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
TYPICAL_BUDGET = 34_000
# A session holding this much protocol text is better restarted from its checkpoint than fed more; advisory.
ROTATE_BUDGET = 100_000
# Templates a step without triggers hands its role; lower it when templates shrink, never raise it.
TEMPLATE_BUDGET = 20_000
TRIGGERED_TEMPLATE_BUDGET = 56_200  # the most templates any step carries once every trigger holds
# Ratchet on the whole protocol: lower these when text is consolidated, never raise them to fit new prose.
PROTOCOL_BUDGET = 539_000  # consolidated ceiling; reduce after future deduplication
FILE_BUDGET = 32_000
PROTOCOL_GLOBS = ('AGENTS.md', 'Agents/*.md', 'skills/*/SKILL.md', 'skills/*/references/*.md', 'command/*.md', 'template/INDEX.md')

P = 'skills/migration-protocol/references/'


def sections(name, *headings):
    return [(P + name, heading) for heading in headings]


# Every card carries the red lines, the rules of the shared protocol (not its notes on where it sits, assets
# or topics, which the card itself answers) and the three rules that apply to every dispatch.
SHARED = 'skills/migration-protocol/SKILL.md'
CORE = [('AGENTS.md', '四条红线')] + [(SHARED, h) for h in ('2. 核心规则', '3. 模式', '4. 取用', '5. 检查', '7. 业务边界与阶段验收', '通用约定')] + sections(
    'runtime.md', '总则', '渐进加载') + sections('context-readiness.md', '总则') + sections('storage-layout.md', '总则')
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
FINAL = ['入口与范围', '收尾的实际执行契约', '问题处理']
AUDIT_OPS = {
    'audit-collect': [D1, D2], 'audit-plan': [D2], 'audit-route-batch': [D2, D3], 'audit-route': [D2, D3],
    'audit-work': [D3, D4], 'audit-retest': [D3, D4], 'audit-block': [D3, D4], 'audit-verdict': [D3, D4],
    'audit-release': [D5], 'audit-defer': ['问题处理', '活动审计的游标恢复'], 'repair-accept': [D3, '问题处理'],
    'audit-assign': FINAL, 'audit': FINAL, 'audit-unavailable': ['活动审计的游标恢复', '收尾的实际执行契约'],
    'audit-revoke': ['活动审计的游标恢复'], 'audit-recover': ['宿主统一审计'],
}
# The module orchestrator's guard and loop rules apply everywhere; the rest only to the operations that use them.
MO_OPS = {
    'freeze': ['Freeze / DoD 分开', 'D', 'M'], 'change': ['Freeze / DoD 分开', 'D', 'M'], 'complete': ['Freeze / DoD 分开'],
    'redecompose': ['M*'], 'redecompose-accept': ['M*'], 'realloc-request': ['M*'],
    'decompose': ['M*'], 'decompose-accept': ['M*'], 'module-summary': ['M*'], 'plan': ['D', 'M'],
    'assign': [], 'accept': [], 'diagnosis-accept': [], 'resume': [], 'recover': [], 'suspend': [], 'invalidate': [],
    'dependency-ready': [], 'automation-unavailable': [], 'automation-resume': [], 'session': [], 'checkpoint': [],
}
STEP = {
    'spec-designer': sections('openspec.md', '六件套映射', '基线与 Delta', '冻结算法', '变更控制', '决策边界与执行基线', '四维完整性索引')
    + sections('dimension-slicing.md', '总则', '7. 任务级四维分析契约') + sections('semantic-extraction.md', '总则')
    + sections('testing.md', '编码前设计交接', '逻辑单测', '静态规格闭合'),
    'implementer': sections('local-runtime.md', '阶段结果') + sections('context-readiness.md', '2. 精确插入节点')
    + sections('dimension-slicing.md', '7. 任务级四维分析契约'),
    'fixer': sections('local-runtime.md', '阶段结果') + sections('state-machine.md', '有限循环')
    + sections('build-automation.md', '本地一轮的预算单位') + sections('context-readiness.md', '2. 精确插入节点'),
    'diagnostician': sections('state-machine.md', '有限循环') + sections('testing.md', '断言与结果')
    + sections('engineering-disciplines.md', '1. Foundation / 迁移知识执行与冻结'),
    'module-orchestrator': sections('state-machine.md', 'Module-Orchestrator 唯一模块守卫', '有限循环'),
    'global-orchestrator': sections('state-machine.md', '模块隔离与全量收尾'),
    'auditor': [],
    'escalation': sections('progress-recovery.md', '总则', '2. invalidate 后必须有明确出口', '3. 宿主必须消费的进度信号'),
}
# Operation families: (role, family) -> extra sections. Families come from family().
OPS = {
    ('global-orchestrator', 'plan'): sections('module-decomposition.md', '总则', '1. 三层职责', '2. 全局可见，按分配范围执行', '3. 分配与登记门禁',
                                              '6. 二方库作为逐层规划依据', '7. 拆分与任务规划的上下文验收', '四维父子覆盖')
    + sections('project-context.md', '总则')
    + sections('dimension-slicing.md', '总则') + [('skills/migration-global/references/slicing.md', '总则')],
    ('global-orchestrator', 'source'): sections('source-changes.md', '总则', '1. GO：评估来源、归属与影响范围', '5. 信号与 Auditor'),
    ('auditor', 'code-review'): [(P + 'audit-code-review.md', None)] + sections('audit-scope.md', '总则', '入口与范围', '代码治理前置'),
}
TEST_SCOPE = {
    'design': sections('testing.md', '编码前设计交接', 'query', '逻辑单测', '静态规格闭合'),
    'build': sections('build-automation.md', '总则', '3. 冻结路径与分阶段证据')
    + sections('testing.md', '断言与结果', '逻辑单测', '静态规格闭合'),
    'automation': sections('build-automation.md', '总则') + sections('testing.md', '断言与结果', '本地执行与严格结果验收')
    + sections('build-automation.md', '4. 自动化环境缺失：直接记 Yellow 并继续'),
    'visual': sections('build-automation.md', '总则') + sections('ui-fidelity.md', '视觉对齐 = automation 第二层（不是独立阶段）')
    + [(P + 'visual-execution.md', None)],
}
# Triggered by facts the Ledger already holds: UI applicability, a reuse plan, telemetry, the lean local-repair path.
PICTURES = '图片与图标对齐'
COPY, FILL = '文件资源按路径复制', '参数填充'   # what a tool carries to the target: files by path, values by key
UI = {
    'spec-designer': sections('ui-fidelity.md', 'UI 证据绑定', '精确性纪律', PICTURES)
    + sections('resource-transfer.md', '总则', '使用点与闭包', COPY, '参数表', FILL) + sections('domain-tools.md', '总则'),
    'implementer': sections('ui-fidelity.md', '基线前移：截图指导实现，而非事后比对', '精确性纪律', PICTURES)
    + sections('resource-transfer.md', '总则', COPY, FILL) + sections('domain-tools.md', '总则', '资源执行与事实绑定'),
    'fixer': sections('ui-fidelity.md', '精确性纪律', PICTURES) + sections('resource-transfer.md', '总则', COPY, FILL)
    + sections('domain-tools.md', '总则'),
    'test-runner': sections('ui-fidelity.md', PICTURES) + sections('domain-tools.md', '总则'),
    'auditor': sections('ui-fidelity.md', 'UI 证据绑定', PICTURES) + sections('domain-tools.md', '总则'),
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
    audit = operation.startswith('audit') or operation == 'repair-accept'
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
    if operation in ('plan-review', 'planning-reopen'):
        return sections('state-machine.md', '控制主线') + sections('openspec.md', '冻结算法', '变更控制')
    if operation in ('audit-test-assign', 'audit-test-submit'):
        return sections('audit-code-review.md', '宿主目标审计') + sections('audit-scope.md', '收尾的实际执行契约')
    if operation in ('run-review', 'revise-run', 'realloc-request', 'redecompose', 'redecompose-accept'):
        return sections('progress-recovery.md', '同 Run 上游修订') + sections('module-decomposition.md', '3. 分配与登记门禁')
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
            and (not n.startswith('7. Android/Harmony') or test_scope in ('automation', 'visual'))]
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


