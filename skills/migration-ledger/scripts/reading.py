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
READ_BUDGET = 29_100  # UTF-8 bytes per dispatch card: the resident text (red lines, shared rules, the role, the step and its operation)
TOPIC_BUDGET = 25_900  # the topic sections one step lists on demand (UI, resources, reuse, telemetry, the declared platforms' Mains, the legacy, the user's media)
# What one step can make a role read: the resident card and every on-demand topic section it lists, for a registered leaf with a
# plan, every fact trigger on and both platform families declared (test_progressive_fidelity enumerates it). Templates are named
# on the card and fetched one by one when written, so they are ratcheted on their own; lower it when a step hands less, never raise it.
STEP_BUDGET = 51_200
# A step with no UI, reuse, telemetry or lean-leaf scope stays under this; lower it when cards shrink, never raise it.
TYPICAL_BUDGET = 29_100
# A session holding this much protocol text is better restarted from its checkpoint than fed more; advisory.
ROTATE_BUDGET = 100_000
# Templates a step without triggers hands its role; lower it when templates shrink, never raise it.
TEMPLATE_BUDGET = 13_500
TRIGGERED_TEMPLATE_BUDGET = 34_700  # the most templates any step carries once every trigger holds
# What a model is handed is bounded, not the size of the control-flow files: one `show` hands at most one section of this
# size, and a file or section above it is handed as its list of headings to pick from.
SECTION_BUDGET = TOPIC_BUDGET
ENTRY_BUDGET = 4_000  # AGENTS.md, the host's entry; a dispatched role reads its card instead
PROTOCOL_GLOBS = ('AGENTS.md', 'Agents/*.md', 'skills/*/SKILL.md', 'skills/*/references/*.md', 'command/*.md', 'template/INDEX.md')

P = 'skills/migration-protocol/references/'


def sections(name, *headings):
    return [(P + name, heading) for heading in headings]


def platform_keys(s):
    """The declared target platforms as the two families their rules and templates come in: web, and device (android, harmony)."""
    platforms = set((((s or {}).get('test_adapter') or {}).get('device') or {}).get('platforms') or [])
    return [key for key, members in (('web', {'web'}), ('device', {'android', 'harmony'})) if platforms & members]


def platform_sections(s):
    """The Main of each declared platform: the shape of its PATHs for the planner, how it runs them for the executor."""
    return [row for key in platform_keys(s) for row in sections('testing.md', {'web': 'web Main', 'device': 'Harmony Main'}[key])]


