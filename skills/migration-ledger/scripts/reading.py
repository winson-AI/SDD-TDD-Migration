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
# A step with no UI, reuse, telemetry or lean-leaf scope stays under this; lower it when cards shrink, never raise it.
TYPICAL_BUDGET = 35_000
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
# audit-scope.md sections by operation; an audit operation outside this table reads the whole file.
D1, D2, D3, D4, D5 = ('1. 所有模块执行阶段结束后统一启动', '2. 收集、根因分析与 finding 路由', '3. 按问题依赖交错修复和回归',
                      '4. 失败隔离与审计报告', '5. 人工审核后恢复')
PROBLEM = ['问题审计与最终审计', '问题处理']
FINAL = ['入口与范围', '收尾的实际执行契约', '问题处理']
AUDIT_OPS = {
    'audit-collect': [D1, D2], 'audit-plan': [D2], 'audit-route-batch': [D2, D3], 'audit-route': [D2, D3],
    'audit-work': [D3, D4], 'audit-retest': [D3, D4], 'audit-block': [D3, D4], 'audit-verdict': [D3, D4],
    'audit-release': [D5], 'audit-defer': ['问题处理', '活动审计的游标恢复'], 'repair-accept': [D3, '问题处理'],
    'audit-resume': PROBLEM, 'problem-assign': PROBLEM, 'problem-audit': PROBLEM,
    'audit-assign': FINAL, 'audit': FINAL, 'audit-unavailable': ['活动审计的游标恢复', '收尾的实际执行契约'],
    'audit-revoke': ['活动审计的游标恢复'],
}
# The module orchestrator's guard and loop rules apply everywhere; the rest only to the operations that use them.
MO_OPS = {
    'freeze': ['Freeze / DoD 分开', 'D', 'M'], 'change': ['Freeze / DoD 分开', 'D', 'M'], 'complete': ['Freeze / DoD 分开'],
    'decompose': ['M*'], 'decompose-accept': ['M*'], 'module-summary': ['M*'], 'plan': ['D', 'M'],
    'assign': [], 'accept': [], 'diagnosis-accept': [], 'resume': [], 'recover': [], 'suspend': [], 'invalidate': [],
    'dependency-ready': [], 'automation-unavailable': [], 'automation-resume': [], 'session': [], 'checkpoint': [],
}
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
    'module-orchestrator': sections('state-machine.md', 'Module-Orchestrator 唯一模块守卫', '有限循环'),
    'global-orchestrator': sections('state-machine.md', '模块隔离与全量收尾'),
    'auditor': [],
    'escalation': [(P + 'progress-recovery.md', None)],
}
# Operation families: (role, family) -> extra sections. Families come from family().
OPS = {
    ('global-orchestrator', 'plan'): sections('module-decomposition.md', '总则', '1. 三层职责', '2. 全局可见，按分配范围执行', '3. 分配与登记门禁',
                                              '6. 二方库作为逐层规划依据', '7. 拆分与任务规划的上下文验收', '四维父子覆盖')
    + sections('project-context.md', '总则')
    + sections('dimension-slicing.md', '总则') + [('skills/migration-global/references/slicing.md', '总则')],
    ('global-orchestrator', 'source'): [(P + 'source-changes.md', None)],
    ('auditor', 'code-review'): [(P + 'audit-code-review.md', None)] + sections('audit-scope.md', '总则', '入口与范围', '代码治理前置'),
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


def audit_sections(operation):
    if operation not in AUDIT_OPS:
        return [(P + 'audit-scope.md', None)]
    return sections('audit-scope.md', '总则', *AUDIT_OPS[operation])


def op_sections(role, operation):
    """Sections that depend on the operation inside a family."""
    fam = family(role, operation)
    if fam == 'audit':
        items = audit_sections(operation)
        if role == 'auditor':
            items += sections('audit-code-review.md', '顺序与职责', 'Ledger 接口')
        elif role == 'global-orchestrator':
            if operation in ('audit-assign', 'audit-collect', 'audit-unavailable', 'audit'):
                items += sections('state-machine.md', 'Auditor 与全局完成')
            if operation in ('audit-assign', 'audit'):
                items += sections('migration-report.md', '总则')
        return items
    if role == 'module-orchestrator':
        extra = MO_OPS.get(operation)
        if extra is None:  # unknown operation: everything the module orchestrator may need
            extra = ['Freeze / DoD 分开', 'D', 'M']
        items = []
        for name in extra:
            if name == 'D':
                items += sections('dimension-slicing.md', '总则')
            elif name == 'M':
                items += sections('module-decomposition.md', '总则')
            elif name == 'M*':
                items += sections('module-decomposition.md', '总则', '1. 三层职责', '2. 全局可见，按分配范围执行', '3. 分配与登记门禁',
                                  '4. 独立执行、父看护与统一审计', '6. 二方库作为逐层规划依据', '7. 拆分与任务规划的上下文验收',
                                  '父 MO 统一命名', '四维父子覆盖', '父级批量冻结信封')
            else:
                items += sections('state-machine.md', name)
        return items
    return OPS.get((role, fam), [])


def skill_sections(path, test_scope=None):
    """The execution rules of a role skill; the pointer and interface boilerplate every skill repeats is not part of a card."""
    names = re.findall(r'(?m)^## (.*)$', (PACKAGE / path).read_text())
    keep = [n for n in names if n not in ('1. 定位', '4. 接口契约')
            and (not n.startswith('7. Harmony') or test_scope in ('automation', 'visual'))]
    return [(path, n) for n in keep]


def topic_flag(topic):
    """Which Ledger fact makes a row of an Agent's 专题义务 table relevant; None means always."""
    for pattern, flag in (('埋点', 'telemetry'), ('UI|视觉|手势', 'ui'), ('复用|provider|fidelity|来源', 'reuse'),
                          ('轻量叶子|功能完备', 'planning'), ('代码治理|自动化缺测|投影核验', 'audit'), ('知识', 'knowledge')):
        if re.search(pattern, topic):
            return flag
    return None


def agent_topics(path, flags):
    text = (PACKAGE / path).read_text()
    m = re.search(r'(?ms)^## 专题义务\n.*', text)
    rows = [line.split('|')[1].strip() for line in (m.group(0).splitlines() if m else []) if line.startswith('| ')]
    rows = [r for r in rows if r not in ('专题',) and not set(r) <= {'-', ' '}]
    return tuple(r for r in rows if topic_flag(r) is None or flags.get(topic_flag(r)))


PLANNING_OPERATIONS = ('register', 'global-plan', 'decompose', 'decompose-accept', 'module-summary', 'freeze', 'plan', 'change')


def _cells(line):
    return [c.strip().strip('`') for c in line.strip().strip('|').split('|')]


def _rows(block, keys):
    """The table header plus the rows whose first cell is one of `keys` (an `@a,b` selector)."""
    lines = block.splitlines(keepends=True)
    table = [i for i, line in enumerate(lines) if line.startswith('|')]
    keep = [lines[0]] + [lines[i] for i in table[:2]] + [lines[i] for i in table[2:] if _cells(lines[i])[0] in keys]
    return ''.join(keep)


def _topic_rows(text, topics):
    out, inside = [], False
    for line in text.splitlines(keepends=True):
        if line.startswith('## '):
            inside = line.strip() == '## 专题义务'
        if inside and line.startswith('| ') and _cells(line)[0] not in topics | {'专题'} and not set(_cells(line)[0]) <= {'-', ' '}:
            continue
        out.append(line)
    return ''.join(out)


@lru_cache(maxsize=None)
def section(path, heading=None, topics=None):
    """Text of one Markdown section: from its heading to the next heading of the same or higher level.

    `heading@a,b` keeps only the table rows whose first cell is a or b; `topics` filters an Agent's 专题义务 table."""
    text = (PACKAGE / path).read_text()
    if heading is None:
        return _topic_rows(text, set(topics)) if topics is not None else text
    name, _, keys = heading.partition('@')
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        match = re.match(r'(#+)\s+(.*?)\s*$', line)
        if match and match.group(2) == name:
            level = len(match.group(1))
            end = next((j for j in range(i + 1, len(lines))
                        if re.match(r'#{1,%d}\s' % level, lines[j])), len(lines))
            block = ''.join(lines[i:end])
            return _rows(block, set(keys.split(','))) if keys else block
    raise KeyError(f'{path}#{heading}')


@lru_cache(maxsize=None)
def matrix_keys():
    block = section(P + 'local-runtime.md', '操作矩阵')
    return {_cells(line)[0] for line in block.splitlines() if line.startswith('|')}


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


def entries(role, test_scope=None, ui=False, reuse=False, operation=None, telemetry=False, lean=False, rows=()):
    agent, skill = ROLE.get(role, [None, None])
    items = list(CORE) + [(agent, None)] + skill_sections(skill, test_scope) + STEP.get(role, [])
    items += op_sections(role, operation)
    selected = [k for k in rows if k in matrix_keys()]
    if selected:
        items += sections('local-runtime.md', '操作矩阵@' + ','.join(selected))
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
    operation = step.get('operation')
    ui, reuse = bool(m) and ui_scope(m), bool(plan.get('reuse_plan_ref')) or bool(s.get('reuse_required'))
    telemetry = telemetry_scope(role, m)
    lean = bool(m) and (bool(m.get('lean_leaf')) or bool(s.get('fixer_self_diagnosis')))
    rows = ([operation] if operation else []) + (['submit'] if step.get('worker_role') else [])
    chosen = entries(role, step.get('test_scope'), ui=ui, reuse=reuse, operation=operation, telemetry=telemetry,
                     lean=lean and role in ('fixer', 'implementer'), rows=rows)
    audit = bool(operation and (operation.startswith('audit') or operation.startswith('problem'))) or role == 'auditor' \
        or bool(m and (m.get('audit_fix_grant') or m.get('audit_batch_id')))
    flags = {'ui': ui, 'reuse': reuse, 'telemetry': telemetry, 'audit': audit,
             'planning': role == 'spec-designer' or operation in PLANNING_OPERATIONS or lean,
             'knowledge': bool(s.get('dependency_resolution_required')) or reuse}
    out = []
    for path, heading in chosen:
        topics = agent_topics(path, flags) if path.startswith('Agents/') else None
        text = section(path, heading, topics)
        out.append({'ref': path, 'section': heading, 'bytes': len(text.encode()),
                    'sha256': hashlib.sha256(text.encode()).hexdigest(), **({'topics': list(topics)} if topics is not None else {})})
    return out


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
                   f'{section(row["ref"], row["section"], tuple(row["topics"]) if "topics" in row else None).rstrip()}\n\n' for row in rows)
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
