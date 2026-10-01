"""Per-dispatch reading cards: the protocol sections one role needs for one step.

Each phase stays small and loads references only when triggered. A card names the role
definition, its skill and the exact sections whose gates apply to this step, plus sections that
only trigger for UI or reuse scope. Everything else stays readable on demand; a card never
narrows the four red lines, which every card includes.
"""
import argparse
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parents[3]
READ_BUDGET = 60_000  # UTF-8 bytes per dispatch card
# Ratchet on the whole protocol: lower these when text is consolidated, never raise them to fit new prose.
PROTOCOL_BUDGET = 480_000
FILE_BUDGET = 40_000
PROTOCOL_GLOBS = ('AGENTS.md', 'Agents/*.md', 'skills/*/SKILL.md', 'skills/migration-protocol/references/*.md')

P = 'skills/migration-protocol/references/'
CORE = [('AGENTS.md', '四条红线'), ('skills/migration-protocol/SKILL.md', None)]
ROLE = {
    'global-orchestrator': ['Agents/global-orchestrator.md', 'skills/migration-global/SKILL.md'],
    'module-orchestrator': ['Agents/module-orchestrator.md', 'skills/migration-module/SKILL.md'],
    'spec-designer': ['Agents/spec-designer.md', 'skills/migration-spec/SKILL.md'],
    'implementer': ['Agents/implementer.md', 'skills/migration-implement/SKILL.md'],
    'test-runner': ['Agents/test-runner.md', 'skills/migration-test/SKILL.md'],
    'diagnostician': ['Agents/diagnostician.md', 'skills/migration-diagnose/SKILL.md'],
    'fixer': ['Agents/fixer.md', 'skills/migration-fix/SKILL.md'],
    'auditor': ['Agents/auditor.md', 'skills/migration-audit/SKILL.md'],
    'escalation': ['Agents/escalation.md', 'skills/migration-escalate/SKILL.md'],
}
STEP = {
    'spec-designer': [(P + 'openspec.md', None), (P + 'dimension-slicing.md', '7. 任务级四维分析契约'),
                      (P + 'testing.md', '设计模式与执行模式'), (P + 'testing.md', '静态规格闭合')],
    'implementer': [(P + 'local-runtime.md', '阶段结果'), (P + 'context-readiness.md', '2. 精确插入节点'),
                    (P + 'dimension-slicing.md', '7. 任务级四维分析契约')],
    'fixer': [(P + 'local-runtime.md', '阶段结果'), (P + 'state-machine.md', '有限循环'),
              (P + 'build-automation.md', '本地一轮的预算单位'), (P + 'context-readiness.md', '2. 精确插入节点')],
    'diagnostician': [(P + 'state-machine.md', '有限循环'), (P + 'testing.md', '断言与结果'),
                      (P + 'engineering-disciplines.md', '1. Foundation / 迁移知识执行与冻结')],
    'module-orchestrator': [(P + 'state-machine.md', 'Module-Orchestrator 唯一模块守卫'),
                            (P + 'state-machine.md', 'Freeze / DoD 分开'), (P + 'state-machine.md', '有限循环')],
    'global-orchestrator': [(P + 'state-machine.md', '模块隔离与全量收尾'), (P + 'module-decomposition.md', None)],
    'auditor': [(P + 'audit-scope.md', None), (P + 'audit-code-review.md', None)],
    'escalation': [(P + 'progress-recovery.md', None)],
}
TEST_SCOPE = {
    'build': [(P + 'build-automation.md', '3. 冻结路径与分阶段证据'), (P + 'testing.md', '断言与结果')],
    'unit': [(P + 'testing.md', '逻辑单测'), (P + 'testing.md', '断言与结果')],
    'static': [(P + 'testing.md', '静态规格闭合')],
    'automation': [(P + 'testing.md', '断言与结果'), (P + 'testing.md', '本地执行与严格结果验收'),
                   (P + 'build-automation.md', '4. 自动化环境缺失：直接记 Yellow 并继续')],
    'visual': [(P + 'ui-fidelity.md', '视觉对齐 = automation 第二层（不是独立阶段）'), (P + 'visual-execution.md', None)],
}
UI = {
    'spec-designer': [(P + 'ui-fidelity.md', 'UI 证据绑定'), (P + 'ui-fidelity.md', '精确性纪律')],
    'implementer': [(P + 'ui-fidelity.md', '基线前移：截图指导实现，而非事后比对'), (P + 'ui-fidelity.md', '精确性纪律'),
                    (P + 'domain-tools.md', '资源执行与事实绑定')],
    'fixer': [(P + 'ui-fidelity.md', '精确性纪律')],
}
REUSE = {
    'spec-designer': [(P + 'reuse-dependencies.md', '5. 需求映射与 OpenSpec')],
    'implementer': [(P + 'reuse-dependencies.md', '6. Coding、测试与失败处理'),
                    (P + 'reuse-dependencies.md', '9. 目标已有实现与二方库冗余：直接重构复用')],
    'fixer': [(P + 'reuse-dependencies.md', '6. Coding、测试与失败处理')],
}