# Every card carries the red lines and the rules of the shared protocol (not its notes on where it sits, assets
# or topics, which the card itself answers). The other general sections ride only where they apply.
SHARED = 'skills/migration-protocol/SKILL.md'
CORE = [('AGENTS.md', '四条红线')] + [(SHARED, h) for h in ('2. 核心规则', '3. 模式', '4. 取用', '5. 检查', '通用约定')]
CONTROLLER = sections('runtime.md', '总则', '渐进加载')          # who runs the controller or resumes a session
BOUNDARY = [(SHARED, '7. 业务边界与阶段验收')]                   # who judges business boundaries and stage acceptance
WRITERS = sections('storage-layout.md', '总则')                  # who writes files under the run
READINESS = sections('context-readiness.md', '总则')             # a run that requires readiness reports
CONTROLLER_ROLES = ('global-orchestrator', 'module-orchestrator')
BOUNDARY_ROLES = CONTROLLER_ROLES + ('auditor', 'escalation')
WRITER_ROLES = ('spec-designer', 'implementer', 'fixer', 'test-runner', 'diagnostician', 'auditor')
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
    + sections('testing.md', '编码前设计交接', '逻辑单测'),
    'implementer': sections('local-runtime.md', '阶段结果') + sections('context-readiness.md', '2. 精确插入节点')
    + sections('dimension-slicing.md', '7. 任务级四维分析契约'),
    'fixer': sections('local-runtime.md', '阶段结果') + sections('state-machine.md', '有限循环')
    + sections('build-automation.md', '本地一轮的预算单位') + sections('context-readiness.md', '2. 精确插入节点'),
    'diagnostician': sections('state-machine.md', '有限循环') + sections('testing.md', '断言与结果'),
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
    ('auditor', 'code-review'): sections('audit-code-review.md', '顺序与职责', '审查内容', 'Ledger 接口') + sections('audit-scope.md', '总则', '入口与范围', '代码治理前置'),
}
TEST_SCOPE = {
    'build': sections('build-automation.md', '总则', '3. 冻结路径与分阶段证据')
    + sections('testing.md', '断言与结果', '逻辑单测', '静态规格闭合'),
    'automation': sections('build-automation.md', '总则') + sections('testing.md', '断言与结果', '本地执行与严格结果验收')
    + sections('build-automation.md', '4. 自动化环境缺失：直接记 Yellow 并继续'),
    'visual': sections('build-automation.md', '总则') + sections('ui-fidelity.md', '视觉对齐 = automation 第二层（不是独立阶段）')
    + sections('visual-execution.md', '2. 执行节点', '3. 失败、留存与恢复'),
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


# Rules of a plan the Ledger completes or checks by itself: the task four-dimension analyses, the decision envelope, the
# dimension index; and how a change request runs, until one is open.
LEDGER_KEPT = sections('openspec.md', '变更控制', '决策边界与执行基线', '四维完整性索引') + sections('dimension-slicing.md', '总则', '7. 任务级四维分析契约')
# Where the Ledger drafts a split and completes each leaf, the orchestrator confirms the cut: the rules of a cut written
# by hand are read when it departs from the draft, and a refusal names them.
HAND_CUT = sections('module-decomposition.md', '1. 三层职责', '2. 全局可见，按分配范围执行', '3. 分配与登记门禁', '4. 独立执行、父看护与统一审计',
                    '6. 二方库作为逐层规划依据', '父 MO 统一命名', '四维父子覆盖', '父级批量冻结信封', '验证边界')


def drafted_split(s, m, step):
    """A decompose step whose split `split_draft.py` drafts from the root's feature inventory."""
    return ((step.get('role'), step.get('operation')) == ('module-orchestrator', 'decompose') and 'split' in (step.get('planning_outcomes') or [])
            and bool(s.get('project_context_ref')) and bool((m or {}).get('feature_inventory_ref')))


def audit_sections(operation):
    if operation not in AUDIT_OPS:  # a generic audit dispatch: the entry, the closure contract and problem handling
        return sections('audit-scope.md', '总则', *FINAL)
    return sections('audit-scope.md', '总则', *AUDIT_OPS[operation])


def op_sections(role, operation):
    """Sections that depend on the operation inside a family."""
    if operation in ('plan-review', 'planning-reopen'):
        return sections('state-machine.md', '控制主线') + sections('openspec.md', '冻结算法', '变更控制')
    if operation in ('audit-test-assign', 'audit-test-submit', 'integration-assign', 'integration-submit'):
        return sections('audit-code-review.md', '宿主目标审计') + sections('audit-scope.md', '收尾的实际执行契约')
    if operation == 'retrospect':  # the closing retrospective abstracts observations; it audits nothing
        return sections('project-context.md', '跨运行经验沉淀与复用')
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
    """The execution rules of a role skill; the pointer, interface and asset boilerplate every skill repeats is not part of a
    card: a step names the templates it instantiates itself."""
    names = re.findall(r'(?m)^## (.*)$', (PACKAGE / path).read_text())
    keep = [n for n in names if n not in ('1. 定位', '4. 接口契约', '6. 配套资产')
            and (not n.startswith('7. Android/Harmony') or test_scope in ('automation', 'visual'))]
    return [(path, n) for n in keep]




PLANNING_OPERATIONS = ('register', 'global-plan', 'decompose', 'decompose-accept', 'module-summary', 'freeze', 'plan', 'change', 'redecompose', 'redecompose-accept', 'realloc-request', 'run-review', 'revise-run', 'plan-review', 'planning-reopen')  # the steps the status view calls planning

def _cells(line):
    return [c.strip().strip('`') for c in line.strip().strip('|').split('|')]


def _rows(block, keys):
    """The table header plus the rows whose first cell is one of `keys` (an `@a,b` selector)."""
    lines = block.splitlines(keepends=True)
    table = [i for i, line in enumerate(lines) if line.startswith('|')]
    keep = [lines[0]] + [lines[i] for i in table[:2]] + [lines[i] for i in table[2:] if _cells(lines[i])[0] in keys]
    return ''.join(keep)


# Blocks of an Agent definition that only apply in some modes of the role; other blocks always stay.
MODE_BLOCKS = {'### 设计', '### 构建', '### 单测与静态审查', '### 自动化', '## 10. 移动端执行器'}
# Build and automation are two stages of one executing Test-Runner, run one after the other: it is handed the role text
# of both once, so the second stage adds only the sections that stage needs.
EXECUTE_MODES = ('### 构建', '### 单测与静态审查', '### 自动化', '## 10. 移动端执行器')
TEST_MODES = {'build': EXECUTE_MODES, 'automation': EXECUTE_MODES, 'visual': EXECUTE_MODES}


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
def section(path, heading=None, modes=None):
    """Text of one Markdown section: from its heading to the next heading of the same or higher level.

    `heading@a,b` keeps only the table rows whose first cell is a or b; `modes` keeps an Agent's mode-specific blocks."""
    text = (PACKAGE / path).read_text()
    if heading is None:
        return _mode_blocks(text, set(modes)) if modes is not None else text
    name, _, keys = heading.partition('@')
    lines = text.splitlines(keepends=True)
    fenced, prose = False, []  # a `# comment` inside a code fence is not a heading
    for i, line in enumerate(lines):
        if line.startswith('```'):
            fenced = not fenced
        prose.append(not fenced)
    for i, line in enumerate(lines):
        match = re.match(r'(#+)\s+(.*?)\s*$', line) if prose[i] else None
        if match and match.group(2) == name:
            level = len(match.group(1))
            end = next((j for j in range(i + 1, len(lines))
                        if prose[j] and re.match(r'#{1,%d}\s' % level, lines[j])), len(lines))
            block = ''.join(lines[i:end])
            return _rows(block, set(keys.split(','))) if keys else block
    raise KeyError(f'{path}#{heading}')


@lru_cache(maxsize=None)
def matrix_keys():
    block = section(P + 'local-runtime.md', '操作矩阵')
    return {_cells(line)[0] for line in block.splitlines() if line.startswith('|')}


def execution_selection(m, step):
    """Accepted contracts take precedence over caller-supplied advisory selectors."""
    if not m or (step.get('worker_role') or step.get('role')) not in ('implementer', 'fixer', 'test-runner'): return None
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
    facts = dict.fromkeys(('ui', 'resources', 'pictures', 'copy', 'parameters', 'api', 'data', 'picture_items'), False)
    facts['visual'] = bool(((s.get('test_adapter') or {}).get('device') or {}).get('platforms'))  # a device to show a screen on
    try:
        import project_context
        stated = project_context.legacy_preview(s)
    except (ValueError, OSError, KeyError, TypeError):
        stated = None
    facts['legacy'] = bool(stated) and stated.get('kind') != 'none'  # the legacy runs: its screens are captured, not inferred
    try:
        import reference_media
        facts['media'] = bool(m) and bool(reference_media.of_module(s, m))  # the user showed screens of this leaf's cases
    except (ValueError, OSError, KeyError, TypeError):
        facts['media'] = False
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
        facts['data'] |= bool(analysis.get('data_inventory_ref')) and selection is None
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
                facts['data'] |= bool(item.get('data_ids'))
                model = item.get('semantic_model') or {}
                facts['picture_items'] |= bool(model.get('image_checks') or item.get('source_resource') or item.get('source_signal'))
                facts['pictures'] |= facts['picture_items']
        # Planners need discovery before choosing a resource strategy; executors consume only frozen facts.
        if step.get('role') in PLANNING_ROLES or step.get('worker_role') == 'spec-designer':
            facts['pictures'] |= facts['ui']
            facts['parameters'] |= facts['ui'] and bool((s.get('target_resources') or {}).get('parameters'))
            facts['copy'] |= facts['resources'] and bool((s.get('target_resources') or {}).get('copy'))
    for path in (s.get('global_paths', []) if m is None else (m.get('plan') or {}).get('paths', [])):
        selection = execution_selection(m, step)
        if selection is not None and path['path_id'] not in selection[1]: continue
        facts['ui'] |= path.get('kind') == 'visual' or bool(path.get('interaction_id'))
        facts['visual'] |= path.get('kind') == 'visual'
        facts['pictures'] |= bool(path.get('image_check_ids'))
    # What the UI-fidelity rules bind: a screen a device can show, a picture to carry, or a resource to copy. A UI dimension
    # in a run without a device, a visual path or a picture is coded from source and tested in-process: those rules do not apply.
    facts['fidelity'] = facts['visual'] or facts['resources'] or facts['picture_items']
    return facts


def reasoning_sections(m):
    """Extra methods activate on observed uncertainty/stagnation, not on role alone."""
    if not m: return []
    bad = [row for row in {**m.get('results', {}), **m.get('repair_findings', {})}.values() if row.get('quality') != 'green-passed']
    if m.get('no_progress_rounds', 0): return sections('progress-recovery.md', '1. 校验范围') + sections('domain-tools.md', '证据保留与修复闭环')
    if any((row.get('root_cause') or {}).get('confidence') != 'confirmed' for row in bad): return sections('semantic-extraction.md', '层与 schema')
    return []


def entries(role, test_scope=None, ui=False, reuse=False, operation=None, telemetry=False, lean=False, rows=(), facts=None, readiness=False):
    agent, skill = ROLE.get(role, [None, None])
    items = list(CORE) + [(agent, None)] + skill_sections(skill, test_scope) + STEP.get(role, [])
    if role in CONTROLLER_ROLES or operation == 'session':
        items += CONTROLLER
    if role in BOUNDARY_ROLES:
        items += BOUNDARY
    if role in WRITER_ROLES:
        items += WRITERS
    items += op_sections(role, operation)
    if operation == 'assign' and role == 'module-orchestrator':
        items += sections('runtime.md', '显式执行任务')
    if operation == 'session':
        items += sections('host-integration.md', '会话交接')
    if operation in ('freeze', 'plan') and role in CONTROLLER_ROLES:
        items += sections('state-machine.md', '控制主线')
    if operation in ('decompose', 'decompose-accept', 'global-plan'):
        items += sections('module-decomposition.md', '验证边界')
    selected = [k for k in (*rows, 'issue / issue-resolve') if k in matrix_keys()]  # any role may record a problem at any step
    if selected:
        items += sections('local-runtime.md', '操作矩阵@' + ','.join(selected))
    if role == 'test-runner':
        items += TEST_SCOPE.get(test_scope, [])
    if ui:
        chosen = UI.get(role, [])
        if facts is not None:
            chosen = [(path, heading) for path, heading in chosen
                      if not (path.endswith('ui-fidelity.md') and not facts.get('fidelity'))
                      and not (path.endswith('resource-transfer.md') and not facts.get('resources'))
                      and not (heading == COPY and not facts.get('copy'))
                      and not (heading in ('参数表', FILL) and not facts.get('parameters'))
                      and not (heading == PICTURES and not facts.get('pictures'))]
        items += chosen
        if facts and facts.get('legacy') and role in ('spec-designer', 'module-orchestrator'):
            items += sections('project-context.md', '存量预览') + sections('visual-execution.md', '4. 存量捕获')
        if facts and facts.get('visual') and role == 'spec-designer':
            items += sections('visual-execution.md', '1. 准备与冻结')  # the target is previewed: visual PATHs start from the written environment
    if facts and facts.get('media') and role in ('spec-designer', 'module-orchestrator'):
        items += sections('project-context.md', '用户参考媒体')
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
    if readiness:
        items += READINESS
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


EXECUTORS = ('implementer', 'fixer', 'test-runner', 'diagnostician')


def reuse_applies(s, m, role):
    """Planners always weigh reuse. An executor follows the reuse protocol only when the frozen plan it executes takes
    something from a provider: a plan whose every mapping is `new` leaves it nothing of that protocol to follow."""
    plan = (m or {}).get('plan') or {}
    required = bool(plan.get('reuse_plan_ref')) or bool(s.get('reuse_required'))
    if not required or role not in EXECUTORS or not plan.get('reuse_plan_ref') or not (m or {}).get('freeze_id'):
        return required
    from contracts import check_ref, read_json
    try:
        return any(row.get('decision') != 'new' for row in read_json(check_ref(plan['reuse_plan_ref'])).get('mappings') or [])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return True  # unreadable: keep the sections, the gates report the plan


def _chosen(s, m, step, topics):
    """The sections of a step: without `topics` the resident card (red lines, shared rules, the role, the step and its
    operation), with them everything the step's facts call for."""
    role = step.get('worker_role') or step.get('role')
    if role not in ROLE:
        return [], role
    operation = step.get('operation')
    facts = topic_facts(s, m, step)
    ui = topics and facts['ui'] and not (role == 'test-runner' and step.get('test_scope') == 'build')
    reuse, telemetry = topics and reuse_applies(s, m, role), topics and telemetry_scope(role, m)
    lean = bool(m) and bool(s.get('fixer_self_diagnosis'))
    # A coder's or a fixer's preflight is written by the Ledger at dispatch: its card carries nothing about reporting one.
    self_checked = bool(s.get('context_readiness_required')) and role in ('implementer', 'fixer') and bool(step.get('worker_role') or operation == 'await-result')
    rows = ([operation] if operation else []) + ((['submit'] if self_checked else ['context-submit', 'submit']) if step.get('worker_role') else [])
    chosen = entries(role, step.get('test_scope'), ui=ui, reuse=reuse, operation=operation, telemetry=telemetry, lean=lean and role in ('fixer', 'implementer'),
                     rows=rows, facts=facts if topics else None, readiness=bool(s.get('context_readiness_required')))
    chosen += reasoning_sections(m)
    if role == 'spec-designer':
        chosen += sections('testing.md', '编码前设计交接')
        # What the Ledger fills or enforces is not the author's to read up front: a refusal names its section.
        kept = LEDGER_KEPT if not (m or {}).get('change_request') else [row for row in LEDGER_KEPT if row[1] != '变更控制']
        chosen = [item for item in chosen if item not in kept]
    if (role == 'module-orchestrator' and (m or {}).get('change_request') and operation in ('plan-review', 'freeze')
            or role == 'auditor' and any(x.get('task_revalidation', {}).get('mode') == 'partial' for x in s.get('modules', {}).values())):
        chosen += sections('openspec.md', 'TASK 局部重验')
    if topics and (role == 'spec-designer' or role == 'test-runner' and step.get('test_scope') == 'automation'):
        chosen += platform_sections(s)
    if self_checked:
        chosen = [item for item in chosen if item != (P + 'context-readiness.md', '2. 精确插入节点')]
    if not topics and drafted_split(s, m, step):
        chosen = [item for item in chosen if item not in HAND_CUT]
    return list(dict.fromkeys(chosen)), role  # a section reaches a step once, whichever rule asked for it


def _card_rows(chosen, role, step):
    out = []
    for path, heading in chosen:
        modes = TEST_MODES.get(step.get('test_scope')) if path.startswith('Agents/') and role == 'test-runner' else None
        text = section(path, heading, modes)
        out.append({'ref': path, 'section': heading, 'bytes': len(text.encode()),
                    'sha256': hashlib.sha256(text.encode()).hexdigest(), **({'modes': list(modes)} if modes is not None else {})})
    return out


def card(s, m, step):
    """The resident text of a dispatch: red lines, shared rules, the role's definition and skill rules, the step's and the
    operation's sections. Topic rules are not here: `on_demand` lists them with their purpose."""
    chosen, role = _chosen(s, m, step, topics=False)
    return _card_rows(chosen, role, step)


# What calls for reading a topic section: the specific rows first, then the file as a whole.
PURPOSES = (
    (('testing.md', 'web Main'), '写 web PATH 时'), (('testing.md', 'Harmony Main'), '写 android / harmony PATH 时'),
    (('visual-execution.md', '1. 准备与冻结'), '写 visual PATH 的 visual_execution 时'), (('visual-execution.md', '4. 存量捕获'), '发 legacy-capture 请求时'),
    (('project-context.md', '存量预览'), '发 legacy-capture 请求时'), (('project-context.md', '用户参考媒体'), '引用用户截图 / 录屏时'),
    (('resource-transfer.md', 'API 与 URL 契约'), '写 api-inventory 与 API item 时'), (('resource-transfer.md', '动态参数与布局结构'), '写 parameter_fill 的 runtime / structural 时'),
    (('ui-fidelity.md', None), '写 UI item、资源策略与图片检查时'), (('resource-transfer.md', None), '写 Resource item、复制清单与参数表例外时'),
    (('domain-tools.md', None), '调用 analyze-ui / resource-plan / resource-sync 时'), (('reuse-dependencies.md', None), '写 reuse-plan 映射与复用接线时'),
    (('telemetry.md', None), '判定埋点适用性、写埋点契约时'),
)


def purpose(ref, heading):
    name = ref.split('/')[-1]
    return next((text for (file, h), text in PURPOSES if file == name and h in (None, heading)), '写到该专题的工件时')


def on_demand(s, m, step):
    """The topic sections a step's facts call for (UI, resources, reuse, telemetry, the Mains of the declared platforms, the
    legacy, the user's media): named on the card with their purpose and size, read with `reading.py show` when the role
    writes that part. A rejection about one of their gates points at the same section."""
    resident, role = _chosen(s, m, step, topics=False)
    full, _ = _chosen(s, m, step, topics=True)
    held = set(resident)
    return [{**row, 'purpose': purpose(row['ref'], row['section'])} for row in _card_rows([x for x in full if x not in held], role, step)]


def text_of(row):
    return section(row['ref'], row['section'], tuple(row['modes']) if 'modes' in row else None)


def changed(rows, held):
    """Of a card, by name: the sections a holder was never handed, and the ones it holds in another text."""
    held = held or {}
    return {'new': [key(row) for row in rows if key(row) not in held],
            'changed': [key(row) for row in rows if key(row) in held and not known(held, row)]}


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
                               'upstream-test-plan.json', 'change-impact.json']},
    'implementer': {'base': ['implementation.md', 'context-readiness.json']},
    'fixer': {'base': ['implementation.md', 'fix-note.json', 'change-request.md', 'context-readiness.json']},
    'diagnostician': {'base': ['diagnosis.md']},
    'escalation': {'base': ['escalation.md', 'human-decision.json']},
    'auditor': {'code-review': [],  # the Ledger writes both report skeletons at the step
                'audit': ['audit-closure-plan.json', 'audit-report.md', 'audit-review.json', 'test-result.json']},
    'test-runner': {'base': ['stage-result.json', 'test-result.json', 'context-readiness.json']},
}
# Module-orchestrator templates by operation; an operation outside the table only updates the module status.
MO_TEMPLATES = {'freeze': ['checklist.md', 'plan-review.json', 'change-impact.json', 'batch-envelope.json'], 'plan-review': ['plan-review.json'], 'planning-reopen': ['status.md'],
                'change': ['change-impact.json'], 'complete': ['checklist.md', 'status.md'],
                'decompose': ['module-decomposition.json', 'dimension-analysis.json', 'batch-envelope.json'],
                'module-summary': ['status.md'], 'suspend': ['implementation-gap.json', 'status.md'],
                'assign': ['execution-assignment.json'], 'accept': ['status.md'], 'diagnosis-accept': ['status.md']}
