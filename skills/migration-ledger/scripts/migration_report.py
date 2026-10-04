"""GO case-level report projected from Ledger facts; never changes acceptance."""
import copy
from collections import Counter
from html import escape

from contracts import check_ref, digest, read_json
import decomposition as dc
import test_validation as tv
import audit_code_review
import parameter_file
import resource_copy
import resource_fidelity
import ui_fidelity
import workflow_cost


def quality(values):
    return 'red-bug' if 'red-bug' in values else 'yellow-blocked' if not values or 'yellow-blocked' in values else 'green-passed'


def refs(value):
    """Collect actual artifact references, not prose claimed to be evidence."""
    found = {}
    def visit(v):
        if isinstance(v, dict):
            if v.get('path') and v.get('sha256'):
                found[(v['path'], v['sha256'])] = {'path': v['path'], 'sha256': v['sha256']}
            else:
                for item in v.values(): visit(item)
        elif isinstance(v, list):
            for item in v: visit(item)
    visit(value)
    return list(found.values())


def picture(mid, item, analysis_ref, carriers, rows):
    """How one picture in the target relates to its legacy source, and whether a measurement on the screen backs it."""
    state, check = resource_fidelity.exactness(item), item.get('image_check')
    paths = [r for r in rows if r['module_id'] == mid and r['path_id'] in carriers.get(check, [])]
    measured = bool(paths) and all(r['quality'] == 'green-passed' and r['executed'] and not r['stale'] for r in paths)
    deviation = item.get('deviation') or {}
    status, reason = {'exact': ('exact', '精确复制或语义等价迁移'),
                      'blocked': ('blocked', item.get('blocked_reason') or '该图片未迁移'),
                      'unrecorded': ('unknown', '未记录迁移策略'),
                      'manual': ('reviewed', '仅有人工评审，未经屏幕测量'),
                      'approved-deviation': ('approved-deviation', f"人工批准的偏差（{deviation.get('kind')}）：{deviation.get('reason')}")
                      }.get(state, ('', ''))
    if state == 'non-exact':
        status, reason = (('verified', '目标屏幕上的节点图像已与存量资源的渲染参考比对，在容差内一致') if measured else
                          ('not-verified', '图像检查所在视觉路径未在当前基线通过' if check else '手工替换的图片没有图像检查，也没有获批偏差'))
    return {'module_id': mid, 'item_id': item.get('item_id'), 'source': item.get('source_resource') or item.get('source_signal'),
            'resource_kind': item.get('resource_kind'), 'strategy': item.get('resource_strategy'), 'state': state, 'status': status,
            'reason': reason, 'image_check': check, 'path_ids': [r['path_id'] for r in paths],
            'evidence_refs': refs([analysis_ref, item.get('adaptation_evidence_ref'), deviation.get('evidence_refs'), [r['evidence_refs'] for r in paths]])}