PLANNING_OPERATIONS = ('register', 'global-plan', 'decompose', 'decompose-accept', 'module-summary', 'freeze', 'plan', 'change', 'redecompose', 'redecompose-accept', 'realloc-request', 'run-review', 'revise-run', 'plan-review', 'planning-reopen')


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


# Blocks of an Agent definition that only apply in some modes of the role; other blocks always stay.
MODE_BLOCKS = {'### 设计', '### 构建', '### 单测与静态审查', '### 自动化', '## 10. 移动端执行器'}
TEST_MODES = {'design': ('### 设计',), 'build': ('### 构建', '### 单测与静态审查'),
              'automation': ('### 自动化', '## 10. 移动端执行器'),
              'visual': ('### 自动化', '## 10. 移动端执行器')}


def _mode_blocks(text, modes):
    out, keep = [], True
    for line in text.splitlines(keepends=True):
        if line.startswith('#'):
            title = line.strip()
            if title in MODE_BLOCKS:
                keep = title in modes
            elif line.startswith('## ') or (line.startswith('### ') and title not in MODE_BLOCKS):
                keep = True
        if keep:
            out.append(line)
    return ''.join(out)


@lru_cache(maxsize=None)
def section(path, heading=None, topics=None, modes=None):
    """Text of one Markdown section: from its heading to the next heading of the same or higher level.

    `heading@a,b` keeps only the table rows whose first cell is a or b; `topics` filters an Agent's 专题义务
    table and `modes` its mode-specific blocks."""
    text = (PACKAGE / path).read_text()
    if heading is None:
        if modes is not None:
            text = _mode_blocks(text, set(modes))
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