SCOPE_TEMPLATES = {'build': ['test-adapter.json'], 'automation': ['test-adapter.json', 'interaction-evidence.json'],
                   'visual': ['visual-test-path.json', 'visual-capture-execution.json', 'visual-test-adapter.json', 'visual-execution.json', 'visual-request.json']}
# What a declared platform adds: the shape of its PATHs for the planner, its adapter and environment for the executor.
PLATFORM_TEMPLATES = {'web': {'spec-designer': ['web-test-path.json'], 'test-runner': ['web-test-adapter.json']},
                      'device': {'spec-designer': ['harmony-test-path.json'], 'test-runner': ['harmony-test-adapter.json', 'harmony-config.json']}}
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
    import context_readiness
    self_reported = step.get('operation') in context_readiness.SELF_REPORTED  # the Ledger writes its preflight
    if step.get('operation') in ('run-review', 'revise-run'):
        return ['template/run-revision.json'] + ([] if self_reported else ['template/context-readiness.json'])
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
        if drafted_split(s, m, step):  # the draft is the split; the Ledger cuts each leaf's analysis
            names = ['module-decomposition.json']
        if (m or {}).get('change_request') and step.get('operation') in ('plan-review', 'freeze'):
            names.append('task-independence.json')
    if role == 'test-runner':
        names += SCOPE_TEMPLATES.get(step.get('test_scope'), [])
    if role == 'spec-designer' or role == 'test-runner' and step.get('test_scope') == 'automation':
        for key in platform_keys(s):
            names += PLATFORM_TEMPLATES[key].get(role, [])
    reuse = reuse_applies(s, m, role)
    facts = topic_facts(s, m, step)
    active = {'reuse': reuse, 'telemetry': telemetry_scope(role, m), 'ui': facts['ui'] and not (role == 'test-runner' and step.get('test_scope') == 'build'),
              'knowledge': bool(s.get('dependency_resolution_required')) or reuse}
    for trigger, by_role in TRIGGER_TEMPLATES.items():
        if active[trigger]:
            names += by_role.get(role, [])
    if role in PLANNING_ROLES:
        if facts['api']: names += ['api-inventory.json']
        if facts['data']: names += ['data-inventory.json']
        if facts['parameters']: names += ['parameter-binding.json']
    unwritten = set()
    if role == 'spec-designer' and (m or {}).get('dimension_analysis_ref'):
        # The leaf's analysis is registered: a refinement starts from that file, not from the template; the model template
        # is for a leaf that has a screen to give evidence for; the four documents start from spec_skeleton.py, and an
        # impact statement belongs to a change request.
        unwritten = {'dimension-analysis.json'} | (set() if active['ui'] else {'semantic-model.json'})
        if not (m or {}).get('plan'):
            unwritten |= {'proposal.md', 'spec.md', 'design.md', 'tasks.md'}
        if not (m or {}).get('change_request'):
            unwritten.add('change-impact.json')
    if s.get('context_readiness_required') and role in ('implementer', 'fixer') and (step.get('worker_role') or step.get('operation') == 'await-result'):
        unwritten.add('context-readiness.json')  # written by the Ledger at dispatch
    if self_reported:
        unwritten.add('context-readiness.json')
    if step.get('operation') == 'register':
        unwritten.add('global-plan.json')  # coverage is its own step, drafted by the Ledger from the registrations
    return ['template/' + n for n in dict.fromkeys(names) if n not in unwritten]