def fidelity(s, rows, ref_check):
    """Disclose proof boundaries without changing business acceptance or scheduling."""
    visual, limitations, pictures, copied, parameters, checks = [], [], [], 0, {}, {}
    for mid, module in s['modules'].items():
        plan = module.get('plan') or {}
        analysis_ref = plan.get('dimension_analysis_ref')
        try:
            analysis = read_json(ref_check(analysis_ref))
            dimensions = analysis['dimensions']
            ui = next(d for d in dimensions if d['dimension'] == 'UI')
        except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
            visual.append({'module_id': mid, 'status': 'unknown', 'reason': '当前四维分析不可核验：' + str(exc),
                           'evidence_refs': refs(analysis_ref)})
            continue
        if ui.get('status') == 'not-applicable':
            visual.append({'module_id': mid, 'status': 'not-applicable',
                           'reason': ui.get('reason', '当前范围显式声明无 UI'), 'evidence_refs': refs(analysis_ref)})
        else:
            for item in ui.get('items', []) or [{}]:
                evidence = (item.get('semantic_model') or {}).get('ui_evidence') or {}
                coverage = evidence.get('coverage')
                paths = [r for r in rows if r['module_id'] == mid and r['kind'] == 'visual'
                         and coverage and r.get('coverage') == coverage]
                verified = (evidence.get('visual_mode') == 'runtime' and bool(paths) and
                            all(r['quality'] == 'green-passed' and r['executed'] and not r['stale'] for r in paths))
                status = 'verified' if verified else 'not-verified' if evidence else 'unknown'
                reason = ('声明的视觉路径已在当前基线通过' if verified else
                          '仅有 source-only 源码分析，未验证运行时视觉保真' if evidence.get('visual_mode') == 'source-only' else
                          '缺少当前基线已执行并通过的视觉路径' if evidence else '未声明可核验的 UI 证据模式')
                entry = {'module_id': mid, 'item_id': item.get('item_id'), 'coverage': coverage,
                         'visual_mode': evidence.get('visual_mode'), 'status': status, 'reason': reason,
                         'path_ids': [r['path_id'] for r in paths],
                         'evidence_refs': refs([analysis_ref, evidence, [r['evidence_refs'] for r in paths]])}
                visual.append(entry)
        carriers = {}
        for path in plan.get('paths', []):
            for cid in path.get('image_check_ids', []) if path.get('kind') == 'visual' else []:
                carriers.setdefault(cid, []).append(path['path_id'])
        try:
            copied += len(resource_copy.rows(analysis, ref_check))
            filled = parameter_file.summary(analysis, ref_check)
            if filled:
                parameters[mid] = filled
            counts = Counter()
            for item in ui.get('items', []) if ui.get('status') == 'applicable' else []:
                model = item.get('semantic_model') or {}
                evidence = model.get('ui_evidence') or {}
                if evidence.get('source_index_ref') and evidence.get('ui_tree_ref'):
                    covered = ui_fidelity.check_coverage(model, read_json(ref_check(evidence['ui_tree_ref'])), read_json(ref_check(evidence['source_index_ref'])))
                    counts.update({name: len(covered[name]) for name in ('uses', 'checked', 'waived')})
            if counts['uses']:
                checks[mid] = dict(counts)
        except (ValueError, OSError, KeyError, TypeError):
            pass  # the closure gate reports an unreadable plan; the report only counts what it can read
        for dimension in dimensions:
            for item in dimension.get('items', []):
                if dimension['dimension'] == 'Resource' and dimension.get('status') == 'applicable' and resource_fidelity.is_picture(item):
                    pictures.append(picture(mid, item, analysis_ref, carriers, rows))
                if item.get('target_strategy') == 'capture-fixture':
                    limitations.append({'module_id': mid, 'item_id': item.get('item_id'),
                        'kind': 'capture-fixture', 'case_ids': item.get('case_ids', []),
                        'reason': 'capture-fixture 只验证记录样本；未证明在线服务或 provider 行为等价',
                        'evidence_refs': refs([analysis_ref, item])})
    limitations[:0] = [{**v, 'kind': 'visual-coverage'} for v in visual if v['status'] in ('unknown', 'not-verified')]
    limitations += [{'module_id': v['module_id'], 'item_id': v['item_id'], 'kind': 'picture-replacement',
                     'reason': f"图片 {v['source']} 与存量不是精确复制（{v['status']}）：{v['reason']}", 'evidence_refs': v['evidence_refs']}
                    for v in pictures if v['status'] not in ('exact', 'verified', 'reviewed')]
    return visual, limitations, {'counts': dict(Counter(v['status'] for v in pictures)), 'copied': copied, 'parameters': parameters, 'checks': checks,
                                 'items': [v for v in pictures if v['status'] != 'exact']}