def execution_selection(m, step):
    """Accepted contracts take precedence over caller-supplied advisory selectors."""
    if not m or (step.get('worker_role') or step.get('role')) not in ('implementer', 'fixer', 'test-runner') or step.get('mode') == 'design': return None
    assignment = m.get('assignments', {}).get(step.get('assignment_id'), {})
    selection = assignment.get('execution_contract') or step.get('execution_contract') or step.get('payload') or step
    tasks = set(selection.get('task_ids', [])); plan = m.get('plan') or {}
    if not tasks or not tasks <= {t['task_id'] for t in plan.get('tasks', [])} or not plan.get('dimension_trace'): return None
    items = {row['item_id'] for row in plan['dimension_trace'] if tasks.intersection(row['task_ids'])}
    paths = set(selection.get('path_ids') or [pid for t in plan['tasks'] if t['task_id'] in tasks for pid in t['path_ids']])
    return items, paths


def topic_facts(s, m, step):
    """Facts from this assignment, or its selected audit scope; no elective rule disables a gate."""
    from contracts import check_ref, read_json
    facts = dict.fromkeys(('ui', 'resources', 'pictures', 'copy', 'parameters', 'api'), False)
    selected = step.get('module_ids') or (s.get('audit_assignment') or {}).get('module_ids')
    modules = [m] if m else [obj for mid, obj in s.get('modules', {}).items() if not selected or mid in selected]
    for obj in modules:
        selection = execution_selection(obj, step) if m else None
        ref = (obj.get('plan') or {}).get('dimension_analysis_ref') or obj.get('dimension_analysis_ref')
        if not ref:
            continue
        try:
            analysis = read_json(check_ref(ref))
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            continue  # the dispatch gate reports invalid evidence; loading does not repair or authorize it
        facts['api'] |= bool(analysis.get('api_inventory_ref')) and selection is None
        selected_ui = any(row.get('dimension') == 'UI' and any(item.get('item_id') in selection[0] for item in row.get('items', []))
                          for row in analysis.get('dimensions', [])) if selection else False
        for row in analysis.get('dimensions', []):
            if row.get('status') != 'applicable':
                continue
            items = [item for item in row.get('items', []) if selection is None or item.get('item_id') in selection[0]]
            if selection is not None and not items and not (row.get('copy_plan_ref') and selected_ui): continue
            facts['ui'] |= row.get('dimension') == 'UI'
            facts['resources'] |= row.get('dimension') == 'Resource'
            facts['copy'] |= bool(row.get('copy_plan_ref'))
            facts['parameters'] |= bool(row.get('parameter_sheet_ref'))
            for item in items:
                facts['api'] |= bool(item.get('api_ids') or item.get('api_binding'))
                model = item.get('semantic_model') or {}
                facts['pictures'] |= bool(model.get('image_checks') or item.get('source_resource') or item.get('source_signal'))
        # Planners need discovery before choosing a resource strategy; executors consume only frozen facts.
        if step.get('role') in PLANNING_ROLES or step.get('worker_role') == 'spec-designer':
            facts['pictures'] |= facts['ui']
            facts['parameters'] |= facts['ui'] and bool((s.get('target_resources') or {}).get('parameters'))
            facts['copy'] |= facts['resources'] and bool((s.get('target_resources') or {}).get('copy'))
    for path in (s.get('global_paths', []) if m is None else (m.get('plan') or {}).get('paths', [])):
        selection = execution_selection(m, step)
        if selection is not None and path['path_id'] not in selection[1]: continue
        facts['ui'] |= path.get('kind') == 'visual' or bool(path.get('interaction_id'))
        facts['pictures'] |= bool(path.get('image_check_ids'))
    return facts