# A rejected request points at the section that states the failed gate; advisory, first match wins.
GATES = [
    (r'\bissues? |issue[_-]|blocking issue|gap the Ledger recorded|standing rule', 'local-runtime.md', '操作矩阵'),  # first: an issue's text may name any topic
    (r'build unit busy', 'build-automation.md', '总则'),
    (r'reference media|reference screenshot|the user showed|user-reference|target expectation', 'project-context.md', '用户参考媒体'),
    (r'legacy_preview|legacy runs on|capture_gap|legacy application', 'project-context.md', '存量预览'),
    (r'the plan settles (?!an API)', 'dimension-slicing.md', '4. 控制节点与交接'),
    (r'trace routes|invalid finding action', 'local-runtime.md', '操作矩阵'),
    (r'self-check output', 'build-automation.md', '构建资产位置'),
    (r'host handoff|cold recovery|rotation checkpoint|global hint|session restoration', 'host-integration.md', '会话交接'),
    (r'test asset', 'testing.md', '本地执行与严格结果验收'),
    (r'test PATH preparation|test preparation', 'testing.md', '编码前设计交接'),
    (r'condition review|condition refs', 'resource-transfer.md', '动态参数与布局结构'),
    (r'pinned to package', 'runtime.md', '总则'),
    (r'API |api_inventory|api_obligations', 'resource-transfer.md', 'API 与 URL 契约'),
    (r'\bdata (source|mapping|fidelity|inventory|entity|contract|target|exclusion|applicability|needs|items|behavior|adaptation|binding|tests|repository)|data_obligations|holds this data', 'resource-transfer.md', '数据契约'),
    (r'dimension (trace|task|path|paths|behavior|assertion)|dimension item IDs|SPEC must bind the allocated', 'dimension-slicing.md', '4. 控制节点与交接'),
    (r'superseded plan|pins only its own target files', 'module-decomposition.md', '验证边界'),
    (r'takes evidence from', 'module-decomposition.md', '切片标准'),
    (r'task scope (in|out):', 'dimension-slicing.md', '7. 任务级四维分析契约'),
    (r'review over \d+ KB', 'local-runtime.md', '操作矩阵'),
    (r'scaffold leaves|anchors on a UI surface|single layer|at (most|least) \d+ cases|at most \d+ tasks|plan over \d+ KB|unknown child kind|skeleton|sub-flow', 'module-decomposition.md', '切片标准'),
    (r'runtime expression|runtime/layout|layout keywords|structural mapping|parameter mapping', 'resource-transfer.md', '动态参数与布局结构'),
    (r'hash mismatch|absolute evidence path|missing file', 'runtime.md', '请求与事件'),   # first: the file named in the message may sit in a path of any other topic
    (r'unknown reference id', 'context-readiness.md', '3. 报告与传递'),
    (r'target_resources\S* is not settled|target_resources (takes|\.declined)|target_resources\.declined', 'resource-transfer.md', '总则'),
    (r'parameter[ _](sheet|fill|file|convention)|parameter_fill|recorded (value )?parameters?|values to parameter|a parameter is'
     r'|expressions the Spec|tokens the Spec|typed value|(not_applicable|settled|token) record|share one key|target_resources\.parameters'
     r'|\b(layout|layer|code|values):\S+: deviation', 'resource-transfer.md', FILL),
    (r'file resources|usage[ _]exclusion|layout_helpers', 'resource-transfer.md', '使用点与闭包'),
    (r'cop(y|ied) (plan|path|target|resources?)|copy_blocker|target_resources\.copy|resource-sync|one target file|index different files'
     r'|refusing to overwrite|target_resource (must|needs)|file of the target project|a consumer is a|planned consumer files|never names|not the legacy file|legacy (entry|vector)',
     'resource-transfer.md', COPY),
    (r'skeleton', 'openspec.md', '冻结算法'),
    (r'design |test.design|设计|user-visible case|device[ _]gaps?|test_adapter\.device', 'testing.md', '编码前设计交接'),
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
    (r'scratch|package rule file is not evidence', 'storage-layout.md', '总则'),
    (r'retirement|run impact|run revision|run review|root revision|root update|contract IDs|replacement IDs', 'progress-recovery.md', '同 Run 上游修订'),
    (r'code review|code findings|goal review|governance|recovery resolutions', 'audit-code-review.md', 'Ledger 接口'),
    (r'finding|repair owner|leftover|owner (not|must|prerequisites)|unresolved (human|verification)|block reason|retry contract', 'audit-scope.md', '问题处理'),
    (r'feature|boundary (review|issue|question|modules|kind)|functional list|test case summary', 'context-readiness.md', '功能清单来源与完备性'),
    (r'project (context|configuration|placeholders|id)|context snapshot|run context|override field|persistent default|build configuration'
     r'|configuration patch|context belongs|single-module requires', 'project-context.md', '运行时固化'),
    (r'context (stage|producer|checklist|verdict|check|understanding|blocked|blocker|test)|wrong context|build not ready|observed failure',
     'context-readiness.md', '3. 报告与传递'),
    (r'fidelity condition|condition_assertions', 'resource-transfer.md', '动态参数与布局结构'),
    (r'statechart|icu messages|strategy new has no legacy', 'semantic-extraction.md', '层与 schema'),
    (r'ui tree|ui_tree|UI node|UI evidence|ui_evidence|UI implementation|screen (must|needs)|runtime ?index|tree modes|native UI', 'ui-fidelity.md', 'UI 证据绑定'),
    (r'capture|baseline screenshot|frozen baseline|reference manifest|installation command', 'ui-fidelity.md', 'capture / 构建产物契约'),
    (r'platform api_level|values (target|entry)|value_xml_exact|loader_mapping|signal exclusion|manual implementation', 'ui-fidelity.md', '精确性纪律'),
    (r'decision boundary|human decision|approval missing', 'openspec.md', '冻结算法'),
    (r'context subject', 'context-readiness.md', '5. 缺失、失效与恢复'),
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
    (r'red evidence|self-check note|first run must fail|second run must pass|a batch (runs|carries)|a note of a PATH', 'testing.md', '逻辑单测'),
    (r'integration (Test-Runner|assignment|selection|task)|no global path is due', 'audit-scope.md', '收尾的实际执行契约'),
    (r'tests-revised|fact or debt', 'openspec.md', '变更控制'),
    (r'path|assertion|test_run|retest|receipt|quality|executed', 'testing.md', '断言与结果'),
    (r'task|TASK|SPEC|plan |six-piece|definition|closure|feasibility', 'openspec.md', '冻结算法'),
    (r'freeze|approv|decision', 'state-machine.md', 'Freeze / DoD 分开'),
    (r'audit', 'audit-scope.md', '总则'),
    (r'fix round|budget|no.progress|local fix', 'state-machine.md', '有限循环'),
    (r'source', 'source-changes.md', '总则'),
    (r'fencing|revision|request id|principal|role denied|stale', 'runtime.md', '请求与事件'),
    # the rows below name the section of what the generic rows above do not reach
    (r'reference_media|media_marks|media mark|media_refs|media evidence', 'project-context.md', '用户参考媒体'),
    (r'run root|\.sdd-runs|storage layout|storage belongs|project store|managed archive|archive context|archived artifact|context archive|context history|context link|registered at a different root|output outside selected run|runs/ directory|runs/harmony/', 'storage-layout.md', '启动与二次启动'),
    (r'events\.jsonl|committed Ledger events|run not initialized|not initialized or wrong run|run_id differs|^run mismatch|host context required|--run-id|argv/cwd required|command/operation mismatch', 'runtime.md', '请求与事件'),
    (r'context_inputs|context input kind', 'runtime.md', '渐进加载'),
    (r'stop/isolation|stop unconfirmed|executor aborted|stop/revoke|revoke worker|worker identity|Test-Runner identity|review identity|session id required|advance needs|mechanical preflight|merged dispatch|api-register|api_id|module (not|already) registered|unknown module|^no modules|selected module', 'local-runtime.md', '操作矩阵'),
    (r'no adapter runs platform', 'local-runtime.md', '实际测试适配器'),
    (r'test_adapter\.(adapters|harmony_reference)', 'project-context.md', '初始化和增量更新'),
    (r'build (argv|command|cwd|timeout|artifact)|build must pass|build report|invalid build timeout|absolute output directory', 'build-automation.md', '2. 构建命令的来源与固化'),
    (r'deferral|defer completed|may be deferred|deferred automation', 'build-automation.md', '4. 自动化环境缺失：直接记 Yellow 并继续'),
    (r'execution (evidence|observation|output|contract)|execution-state|completion (acceptance|query|interpretation)|host normalization|host execution', 'testing.md', '本地执行与严格结果验收'),
    (r'mobile|Harmony (classification|context|query|output)', 'testing.md', 'Harmony Main'),
    (r'web (PATH platform|PATH |report context|query|execution environment)', 'testing.md', 'web Main'),
    (r'review (every|must cover|owner/scope|context|code changed)|goal conclusion', 'audit-code-review.md', 'Ledger 接口'),
    (r'anti-pattern|production_symbols|production binding', 'testing.md', '静态规格闭合'),
    (r'CR and impact|before CR|DoD review|accepted diagnosis|planning reopen|planning rollback|route directly to Fixer|module blocker|module work before repair|repair not pending|release (a )?blocker|invalidation reason|invalid blocker|structured blocker', 'state-machine.md', '控制流闭环细则'),
    (r'modules (incomplete|not operationally)', 'state-machine.md', '模块隔离与全量收尾'),
    (r'project patch|invalid defaults|entry mode|invalid run id|architecture required|not a directory|legacy/target overlap|frozen architecture|run/config|prepared run requires|must be boolean|stall timeout|lock timeout|timezone|package_sha|adapter (args|timeout)|context document|attach context', 'project-context.md', '初始化和增量更新'),
    (r'model_routing|model tier|default_tier|override tier|low-cost model|strong-only|model id|policy selectors', 'model-routing.md', '总则'),
    (r'interaction', 'ui-fidelity.md', '视觉对齐 = automation 第二层（不是独立阶段）'),
    (r'COMPLETE (needs|snapshot)|generatedFrom|native (node|runtime)|runtime (observation|UI target)|vector drawable', 'ui-fidelity.md', 'UI 证据绑定'),
    (r'knowledge|Foundation|resolution|resolved requirements|not-required result', 'engineering-disciplines.md', '1. Foundation / 迁移知识执行与冻结'),
    (r'implementation gap|not-implemented|viable alternative|assess adaptation', 'reuse-dependencies.md', '8.2 核验后才能声明未实现'),
    (r'scaffold|target profile', 'module-decomposition.md', '切片标准'),
    (r'lesson|experience', 'project-context.md', '跨运行经验沉淀与复用'),
    (r'test_assets|deferred preparation|test context|test scope', 'testing.md', '编码前设计交接'),
    (r'red_evidence|failing run precedes', 'testing.md', '逻辑单测'),
    (r'hub identity|global inputs mismatch|host state identity', 'storage-layout.md', 'OpenSpec 投影完整性收尾门禁'),
    (r'unknown stream|--attempt|offset must|trace needs|preview needs', 'testing.md', '日志与按需追溯'),
    (r'boundary_review|global (requirement|case)|requirement ownership|owner mapping|removed requirement|retired contract|single-module', 'context-readiness.md', '功能清单来源与完备性'),
    (r'refined analysis|allocated scope|scope exclusions|fidelity_conditions|runtime mapping needs', 'dimension-slicing.md', '4. 控制节点与交接'),
    (r'code (outside|changed|not generated)|committed blob|acceptance (changed|evidence)|active submission', 'local-runtime.md', '阶段结果'),
    (r'repair (memory|route|module)|recovery resolution|affected modules|duplicate owner', 'audit-scope.md', '问题处理'),
    (r'realloc-request|revise existing roots', 'progress-recovery.md', '同 Run 上游修订'),
    (r'unresolved planning questions|human check', 'openspec.md', '冻结算法'),
    (r'decision_envelope|allowed_alternatives|forbidden_changes|envelope', 'openspec.md', '决策边界与执行基线'),
    (r'task dimension|task four-dimension|dimension_analysis', 'dimension-slicing.md', '7. 任务级四维分析契约'),
]


