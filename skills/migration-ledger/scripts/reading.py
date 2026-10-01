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
PROTOCOL_BUDGET = 556_000
FILE_BUDGET = 34_000
PROTOCOL_GLOBS = ('AGENTS.md', 'Agents/*.md', 'skills/*/SKILL.md', 'skills/*/references/*.md', 'command/*.md', 'template/INDEX.md')

P = 'skills/migration-protocol/references/'


def sections(name, *headings):
    return [(P + name, heading) for heading in headings]


# Every card carries the red lines, the shared protocol and the three rules that apply to every dispatch.
CORE = [('AGENTS.md', '四条红线'), ('skills/migration-protocol/SKILL.md', None)] + sections(
    'runtime.md', '总则') + sections('context-readiness.md', '总则') + sections('storage-layout.md', '总则')
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
AUDIT_FINISH = '默认收尾：修复后验证，失败待人工'
# Sections the role needs at every step; operation families add to them (see family()).
STEP = {
    'spec-designer': sections('openspec.md', '六件套映射', '基线与 Delta', '冻结算法', '变更控制', '决策边界与执行基线', '四维完整性索引')
    + sections('dimension-slicing.md', '总则', '7. 任务级四维分析契约') + sections('semantic-extraction.md', '总则')
    + sections('testing.md', '设计模式与执行模式', '静态规格闭合'),
    'implementer': sections('local-runtime.md', '阶段结果') + sections('context-readiness.md', '2. 精确插入节点')
    + sections('dimension-slicing.md', '7. 任务级四维分析契约'),
    'fixer': sections('local-runtime.md', '阶段结果') + sections('state-machine.md', '有限循环')
    + sections('build-automation.md', '本地一轮的预算单位') + sections('context-readiness.md', '2. 精确插入节点'),
    'diagnostician': sections('state-machine.md', '有限循环') + sections('testing.md', '断言与结果')
    + sections('engineering-disciplines.md', '1. Foundation / 迁移知识执行与冻结'),
    'module-orchestrator': sections('state-machine.md', 'Module-Orchestrator 唯一模块守卫', 'Freeze / DoD 分开', '有限循环')
    + sections('module-decomposition.md', '总则') + sections('dimension-slicing.md', '总则'),
    'global-orchestrator': sections('state-machine.md', '模块隔离与全量收尾'),
    'auditor': [],
    'escalation': [(P + 'progress-recovery.md', None)],
}
# Operation families: (role, family) -> extra sections. Families come from family().
OPS = {
    ('module-orchestrator', 'audit'): sections('audit-scope.md', AUDIT_FINISH),
    ('global-orchestrator', 'plan'): [(P + 'module-decomposition.md', None)] + sections('project-context.md', '总则')
    + sections('dimension-slicing.md', '总则') + [('skills/migration-global/references/slicing.md', '总则')],
    ('global-orchestrator', 'audit'): sections('state-machine.md', 'Auditor 与全局完成') + [(P + 'audit-scope.md', None)]
    + sections('migration-report.md', '总则'),
    ('global-orchestrator', 'source'): [(P + 'source-changes.md', None)],
    ('auditor', 'code-review'): [(P + 'audit-code-review.md', None)] + sections('audit-scope.md', '总则', '入口与范围', '代码治理前置'),
    ('auditor', 'audit'): [(P + 'audit-scope.md', None)] + sections('audit-code-review.md', '顺序与职责', 'Ledger 接口'),
}
TEST_SCOPE = {
    'build': sections('build-automation.md', '总则', '3. 冻结路径与分阶段证据') + sections('testing.md', '断言与结果'),
    'unit': sections('build-automation.md', '总则') + sections('testing.md', '逻辑单测', '断言与结果'),
    'static': sections('build-automation.md', '总则') + sections('testing.md', '静态规格闭合'),
    'automation': sections('build-automation.md', '总则') + sections('testing.md', '断言与结果', '本地执行与严格结果验收')
    + sections('build-automation.md', '4. 自动化环境缺失：直接记 Yellow 并继续'),
    'visual': sections('build-automation.md', '总则') + sections('ui-fidelity.md', '视觉对齐 = automation 第二层（不是独立阶段）')
    + [(P + 'visual-execution.md', None)],
}
# Triggered by facts the Ledger already holds: UI applicability, a reuse plan, telemetry, the lean local-repair path.
UI = {
    'spec-designer': sections('ui-fidelity.md', 'UI 证据绑定', '精确性纪律') + sections('domain-tools.md', '总则'),
    'implementer': sections('ui-fidelity.md', '基线前移：截图指导实现，而非事后比对', '精确性纪律')
    + sections('domain-tools.md', '总则', '资源执行与事实绑定'),
    'fixer': sections('ui-fidelity.md', '精确性纪律') + sections('domain-tools.md', '总则'),
    'test-runner': sections('domain-tools.md', '总则'),
    'auditor': sections('domain-tools.md', '总则'),
}
REUSE_GENERAL = sections('reuse-dependencies.md', '总则')
REUSE = {
    'spec-designer': sections('reuse-dependencies.md', '5. 需求映射与 OpenSpec'),
    'implementer': sections('reuse-dependencies.md', '6. Coding、测试与失败处理', '9. 目标已有实现与二方库冗余：直接重构复用'),
    'fixer': sections('reuse-dependencies.md', '6. Coding、测试与失败处理'),
}
TELEMETRY = sections('telemetry.md', '总则')
LEAN = sections('module-decomposition.md', '总则')
PLANNING_ROLES = ('global-orchestrator', 'module-orchestrator', 'spec-designer')