def reasoning_sections(m):
    """Extra methods activate on observed uncertainty/stagnation, not on role alone."""
    if not m: return []
    bad = [row for row in {**m.get('results', {}), **m.get('repair_findings', {})}.values() if row.get('quality') != 'green-passed']
    if m.get('no_progress_rounds', 0): return sections('progress-recovery.md', '1. 校验范围') + sections('domain-tools.md', '证据保留与修复闭环')
    if any((row.get('root_cause') or {}).get('confidence') != 'confirmed' for row in bad): return sections('semantic-extraction.md', '层与 schema')
    return []


def entries(role, test_scope=None, ui=False, reuse=False, operation=None, telemetry=False, lean=False, rows=(), facts=None):
    agent, skill = ROLE.get(role, [None, None])
    items = list(CORE) + [(agent, None)] + skill_sections(skill, test_scope) + STEP.get(role, [])
    items += op_sections(role, operation)
    if operation == 'assign' and role == 'module-orchestrator':
        items += sections('runtime.md', '显式执行任务')
    if operation == 'session':
        items += sections('host-integration.md', '会话交接')
    if operation in ('freeze', 'plan'):
        items += sections('state-machine.md', '控制主线')
    if operation in ('decompose', 'decompose-accept', 'global-plan'):
        items += sections('module-decomposition.md', '验证边界')
    selected = [k for k in rows if k in matrix_keys()]
    if selected:
        items += sections('local-runtime.md', '操作矩阵@' + ','.join(selected))
    if role == 'test-runner':
        items += TEST_SCOPE.get(test_scope, [])
    if ui:
        chosen = UI.get(role, [])
        if facts is not None:
            chosen = [(path, heading) for path, heading in chosen
                      if not (path.endswith('resource-transfer.md') and not facts.get('resources'))
                      and not (heading == COPY and not facts.get('copy'))
                      and not (heading in ('参数表', FILL) and not facts.get('parameters'))
                      and not (heading == PICTURES and not facts.get('pictures'))]
        items += chosen
    if facts and facts.get('api'):
        items += sections('resource-transfer.md', 'API 与 URL 契约')
    if facts and facts.get('parameters'):
        items += sections('resource-transfer.md', '动态参数与布局结构')
    if facts and facts.get('resources') and not ui:
        items += sections('resource-transfer.md', '总则', '使用点与闭包')
        if facts.get('copy'):
            items += sections('resource-transfer.md', COPY)
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
    facts = topic_facts(s, m, step)
    ui, reuse = facts['ui'] and not (role == 'test-runner' and step.get('test_scope') == 'build'), bool(plan.get('reuse_plan_ref')) or bool(s.get('reuse_required'))
    telemetry = telemetry_scope(role, m)
    lean = bool(m) and (bool(m.get('lean_leaf')) or bool(s.get('fixer_self_diagnosis')))
    rows = ([operation] if operation else []) + (['context-submit', 'submit'] if step.get('worker_role') else [])
    chosen = entries(role, step.get('test_scope'), ui=ui, reuse=reuse, operation=operation, telemetry=telemetry,
                     lean=lean and role in ('fixer', 'implementer'), rows=rows, facts=facts)
    chosen += reasoning_sections(m)
    if role == 'spec-designer' or (step.get('mode') == 'design' and role == 'module-orchestrator'):
        chosen += sections('testing.md', '编码前设计交接')
    if (role == 'module-orchestrator' and (m or {}).get('change_request') and operation in ('plan-review', 'freeze')
            or role == 'auditor' and any(x.get('task_revalidation', {}).get('mode') == 'partial' for x in s.get('modules', {}).values())):
        chosen += sections('openspec.md', 'TASK 局部重验')
    chosen = list(dict.fromkeys(chosen))  # a section reaches a card once, whichever rule asked for it
    audit = bool(operation and (operation.startswith('audit') or operation.startswith('problem'))) or role == 'auditor' \
        or bool(m and (m.get('audit_fix_grant') or m.get('audit_batch_id')))
    flags = {'ui': ui, 'reuse': reuse, 'telemetry': telemetry, 'audit': audit,
             'planning': role == 'spec-designer' or operation in PLANNING_OPERATIONS or lean,
             'knowledge': bool(s.get('dependency_resolution_required')) or reuse}
    out = []
    for path, heading in chosen:
        agent = path.startswith('Agents/')
        topics = agent_topics(path, flags) if agent else None
        modes = TEST_MODES.get(step.get('test_scope')) if agent and role == 'test-runner' else None
        text = section(path, heading, topics, modes)
        out.append({'ref': path, 'section': heading, 'bytes': len(text.encode()),
                    'sha256': hashlib.sha256(text.encode()).hexdigest(), **({'topics': list(topics)} if topics is not None else {}),
                    **({'modes': list(modes)} if modes is not None else {})})
    return out