# The share of the Ledger's rejection messages that name the section stating their rule. A rejection is where a rule
# that is not on the card gets loaded; raise this when hints are added, never lower it.
HINT_COVERAGE = 0.90


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


def known(held, row):
    """Whether a holder has read this exact text of a section. It keeps every text of a section it was handed, so a
    section that differs by stage is not handed again when the stage comes round."""
    seen = (held or {}).get(key(row)) or []
    return any(row['sha256'].startswith(digest) for digest in ([seen] if isinstance(seen, str) else seen) if digest)


def fresh(rows, held):
    """The rows a session that already holds `held` still has to read. The red lines are on every card, new or not."""
    return [row for row in rows if row['ref'] == 'AGENTS.md' or not known(held, row)]


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
          '上文“（文件 § 小节）”即可直接作为参数。本步模板只列名：写该工件前 `reading.py show --template <名>` 取单份，不预读全部。\n')


def offered(path, lessons):
    """Which lessons this run handed a role, by the lesson each names: the harvest compares them with what happened."""
    try:
        seen = json.loads(path.read_text())
    except (OSError, ValueError):
        seen = {}
    fresh = {row['lesson_ref']['sha256']: {k: row[k] for k in ('kind', 'summary', 'lesson_ref') if k in row}
             for row in lessons if isinstance(row.get('lesson_ref'), dict) and row['lesson_ref'].get('sha256') not in seen}
    if fresh:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({**seen, **fresh}, ensure_ascii=False, indent=2, sort_keys=True))
        except OSError:
            pass  # a card is handed whether or not its record could be kept