def family(role, operation):
    """Which part of the role's duties an operation belongs to; only roles with distinct duty sets have families."""
    operation = operation or ''
    audit = operation.startswith('audit') or operation in ('problem-assign', 'problem-audit', 'repair-accept')
    if role == 'auditor':
        return 'code-review' if operation == 'audit-code-review' else 'audit'
    if role == 'global-orchestrator':
        return 'source' if operation in ('source-review', 'reconfigure-sources') else 'audit' if audit else 'plan'
    if role == 'module-orchestrator':
        return 'audit' if audit else 'base'
    return 'base'


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


def entries(role, test_scope=None, ui=False, reuse=False, operation=None, telemetry=False, lean=False):
    items = list(CORE) + [(path, None) for path in ROLE.get(role, [])] + STEP.get(role, [])
    items += OPS.get((role, family(role, operation)), [])
    if role == 'test-runner':
        items += TEST_SCOPE.get(test_scope, [])
    if ui:
        items += UI.get(role, [])
    if reuse:
        items += REUSE_GENERAL + REUSE.get(role, [])
    if telemetry:
        items += TELEMETRY
    if lean:
        items += LEAN
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item); out.append(item)
    return out


def telemetry_scope(role, m):
    """Planning roles must decide applicability, so they read the rule until it is resolved; executors only when applicable."""
    plan = (m or {}).get('plan')
    status = ((plan or {}).get('telemetry') or {}).get('status')
    return status == 'applicable' or (role in PLANNING_ROLES and status is None)


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
                   reuse=bool(plan.get('reuse_plan_ref')) or bool(s.get('reuse_required')),
                   operation=step.get('operation'), telemetry=telemetry_scope(role, m),
                   lean=bool(m) and (bool(m.get('lean_leaf')) or bool(s.get('fixer_self_diagnosis'))) and role in ('fixer', 'implementer'))
    return [{'ref': path, 'section': heading, 'bytes': len(section(path, heading).encode()),
             'sha256': hashlib.sha256(section(path, heading).encode()).hexdigest()} for path, heading in rows]


# A rejected request points at the section that states the failed gate; advisory, first match wins.
GATES = [
    (r'write scope|undeclared change|write outside', 'engineering-disciplines.md', '写范围核验（可选，默认关闭）'),
    (r'checkpoint', 'engineering-disciplines.md', '模块 Git 检查点（可选，默认关闭）'),
    (r'authoring.diagnostics', 'local-runtime.md', '阶段结果'),
    (r'\bunit\b', 'testing.md', '逻辑单测'),
    (r'static|spec closure|reached_from|production symbol|fake implementation', 'testing.md', '静态规格闭合'),
    (r'readiness|context[-_ ](gate|report|submit)', 'context-readiness.md', '2. 精确插入节点'),
    (r'telemetry', 'telemetry.md', '1. 适用性与非阻塞原则'),
    (r'reuse|provider|capabilit', 'reuse-dependencies.md', '总则'),
    (r'dimension|semantic|resource item|consumer', 'dimension-slicing.md', '总则'),
    (r'visual|alignment', 'ui-fidelity.md', '视觉对齐 = automation 第二层（不是独立阶段）'),
    (r'envelope', 'module-decomposition.md', '父级批量冻结信封'),
    (r'freeze|approv|decision', 'state-machine.md', 'Freeze / DoD 分开'),
    (r'audit', 'audit-scope.md', '总则'),
    (r'fix round|budget|no.progress|local fix', 'state-machine.md', '有限循环'),
    (r'source', 'source-changes.md', '总则'),
    (r'fencing|revision|request id|principal|role denied|stale', 'runtime.md', '事件信封'),
]


def read_hint(reason):
    for pattern, name, heading in GATES:
        if re.search(pattern, str(reason), re.I):
            return {'ref': P + name, 'section': heading}
    return None


def key(row):
    return f'{row["ref"]}#{row["section"] or ""}'


def delivered(rows):
    """Section digests a session holds once it has been handed this card."""
    return {key(row): row['sha256'] for row in rows}


def fresh(rows, held):
    """The rows a session that already holds `held` still has to read."""
    return [row for row in rows if (held or {}).get(key(row)) != row['sha256']]


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
    r.add_argument('--resumed', action='store_true', help='the session already holds earlier cards: write only the new sections')
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
        rows = step['must_read']
        if args.resumed:
            rows = step.get('must_read_new', rows)
            if not rows:
                print(json.dumps({'path': None, 'card_sha256': step['card_sha256'], 'bytes': 0, 'sections': 0}))
                return 0
        print(json.dumps(render(rows, Path(st['run_root']) / 'reports/reading'), ensure_ascii=False))
        return 0
    except (KeyError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