def text_of(row):
    return section(row['ref'], row['section'], tuple(row['topics']) if 'topics' in row else None,
                   tuple(row['modes']) if 'modes' in row else None)


def summary(rows):
    """What a polling host needs to know about a card; the rows themselves come from render."""
    return {'bytes': sum(row['bytes'] for row in rows), 'sections': len(rows)}


# Templates a step instantiates, so no role has to read the template index to find them.
TEMPLATES = {
    'global-orchestrator': {'plan': ['module-input.json', 'global-plan.json', 'feature-inventory.json', 'dimension-analysis.json',
                                     'module-slicing.json', 'context-readiness.json'],
                            'audit': ['migration-report.md'], 'source': ['source-impact.json']},
    'module-orchestrator': {'base': ['status.md'], 'audit': ['status.md']},
    'spec-designer': {'base': ['stage-plan.json', 'proposal.md', 'spec.md', 'design.md', 'tasks.md',
                               'upstream-test-plan.json', 'change-impact.json', 'context-readiness.json']},
    'implementer': {'base': ['implementation.md', 'context-readiness.json']},
    'fixer': {'base': ['implementation.md', 'fix-note.json', 'change-request.md', 'context-readiness.json']},
    'diagnostician': {'base': ['diagnosis.md']},
    'escalation': {'base': ['escalation.md', 'human-decision.json']},
    'auditor': {'code-review': ['audit-code-review.json', 'audit-change-inventory.md'],
                'audit': ['audit-closure-plan.json', 'audit-report.md', 'audit-review.json', 'test-result.json']},
    'test-runner': {'base': ['stage-result.json', 'test-result.json', 'context-readiness.json']},
}
# Module-orchestrator templates by operation; an operation outside the table only updates the module status.
MO_TEMPLATES = {'freeze': ['checklist.md', 'plan-review.json', 'change-impact.json', 'batch-envelope.json'], 'plan-review': ['plan-review.json'], 'planning-reopen': ['status.md'],
                'change': ['change-impact.json'], 'complete': ['checklist.md', 'status.md'],
                'decompose': ['module-decomposition.json', 'dimension-analysis.json', 'batch-envelope.json'],
                'module-summary': ['status.md'], 'suspend': ['implementation-gap.json', 'status.md'],
                'assign': ['test-design-input.json', 'execution-assignment.json'], 'accept': ['status.md'], 'diagnosis-accept': ['status.md']}
SCOPE_TEMPLATES = {'build': ['test-adapter.json'], 'automation': ['test-adapter.json', 'harmony-test-adapter.json', 'harmony-config.json', 'interaction-evidence.json'],
                   'visual': ['visual-test-path.json', 'visual-alignment.json', 'visual-capture-execution.json', 'visual-test-adapter.json',
                              'visual-execution.json', 'visual-request.json']}