@lru_cache(maxsize=None)
def section(path, heading=None):
    """Text of one Markdown section: from its heading to the next heading of the same or higher level."""
    text = (PACKAGE / path).read_text()
    if heading is None:
        return text
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        match = re.match(r'(#+)\s+(.*?)\s*$', line)
        if match and match.group(2) == heading:
            level = len(match.group(1))
            end = next((j for j in range(i + 1, len(lines))
                        if re.match(r'#{1,%d}\s' % level, lines[j])), len(lines))
            return ''.join(lines[i:end])
    raise KeyError(f'{path}#{heading}')


def ui_scope(m):
    """UI-only sections trigger when the module's dimension analysis has applicable UI."""
    ref = (m.get('plan') or {}).get('dimension_analysis_ref') or m.get('dimension_analysis_ref')
    if not ref:
        return False
    from contracts import read_json
    try:
        analysis = read_json(ref['path'])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return any(row.get('dimension') == 'UI' and row.get('status') == 'applicable' for row in analysis.get('dimensions', []))


def entries(role, test_scope=None, ui=False, reuse=False):
    items = list(CORE) + [(path, None) for path in ROLE.get(role, [])] + STEP.get(role, [])
    if role == 'test-runner':
        items += TEST_SCOPE.get(test_scope, [])
    if ui:
        items += UI.get(role, [])
    if reuse:
        items += REUSE.get(role, [])
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item); out.append(item)
    return out


def digest_card(rows):
    """Bound to the section text, so a protocol edit changes the digest a host reports back."""
    from contracts import digest
    return digest([{k: row[k] for k in ('ref', 'section', 'sha256')} for row in rows])


def card(s, m, step):
    role = step.get('worker_role') or step.get('role')
    if role not in ROLE:
        return []
    plan = (m or {}).get('plan') or {}
    rows = entries(role, step.get('test_scope'), ui=bool(m) and ui_scope(m),
                   reuse=bool(plan.get('reuse_plan_ref')) or bool(s.get('reuse_required')))
    return [{'ref': path, 'section': heading, 'bytes': len(section(path, heading).encode()),
             'sha256': hashlib.sha256(section(path, heading).encode()).hexdigest()} for path, heading in rows]


def render(rows, output_dir):
    """Write the card as one file named by its digest; a dispatch then hands the role a single path."""
    body = ''.join(f'<!-- {row["ref"]}{"#" + row["section"] if row["section"] else ""} -->\n'
                   f'{section(row["ref"], row["section"]).rstrip()}\n\n' for row in rows)
    name = digest_card(rows)
    target = Path(output_dir) / f'{name}.md'
    if not target.is_file() or target.read_text() != body:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + '.tmp')
        tmp.write_text(body)
        os.replace(tmp, target)
    return {'path': str(target), 'card_sha256': name, 'bytes': len(body.encode()), 'sections': len(rows)}


def show(ref, heading=None):
    """One section of one protocol file, for a role that needs a rule its card did not carry."""
    path = (PACKAGE / ref).resolve()
    if not path.is_relative_to(PACKAGE) or path.suffix != '.md' or not path.is_file():
        raise KeyError(f'not a package Markdown file: {ref}')
    return section(str(path.relative_to(PACKAGE)), heading)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('render', help='write the current step card of one module (or the global step) as one file')
    r.add_argument('--root', required=True)
    target = r.add_mutually_exclusive_group(required=True)
    target.add_argument('--module')
    target.add_argument('--global', dest='is_global', action='store_true')
    sh = sub.add_parser('show', help='print one section of a package Markdown file')
    sh.add_argument('--ref', required=True)
    sh.add_argument('--section')
    args = parser.parse_args()
    try:
        if args.command == 'show':
            sys.stdout.write(show(args.ref, args.section))
            return 0
        from ledger import status
        st = status(args.root)
        step = st['global_next_step'] if args.is_global else next(
            (x for x in st['next_steps'] if x.get('module_id') == args.module), None)
        if not step or not step.get('must_read'):
            raise ValueError('no dispatchable step with a reading card')
        print(json.dumps(render(step['must_read'], Path(st['run_root']) / 'reports/reading'), ensure_ascii=False))
        return 0
    except (KeyError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