def build(root, s, sequence, ref_check=check_ref):
    rows = []
    gaps = [{'module_id': mid, 'label': '未实现', 'review': copy.deepcopy(m['blocked']['implementation_gap']),
             'review_ref': m['blocked']['implementation_gap_ref'], 'owner': m['blocked']['owner'],
             'next_action': m['blocked']['next_action']}
            for mid, m in s['modules'].items() if (m.get('blocked') or {}).get('implementation_gap')
            and m['blocked'].get('implementation_gap_ref')]
    names = dc.parent_mo_names(s)
    snapshot = {mid: m.get('code_baseline') for mid, m in s['modules'].items()}
    code_refs = [r for m in s['modules'].values() for r in m.get('code_files', [])]
    global_baseline = digest(sorted(code_refs, key=lambda r: r['path'])) if code_refs else None
    invalid = any(m.get('stale') or m.get('effective_quality') == 'yellow-blocked' for m in s['modules'].values())

    def row(mid, cid, path=None, m=None):
        pid = path.get('path_id') if path else None
        record = (m.get('results', {}) if m else s.get('audit_results', {})).get(pid, {})
        audit_row = next((r for r in s.get('audit', {}).get('paths', []) if r['path_id'] == pid), None)
        audited = bool(audit_row and s['audit'].get('snapshot') == snapshot)
        if audited: record = {**record, **audit_row}
        last_execution = copy.deepcopy(record.get('last_execution'))
        current_baseline = m.get('code_baseline') if m else global_baseline
        execution_scope_stale = invalid if not m else m.get('stale') or m.get('effective_quality') == 'yellow-blocked'
        last_execution_stale = bool(last_execution and
            (execution_scope_stale or last_execution.get('code_baseline') != current_baseline))
        stale = (m.get('stale') or m.get('effective_quality') == 'yellow-blocked' or
                 record.get('code_baseline', m.get('code_baseline')) != m.get('code_baseline')) if m else (
                 invalid or record.get('code_baseline') != global_baseline)
        # Environment omissions have no executed baseline to expire.
        stale = bool(stale and record.get('executed'))
        q = record.get('quality', 'yellow-blocked')
        if stale and q == 'green-passed': q = 'yellow-blocked'
        causes = [copy.deepcopy(record['root_cause'])] if q != 'green-passed' and record.get('root_cause') else []
        if not record or stale:
            category = 'evidence-stale' if record and stale else 'not-executed' if path else 'path-not-defined'
            causes.append({'category': category, 'summary': '结果基线已失效，须复核' if category == 'evidence-stale' else
                           '尚无已接受的测试结果' if path else '尚无此用例的冻结测试路径',
                           'owner': mid, 'next_action': 'retest-current-baseline' if record else 'continue-module-work'})
        blocker = (m or {}).get('blocked')
        gap = (blocker or {}).get('implementation_gap', {})
        not_implemented = cid in gap.get('case_ids', [])
        if q != 'green-passed' and blocker:
            causes.append({'category': 'not-implemented' if not_implemented else blocker.get('kind', 'blocked'), 'summary': blocker.get('reason', '模块受阻'),
                           'owner': blocker.get('owner', mid), 'next_action': blocker.get('next_action', 'resolve-blocker')})
        if q != 'green-passed' and not causes:
            causes.append({'category': 'cause-not-recorded', 'summary': 'Ledger 未记录根因，须补充诊断证据',
                           'owner': mid, 'next_action': 'diagnose'})
        related = [record, (m or {}).get('blocked'), (m or {}).get('diagnosis')]
        for sub in (m or {}).get('submissions', {}).values():
            if record.get('test_run_id') and record['test_run_id'] in sub.get('test_run_ids', []):
                related.append(sub['ref'])
        if not m or audited: related.append(s.get('audit', {}).get('report_ref'))
        rows.append({'case_id': cid, 'module_id': mid, 'parent_mo_name': names.get((m or {}).get('parent_module_id')) or names.get(mid),
                     'path_id': pid, 'name': (path or {}).get('name', pid or cid), 'kind': (path or {}).get('kind', 'test'),
                     'coverage': (path or {}).get('coverage'),
                     'quality': q, 'recorded_quality': record.get('quality'),
                     'executed': bool(record.get('executed') or (last_execution or {}).get('executed')),
                     'attempt_executed': record.get('executed', False),
                     'last_execution': last_execution, 'last_execution_stale': last_execution_stale,
                     'implementation_status': 'not-implemented' if not_implemented else None,
                     'stale': bool(record and stale), 'test_run_id': record.get('test_run_id'), 'retest_of': record.get('retest_of'),
                     'code_baseline': record.get('code_baseline', (m or {}).get('code_baseline')),
                     'assertions': copy.deepcopy(record.get('assertions', [])), 'root_causes': causes,
                     'evidence_refs': refs(related), 'spec_ref': m.get('plan_ref') if m else s.get('global_spec'),
                     'ledger_evidence': {'path': str(root / 'ledger/events.jsonl'), 'sequence': sequence,
                                         'module_id': mid, 'path_id': pid, 'case_id': cid}})

    for mid, m in s['modules'].items():
        paths = (m.get('plan') or {}).get('paths', [])
        for p in paths: row(mid, p['case_id'], p, m)
        for cid in m['case_ids']:
            if not any(p['case_id'] == cid and p.get('kind') != 'build' for p in paths): row(mid, cid, m=m)
    for p in s.get('global_paths', []): row('GLOBAL', p['case_id'], p)
    for cid in s['case_ids']:
        if not any(r['case_id'] == cid for r in rows): row('UNASSIGNED', cid)
    cases = []
    for cid in s['case_ids']:
        case_rows = [r for r in rows if r['case_id'] == cid]
        cases.append({'case_id': cid, 'quality': quality([r['quality'] for r in case_rows]),
                      'module_ids': sorted({r['module_id'] for r in case_rows}),
                      'path_count': sum(r['path_id'] is not None for r in case_rows),
                      'executed_count': sum(bool(r['executed']) for r in case_rows),
                      'unresolved': [r for r in case_rows if r['quality'] != 'green-passed']})
    batch = s.get('audit_batch', {})
    settled = (bool(s['modules']) and all(tv.available(m) for m in s['modules'].values()) and
               not any(not a.get('closed') for m in s['modules'].values() for a in m['assignments'].values()) and
               all(dc.summary_current(s, g, ref_check) for g in s.get('module_groups', {}).values()))
    governance = {'report_ref': s.get('audit_code_review', {}).get('report_ref'),
                  'change_inventory_ref': s.get('audit_code_review', {}).get('change_inventory_ref'),
                  'current': audit_code_review.current(s, ref_check), 'pending_findings': list(audit_code_review.pending(s).values()),
                  'verification_deferral_history': audit_code_review.deferred(s),
                  'history_refs': [r['report_ref'] for r in s.get('audit_code_review_history', [])]}
    reviewed = governance['current'] and not governance['pending_findings']
    stage = ('completed' if settled and reviewed and not invalid and s.get('quality') == 'green-passed' and
             all(c['quality'] == 'green-passed' for c in cases) else
             'completed-with-unverified-tests' if settled and reviewed and not invalid and tv.final_deferred_current(s) else
             'awaiting-human' if batch.get('status') == 'awaiting-human' else 'in-progress')
    visual, limitations, pictures = fidelity(s, rows, ref_check)
    return {'schema_version': 1, 'run_id': s['run_id'], 'sequence': sequence, 'report_stage': stage,
            'quality': quality([s.get('quality', 'yellow-blocked'), *[c['quality'] for c in cases]]),
            'entry_mode': s.get('entry_mode', 'project'), 'single_module_id': s.get('single_module_id'),
            'legacy_root': s['legacy_root'], 'target_root': s['target_root'],
            'parent_mo_names': names, 'snapshot': snapshot, 'audit': copy.deepcopy(s.get('audit', {})),
            'case_counts': {q: Counter(c['quality'] for c in cases)[q] for q in ('green-passed', 'red-bug', 'yellow-blocked')},
            'cases': cases, 'paths': rows, 'non_green': [r for r in rows if r['quality'] != 'green-passed'],
            'unimplemented': gaps, 'code_governance': governance,
            'visual_coverage': visual, 'fidelity_limitations': limitations, 'picture_fidelity': pictures,
            'human_report': copy.deepcopy(batch.get('human_report')),
            'workflow_cost': workflow_cost.build(s, workflow_cost.journal(root)),
            'modules': {mid: {'phase': m.get('phase'), 'quality': m.get('effective_quality', m.get('quality')),
                              'parent_module_id': m.get('parent_module_id'), 'dependencies': m.get('dependencies', [])}
                        for mid, m in s.get('modules', {}).items()},
            'module_groups': {mid: {'children': grp.get('children', []), 'agent_name': names.get(mid, f'parent-mo-{mid}')}
                              for mid, grp in s.get('module_groups', {}).items()},
            'human_report_path': str(root / 'audit-reports' / (batch['batch_id'] + '.json')) if batch.get('human_report') else None}