TRIGGER_TEMPLATES = {
    'reuse': {'global-orchestrator': ['reuse-catalog.json', 'reuse-source.json'], 'spec-designer': ['reuse-plan.json', 'reuse-fidelity.md']},
    'telemetry': {'global-orchestrator': ['telemetry-analysis.md'], 'module-orchestrator': ['telemetry-analysis.md'],
                  'spec-designer': ['telemetry-contract.json', 'telemetry-analysis.md'], 'auditor': ['telemetry-analysis.md']},
    'ui': {'spec-designer': ['semantic-model.json', 'ui-state-test-design.md', 'domain-worker-request.json', 'dimension-analysis.json'],
           'implementer': ['resource-request.json'], 'fixer': ['resource-request.json']},
    'knowledge': {'spec-designer': ['knowledge-request.json'], 'implementer': ['knowledge-request.json'],
                  'fixer': ['knowledge-request.json'], 'diagnostician': ['knowledge-request.json']},
}


def templates(s, m, step):
    if step.get('operation') in ('run-review', 'revise-run'):
        return ['template/run-revision.json', 'template/context-readiness.json']
    if step.get('operation') == 'retrospect':
        return ['template/retrospective.json']
    role = step.get('worker_role') or step.get('role')
    if role not in ROLE:
        return []
    plan = (m or {}).get('plan') or {}
    table = TEMPLATES.get(role, {})
    names = list(table.get(family(role, step.get('operation')), table.get('base', [])))
    if role == 'module-orchestrator' and family(role, step.get('operation')) == 'base':
        names = list(MO_TEMPLATES.get(step.get('operation'), ['status.md']))
        if (m or {}).get('change_request') and step.get('operation') in ('plan-review', 'freeze'):
            names.append('task-independence.json')
    if role == 'test-runner':
        names += SCOPE_TEMPLATES.get(step.get('test_scope'), [])
    if step.get('mode') == 'design':
        names = ['test-design-input.json', 'test-design-result.json', 'test-paths.json', 'harmony-test-path.json', 'context-readiness.json']
    reuse = bool(plan.get('reuse_plan_ref')) or bool(s.get('reuse_required'))
    facts = topic_facts(s, m, step)
    active = {'reuse': reuse, 'telemetry': telemetry_scope(role, m), 'ui': facts['ui'] and not (role == 'test-runner' and step.get('test_scope') == 'build'),
              'knowledge': bool(s.get('dependency_resolution_required')) or reuse}
    for trigger, by_role in TRIGGER_TEMPLATES.items():
        if active[trigger]:
            names += by_role.get(role, [])
    if role in PLANNING_ROLES:
        if facts['api']: names += ['api-inventory.json']
        if facts['parameters']: names += ['parameter-binding.json']
    return ['template/' + n for n in dict.fromkeys(names)]