def render(rows, output_dir, extra=(), skill=None, on_demand=(), lessons=()):
    """Write the card as one file named by its digest; a dispatch then hands the role a single path. A skill the step
    names travels in the same file, so loading the card loads it; the topic sections the step lists on demand are named
    with their purpose, not copied; the lessons it offers are listed by summary and reference, read when they apply."""
    body = ''.join(f'<!-- {row["ref"]}{"#" + row["section"] if row["section"] else ""} -->\n'
                   f'{unlink(text_of(row), row["ref"]).rstrip()}\n\n' for row in rows)
    if skill:
        from contracts import check_ref
        body += f'<!-- 技能 {skill["name"]} -->\n{check_ref(skill["ref"]).read_text().rstrip()}\n\n'
    if on_demand:
        body += ('<!-- 按需小节：写到对应工件时读，门禁照常，拒绝提示指向同一小节 -->\n'
                 + ''.join(f'- {row["purpose"]}：{row["ref"]} § {row["section"]}（{row["bytes"]} 字节）\n' for row in on_demand) + '\n')
    if lessons:
        body += ('<!-- 可参考的经验：核对适用范围后再读正文 -->\n'
                 + ''.join(f'- [{row["kind"]}] {row["summary"]}（适用：{row.get("applicability")}）：{row["lesson_ref"]["path"]}\n' for row in lessons) + '\n')
    if extra:
        body += '<!-- 本步模板 -->\n' + ''.join(f'- {name}\n' for name in extra) + '\n'
    body += FOOTER
    if lessons:
        offered(Path(output_dir).parent / 'lessons-offered.json', lessons)
    name = digest_card(rows)
    if skill or lessons:  # the same sections with another skill or other lessons are another card
        from contracts import digest
        name = digest([name, skill and skill['ref'], [row['lesson_ref'] for row in lessons]])
    target = Path(output_dir) / f'{name}.md'
    if not target.is_file() or target.read_text() != body:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + '.tmp')
        tmp.write_text(body)
        os.replace(tmp, target)
    return {'path': str(target), 'card_sha256': name, 'bytes': len(body.encode()), 'sections': len(rows)}