def mermaid_diagram(report):
    groups = report.get('module_groups', {})
    modules = report.get('modules', {})
    if not modules and not groups:
        return ''
    lines = ['```mermaid', 'graph TD']
    for pid, grp in sorted(groups.items()):
        name = grp.get('agent_name', f'parent-mo-{pid}')
        lines.append(f'  subgraph {pid} ["{name}"]')
        for cid in sorted(grp.get('children', [])):
            m = modules.get(cid, {})
            q = m.get('quality', 'unknown')
            phase = m.get('phase', 'pending')
            lines.append(f'    {cid}["{cid} ({phase})<br/>{q}"]')
        lines.append('  end')
    for mid, m in sorted(modules.items()):
        if not m.get('parent_module_id') and mid not in [c for g in groups.values() for c in g.get('children', [])]:
            q = m.get('quality', 'unknown')
            phase = m.get('phase', 'pending')
            lines.append(f'  {mid}["{mid} ({phase})<br/>{q}"]')
    for mid, m in sorted(modules.items()):
        for dep in sorted(m.get('dependencies', [])):
            lines.append(f'  {dep} --> {mid}')
    lines.append('```')
    return '\n'.join(lines)


def render(report):
    def cell(value):
        return escape(str(value if value is not None else '—')).replace('|', '&#124;').replace('\n', '<br>')
    text = [f"# GO 迁移报告：{cell(report['run_id'])}", '',
            f"Ledger sequence: {report['sequence']} · 阶段: {report['report_stage']} · 全局状态: {report['quality']}", '',
            f"范围: {cell(report['entry_mode'])} / {cell(report['single_module_id'])} · CASE 统计: {cell(report['case_counts'])}", '',
            f"存量: {cell(report['legacy_root'])} · 目标: {cell(report['target_root'])}", '',
            '用例状态来自已接受的 PATH 证据；build Green 不等于自动化通过。executed 表示曾执行，attempt_executed 表示本次尝试实际执行；last_execution 单独保留此前真实断言及回执，不能代替本次复核。stale 表示当前结果失效，last_execution_stale 标记保留执行是否失效。', '',
            '## 父 MO', '', *[f'- {mid}: {name}' for mid, name in report['parent_mo_names'].items()], '']
    diagram = mermaid_diagram(report)
    if diagram:
        text += ['## 模块架构与依赖拓扑', '', diagram, '']
    text += ['## 全部测试用例', '', '| CASE-ID | 模块 | 状态 | 路径数 | 曾执行数 |', '| --- | --- | --- | --- | --- |']
    for c in report['cases']:
        text.append('| ' + ' | '.join(cell(v) for v in (c['case_id'], ', '.join(c['module_ids']), c['quality'], c['path_count'], c['executed_count'])) + ' |')
    text += ['', '## 视觉覆盖与保真限制', '',
             '以下为证据覆盖披露，独立于业务 CASE 三态；completed 不代表未测维度已经验证。', '',
             '| 模块 / 项 | 覆盖 | 视觉模式 | 验证状态 | 原因 |', '| --- | --- | --- | --- | --- |']
    for v in report.get('visual_coverage', []):
        text.append('| ' + ' | '.join(cell(x) for x in (f"{v['module_id']} / {v.get('item_id', '—')}",
                    v.get('coverage'), v.get('visual_mode'), v['status'], v['reason'])) + ' |')
    for limit in report.get('fidelity_limitations', []):
        text.append(f"- {cell(limit['module_id'])} / {cell(limit.get('item_id'))}: {cell(limit['reason'])}")
        for ref in limit['evidence_refs']:
            text.append(f"  - 证据：[{cell(ref['path'])}](<{ref['path']}>) · sha256={ref['sha256']}")
    pictures = report.get('picture_fidelity') or {'counts': {}, 'items': []}
    if pictures.get('copied'):
        text += ['', f"按路径复制到目标的文件资源：{pictures['copied']} 个（验收时逐个与存量文件比对）。"]
    for mid, row in sorted((pictures.get('checks') or {}).items()):
        text += ['', f"{cell(mid)}：节点显示的图片 {row['uses']} 处，其中 {row['checked']} 处有图像检查，{row['waived']} 处经豁免。"]
    if pictures.get('parameters'):
        text += ['', '参数填充（组件与图层的取值由参数表生成到目标，按键取用；结构性关键字不计入）：', '',
                 '| 模块 | 组件 / 图层 | 参数 | 按记录取用 | 不适用 | 获批偏差 | 填充率 |', '| --- | --- | --- | --- | --- | --- | --- |']
        for mid, row in sorted(pictures['parameters'].items()):
            c = row['counts']
            text.append(f"| {cell(mid)} | {row['components']} / {row['layers']} | {row['parameters']} | {c.get('used', 0) + c.get('mapped', 0)} | "
                        f"{c.get('not-applicable', 0)} | {c.get('deviation', 0)} | {cell(row['fill_rate'])} |")
    if pictures['items']:
        text += ['', '以下图片不是对存量资源的精确复制；verified 表示目标屏幕上的节点图像已在容差内与存量渲染参考一致。', '',
                 f"图片统计：{cell(pictures['counts'])}", '', '| 模块 / 项 | 来源 | 类型 / 策略 | 状态 | 说明 |', '| --- | --- | --- | --- | --- |']
        for v in pictures['items']:
            text.append('| ' + ' | '.join(cell(x) for x in (f"{v['module_id']} / {v.get('item_id', '—')}", v['source'],
                        f"{v['resource_kind']} / {v['strategy']}", v['status'], v['reason'])) + ' |')
    governance = report.get('code_governance', {})
    text += ['', '## 整体代码治理', '', f"当前基线审查有效：{governance.get('current', False)}；待处理治理发现：{len(governance.get('pending_findings', []))}"]
    if governance.get('report_ref'):
        ref = governance['report_ref']
        text.append(f"- 审查证据：[{cell(ref['path'])}](<{ref['path']}>) · sha256={ref['sha256']}")
    if governance.get('change_inventory_ref'):
        ref = governance['change_inventory_ref']
        text.append(f"- 本次代码修改清单：[{cell(ref['path'])}](<{ref['path']}>) · sha256={ref['sha256']}")
    for finding in governance.get('pending_findings', []):
        cause, ref = finding['root_cause'], finding['analysis_ref']
        text.append(f"- {cell(finding['finding_id'])} / {cell(finding['category'])}：{cell(cause['summary'])}；owner={cell(cause['owner'])}；next={cell(cause['next_action'])}；证据：[{cell(ref['path'])}](<{ref['path']}>)")
    if report.get('unimplemented'):
        text += ['', '## 未实现：需要人工决策', '']
        for gap in report['unimplemented']:
            review, ref = gap['review'], gap['review_ref']
            text += [f"- {cell(gap['module_id'])} · REQ={cell(review['requirement_ids'])} · CASE={cell(review['case_ids'])} · TASK={cell(review['task_ids'])}：{cell(review['goal'])}",
                     f"  - 核验：{cell(review['verification']['summary'])}；owner={cell(gap['owner'])}；next={cell(gap['next_action'])}",
                     f"  - 证据：[{cell(ref['path'])}](<{ref['path']}>) · sha256={ref['sha256']}"]
    cost = report.get('workflow_cost') or {'modules': {}, 'totals': {}}
    text += ['', '## 流程成本', '', f"合计：{cell(cost['totals'])}", '',
             '| 模块 | 事件 | 派发 | 上下文回执 | 验收 | 人工决定 | 修复轮次 | 轻量叶子 | 阅读卡字节（完整/实际交付） |', '| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
             *[f"| {cell(mid)} | {r['events']} | {r['dispatches']} | {r['context_receipts']} | {r['acceptances']} | "
               f"{r['human_decisions']} | {r['fix_rounds']} | {'是' if r['lean_leaf'] else '否'} | {r['card_bytes_full']} / {r['card_bytes_delivered']} |" for mid, r in cost['modules'].items()]]
    text += ['', '## 路径明细', '', '| CASE-ID | 模块 / 父 MO | PATH / Name | 类型 | 状态 | 曾执行 / 本次执行 / stale | test_run |', '| --- | --- | --- | --- | --- | --- | --- |']
    for r in report['paths']:
        text.append('| ' + ' | '.join(cell(v) for v in (r['case_id'], f"{r['module_id']} / {r['parent_mo_name'] or '—'}", f"{r['path_id'] or '—'} / {r['name']}",
                    r['kind'], r['quality'], f"{r['executed']} / {r['attempt_executed']} / {r['stale']}", r['test_run_id'])) + ' |')
    text += ['', '## 非 Green 原因与证据', '']
    if not report['non_green']: text.append('无非 Green 用例；是否完成迁移仍以报告阶段、DoD 和 Auditor 裁决为准。')
    for r in report['non_green']:
        text += [f"### {cell(r['case_id'])} / {cell(r['module_id'])} / {cell(r['path_id'])}", '']
        for cause in r['root_causes']:
            text.append(f"- {cell(cause.get('category'))}: {cell(cause.get('summary'))}；confidence={cell(cause.get('confidence', '未标注'))}；owner={cell(cause.get('owner'))}；next={cell(cause.get('next_action'))}")
        if r['last_execution']:
            previous = r['last_execution']
            text.append(f"- 最近真实执行：{cell(previous['test_run_id'])}；原状态={cell(previous['quality'])}；断言={cell(previous.get('assertions', []))}；证据失效={r['last_execution_stale']}。本次尝试未执行，旧观测不构成本次通过。")
        for ref in r['evidence_refs']:
            text.append(f"- 证据：[{cell(ref['path'])}](<{ref['path']}>) · sha256={ref['sha256']}")
        ev = r['ledger_evidence']
        text += [f"- Ledger 状态依据：[events.jsonl](<{ev['path']}>) · sequence={ev['sequence']} · module={cell(r['module_id'])} · PATH={cell(r['path_id'])}", '']
    if report['human_report']:
        text += ['## 人工待决', '', f"原因：{cell(report['human_report'].get('reason'))}",
                 f"完整根因与证据：[审计人工报告](<{report['human_report_path']}>)", '']
    text += ['本报告为 Ledger 可重建投影；不生成新验收，不触发全量复测。未执行/证据缺失保持 Yellow，原因不明明确待诊断。', '']
    return '\n'.join(text)