# A rejected request points at the section that states the failed gate; advisory, first match wins.
GATES = [
    (r'host handoff|cold recovery|rotation checkpoint|global hint|session restoration', 'host-integration.md', '会话交接'),
    (r'test asset|test PATH preparation|test preparation', 'testing.md', '编码前设计交接'),
    (r'condition review|condition refs', 'resource-transfer.md', '动态参数与布局结构'),
    (r'API |api_inventory|api_obligations', 'resource-transfer.md', 'API 与 URL 契约'),
    (r'runtime expression|runtime/layout|layout keywords|structural mapping|parameter mapping', 'resource-transfer.md', '动态参数与布局结构'),
    (r'hash mismatch|absolute evidence path|missing file', 'runtime.md', '请求与事件'),   # first: the file named in the message may sit in a path of any other topic
    (r'unknown reference id', 'context-readiness.md', '3. 报告与传递'),
    (r'is not settled|target_resources (takes|\.declined)|target_resources\.declined', 'resource-transfer.md', '总则'),
    (r'parameter[ _](sheet|fill|file|convention)|parameter_fill|recorded (value )?parameters?|values to parameter|a parameter is'
     r'|expressions the Spec|tokens the Spec|typed value|(not_applicable|settled|token) record|share one key|target_resources\.parameters'
     r'|\b(layout|layer|code|values):\S+: deviation', 'resource-transfer.md', FILL),
    (r'file resources|usage[ _]exclusion|layout_helpers', 'resource-transfer.md', '使用点与闭包'),
    (r'cop(y|ied) (plan|path|target|resources?)|copy_blocker|target_resources\.copy|resource-sync|one target file|index different files'
     r'|refusing to overwrite|target_resource (must|needs)|file of the target project|never names|not the legacy file|legacy (entry|vector)',
     'resource-transfer.md', COPY),
    (r'design |test.design|设计', 'testing.md', '编码前设计交接'),
    (r'TASK independence', 'openspec.md', 'TASK 局部重验'),
    (r'execution capture|output capture|excerpt|committed.*hash', 'testing.md', '日志与按需追溯'),
    (r'write scope|undeclared change|write outside', 'engineering-disciplines.md', '写范围核验（可选，默认关闭）'),
    (r'checkpoint', 'engineering-disciplines.md', '模块 Git 检查点（可选，默认关闭）'),
    (r'authoring.diagnostics', 'local-runtime.md', '阶段结果'),
    (r'JUnit|required_test_ids|unit_report|\bunit\b', 'testing.md', '逻辑单测'),
    (r'verification |acceptance cases|case_acceptance|supporting slice|accepted by|already accepts|slices form|independence review', 'module-decomposition.md', '验证边界'),
    (r'behavior_review|behavior review|behavior contract|shared capability', 'module-decomposition.md', '3. 分配与登记门禁'),
    (r'Scenario|scenario|Requirement-ID', 'openspec.md', '冻结算法'),
    (r'static|spec closure|reached_from|production symbol|fake implementation', 'testing.md', '静态规格闭合'),
    (r'readiness|context[-_ ](gate|report|submit)', 'context-readiness.md', '2. 精确插入节点'),
    (r'telemetry', 'telemetry.md', '1. 适用性与非阻塞原则'),
    (r'image[ _-]?(check|parity|source)|picture|deviation|render-reference', 'ui-fidelity.md', PICTURES),
    (r'watchdog|notice', 'watchdog.md', '总则'),
    (r'journal|workflow hub|hub routing|workflow\.md|event artifact|archive entry|projection', 'storage-layout.md', 'OpenSpec 投影完整性收尾门禁'),
    (r'retirement|run impact|run revision|run review|root revision|root update|contract IDs|replacement IDs', 'progress-recovery.md', '同 Run 上游修订'),
    (r'code review|code findings|goal review|governance|recovery resolutions', 'audit-code-review.md', 'Ledger 接口'),
    (r'finding|repair owner|leftover|owner (not|must|prerequisites)|unresolved (human|verification)|block reason|retry contract', 'audit-scope.md', '问题处理'),
    (r'feature|boundary (review|issue|question|modules|kind)|functional list|test case summary', 'context-readiness.md', '功能清单来源与完备性'),
    (r'project (context|configuration|placeholders|id)|context snapshot|run context|override field|persistent default|build configuration'
     r'|configuration patch|context belongs|single-module requires', 'project-context.md', '运行时固化'),
    (r'context (stage|producer|checklist|verdict|check|understanding|blocked|blocker|test)|wrong context|build not ready|observed failure',
     'context-readiness.md', '3. 报告与传递'),
    (r'statechart|icu messages|strategy new has no legacy', 'semantic-extraction.md', '层与 schema'),
    (r'ui tree|ui_tree|UI node|UI evidence|ui_evidence|UI implementation|screen (must|needs)|runtime ?index|tree modes|native UI', 'ui-fidelity.md', 'UI 证据绑定'),
    (r'capture|baseline screenshot|frozen baseline|reference manifest|installation command', 'ui-fidelity.md', 'capture / 构建产物契约'),
    (r'platform api_level|values (target|entry)|value_xml_exact|loader_mapping|signal exclusion|manual implementation', 'ui-fidelity.md', '精确性纪律'),
    (r'impact review|within-envelope', 'openspec.md', '变更控制'),
    (r'worker (result|phase)|assignment|unsupported worker role|invalid module id|incorrect global/module scope|accepted before testing'
     r'|unmapped|result (actor|kind|schema)|baseline mismatch|current code changed|owner mismatch|duplicate code files', 'local-runtime.md', '操作矩阵'),
    (r'reuse|provider|capabilit', 'reuse-dependencies.md', '总则'),
    (r'configuration[ _]mapping|qualifier|resource_strategy|exact strategy|source baseline|rendition', 'ui-fidelity.md', '精确性纪律'),
    (r'dimension|semantic|resource item|consumer', 'dimension-slicing.md', '总则'),
    (r'visual|alignment', 'ui-fidelity.md', '视觉对齐 = automation 第二层（不是独立阶段）'),
    (r'envelope', 'module-decomposition.md', '父级批量冻结信封'),
    (r'global coverage review|planning requires current|allocation|decomposition|decompose|child |children|submodule|parent |root ',
     'module-decomposition.md', '3. 分配与登记门禁'),
    (r'dependenc|worker still active|module blocked|suspend|resume|not suspended|parallel budget', 'state-machine.md', 'Module-Orchestrator 唯一模块守卫'),
    (r'path|assertion|test_run|retest|receipt|quality|executed', 'testing.md', '断言与结果'),
    (r'task|TASK|SPEC|plan |six-piece|definition|closure|feasibility', 'openspec.md', '冻结算法'),
    (r'freeze|approv|decision', 'state-machine.md', 'Freeze / DoD 分开'),
    (r'audit', 'audit-scope.md', '总则'),
    (r'fix round|budget|no.progress|local fix', 'state-machine.md', '有限循环'),
    (r'source', 'source-changes.md', '总则'),
    (r'fencing|revision|request id|principal|role denied|stale', 'runtime.md', '请求与事件'),
]