def show(ref, heading=None):
    """One section of one protocol file, for a role that needs a rule its card did not carry; above SECTION_BUDGET, the
    headings inside it to pick one from."""
    path = (PACKAGE / ref).resolve()
    if not path.is_relative_to(PACKAGE) or path.suffix != '.md' or not path.is_file():
        raise KeyError(f'not a package Markdown file: {ref}')
    text = section(str(path.relative_to(PACKAGE)), heading)
    if len(text.encode()) <= SECTION_BUDGET:
        return text
    headings = [line for line in text.splitlines()[1:] if re.match(r'#+\s', line)]
    return (f'{ref}#{heading or ""} is {len(text.encode())} bytes, above {SECTION_BUDGET}: read one section with --section\n'
            + '\n'.join(headings) + '\n')


def show_template(name):
    """One template, for the role about to write that artifact; a card names its step's templates and carries none."""
    folder = (PACKAGE / 'template').resolve()
    path = (folder / name).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise KeyError(f'not a package template: {name}')
    return path.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('render', help='write the current step card of one module (or the global step) as one file')
    r.add_argument('--root', required=True)
    r.add_argument('--resumed', action='store_true', help='the session already holds earlier cards: write only the new sections')
    target = r.add_mutually_exclusive_group(required=True)
    target.add_argument('--module')
    target.add_argument('--global', dest='is_global', action='store_true')
    sh = sub.add_parser('show', help='print one section of a package Markdown file, or one template by name')
    what = sh.add_mutually_exclusive_group(required=True)
    what.add_argument('--ref')
    what.add_argument('--template')
    sh.add_argument('--section')
    args = parser.parse_args()
    try:
        if args.command == 'show':
            sys.stdout.write(show_template(args.template) if args.template else show(args.ref, args.section))
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
        print(json.dumps(render(rows, Path(st['run_root']) / 'reports/reading', step.get('templates', ()),
                                None if args.resumed else step.get('slicing_skill'), step.get('read_when_writing', ()),
                                step.get('lesson_candidates', ())), ensure_ascii=False))
        return 0
    except (KeyError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