# The share of the Ledger's rejection messages that name the section stating their rule. A rejection is where a rule
# that is not on the card gets loaded; raise this when hints are added, never lower it.
HINT_COVERAGE = 0.80


def read_hint(reason):
    for pattern, name, heading in GATES:
        if re.search(pattern, str(reason), re.I):
            return {'ref': P + name, 'section': heading}
    return None


def key(row):
    return f'{row["ref"]}#{row["section"] or ""}'


def delivered(rows):
    """Section digests a holder has once it has been handed this card; a prefix is enough to tell a changed section."""
    return {key(row): row['sha256'][:16] for row in rows}


def fresh(rows, held):
    """The rows a session that already holds `held` still has to read. The red lines are on every card, new or not."""
    return [row for row in rows if row['ref'] == 'AGENTS.md' or not row['sha256'].startswith((held or {}).get(key(row)) or '\0')]


def _slug(heading):
    return re.sub(r'[^\w\- 一-鿿]', '', heading.strip().lower()).replace(' ', '-')


@lru_cache(maxsize=None)
def _heading_of(path, anchor):
    try:
        text = (PACKAGE / path).read_text()
    except OSError:
        return None
    return next((h for h in re.findall(r'(?m)^#+\s+(.*?)\s*$', text) if _slug(h) == anchor.lower()), None)


def unlink(text, ref):
    """A card is read on its own: a link to a whole protocol file becomes plain text, a link to a section
    becomes a selector for `show`, and a template or any other package file is named by its package path."""
    base = (PACKAGE / ref).parent

    def sub(match):
        label, target = match.group(1), match.group(2)
        if re.match(r'[a-z]+:', target):
            return match.group(0)
        path, _, anchor = target.partition('#')
        resolved = (base / path).resolve() if path else (PACKAGE / ref).resolve()
        if not resolved.is_relative_to(PACKAGE):
            return label
        rel = str(resolved.relative_to(PACKAGE))
        if resolved.suffix != '.md' or rel.startswith('template/'):  # a template is opened as a file
            return f'{label}（{rel}）'
        heading = _heading_of(rel, anchor) if anchor else None
        return f'{label}（{rel} § {heading}）' if heading else label
    return re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', sub, text)


FOOTER = ('<!-- 取用 -->\n本卡之外的规则不整份读取：`reading.py show --ref <文件> --section <小节>` 读单节，'
          '上文“（文件 § 小节）”即可直接作为参数。\n')


def render(rows, output_dir, extra=()):
    """Write the card as one file named by its digest; a dispatch then hands the role a single path."""
    body = ''.join(f'<!-- {row["ref"]}{"#" + row["section"] if row["section"] else ""} -->\n'
                   f'{unlink(text_of(row), row["ref"]).rstrip()}\n\n' for row in rows)
    if extra:
        body += '<!-- 本步模板 -->\n' + ''.join(f'- {name}\n' for name in extra) + '\n'
    body += FOOTER
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
        print(json.dumps(render(rows, Path(st['run_root']) / 'reports/reading', step.get('templates', ())), ensure_ascii=False))
        return 0
    except (KeyError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
