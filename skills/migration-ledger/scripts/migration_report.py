"""GO case-level report projected from Ledger facts; never changes acceptance."""
import copy
from collections import Counter
from html import escape

from contracts import digest
import decomposition as dc
import test_validation as tv


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


def build(root, s, sequence):
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
            if record.get('test_run_id') and any(r.get('test_run_id') == record['test_run_id'] for r in sub['result'].get('paths', [])):
                related.append(sub['ref'])
        if not m or audited: related.append(s.get('audit', {}).get('report_ref'))
        rows.append({'case_id': cid, 'module_id': mid, 'parent_mo_name': names.get((m or {}).get('parent_module_id')) or names.get(mid),
                     'path_id': pid, 'name': (path or {}).get('name', pid or cid), 'kind': (path or {}).get('kind', 'test'),
                     'quality': q, 'recorded_quality': record.get('quality'), 'executed': record.get('executed', False),
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
               all(dc.summary_current(s, g) for g in s.get('module_groups', {}).values()))
    stage = ('completed' if settled and not invalid and s.get('quality') == 'green-passed' and
             all(c['quality'] == 'green-passed' for c in cases) else
             'completed-with-unverified-tests' if settled and not invalid and tv.final_deferred_current(s) else
             'awaiting-human' if batch.get('status') == 'awaiting-human' else 'in-progress')
    return {'schema_version': 1, 'run_id': s['run_id'], 'sequence': sequence, 'report_stage': stage,
            'quality': quality([s.get('quality', 'yellow-blocked'), *[c['quality'] for c in cases]]),
            'entry_mode': s.get('entry_mode', 'project'), 'single_module_id': s.get('single_module_id'),
            'legacy_root': s['legacy_root'], 'target_root': s['target_root'],
            'parent_mo_names': names, 'snapshot': snapshot, 'audit': copy.deepcopy(s.get('audit', {})),
            'case_counts': {q: Counter(c['quality'] for c in cases)[q] for q in ('green-passed', 'red-bug', 'yellow-blocked')},
            'cases': cases, 'paths': rows, 'non_green': [r for r in rows if r['quality'] != 'green-passed'],
            'unimplemented': gaps,
            'human_report': copy.deepcopy(batch.get('human_report')),
            'human_report_path': str(root / 'audit-reports' / (batch['batch_id'] + '.json')) if batch.get('human_report') else None}


def render(report):
    def cell(value):
        return escape(str(value if value is not None else '—')).replace('|', '&#124;').replace('\n', '<br>')
    text = [f"# GO 迁移报告：{cell(report['run_id'])}", '',
            f"Ledger sequence: {report['sequence']} · 阶段: {report['report_stage']} · 全局状态: {report['quality']}", '',
            f"范围: {cell(report['entry_mode'])} / {cell(report['single_module_id'])} · CASE 统计: {cell(report['case_counts'])}", '',
            f"存量: {cell(report['legacy_root'])} · 目标: {cell(report['target_root'])}", '',
            '用例状态来自已接受的 PATH 证据；build Green 不等于自动化通过。executed 表示曾执行，stale 表示证据已失效。', '',
            '## 父 MO', '', *[f'- {mid}: {name}' for mid, name in report['parent_mo_names'].items()], '',
            '## 全部测试用例', '', '| CASE-ID | 模块 | 状态 | 路径数 | 曾执行数 |', '| --- | --- | --- | --- | --- |']
    for c in report['cases']:
        text.append('| ' + ' | '.join(cell(v) for v in (c['case_id'], ', '.join(c['module_ids']), c['quality'], c['path_count'], c['executed_count'])) + ' |')
    if report.get('unimplemented'):
        text += ['', '## 未实现：需要人工决策', '']
        for gap in report['unimplemented']:
            review, ref = gap['review'], gap['review_ref']
            text += [f"- {cell(gap['module_id'])} · REQ={cell(review['requirement_ids'])} · CASE={cell(review['case_ids'])} · TASK={cell(review['task_ids'])}：{cell(review['goal'])}",
                     f"  - 核验：{cell(review['verification']['summary'])}；owner={cell(gap['owner'])}；next={cell(gap['next_action'])}",
                     f"  - 证据：[{cell(ref['path'])}](<{ref['path']}>) · sha256={ref['sha256']}"]
    text += ['', '## 路径明细', '', '| CASE-ID | 模块 / 父 MO | PATH / Name | 类型 | 状态 | executed / stale | test_run |', '| --- | --- | --- | --- | --- | --- | --- |']
    for r in report['paths']:
        text.append('| ' + ' | '.join(cell(v) for v in (r['case_id'], f"{r['module_id']} / {r['parent_mo_name'] or '—'}", f"{r['path_id'] or '—'} / {r['name']}",
                    r['kind'], r['quality'], f"{r['executed']} / {r['stale']}", r['test_run_id'])) + ' |')
    text += ['', '## 非 Green 原因与证据', '']
    if not report['non_green']: text.append('无非 Green 用例；是否完成迁移仍以报告阶段、DoD 和 Auditor 裁决为准。')
    for r in report['non_green']:
        text += [f"### {cell(r['case_id'])} / {cell(r['module_id'])} / {cell(r['path_id'])}", '']
        for cause in r['root_causes']:
            text.append(f"- {cell(cause.get('category'))}: {cell(cause.get('summary'))}；confidence={cell(cause.get('confidence', '未标注'))}；owner={cell(cause.get('owner'))}；next={cell(cause.get('next_action'))}")
        for ref in r['evidence_refs']:
            text.append(f"- 证据：[{cell(ref['path'])}](<{ref['path']}>) · sha256={ref['sha256']}")
        ev = r['ledger_evidence']
        text += [f"- Ledger 状态依据：[events.jsonl](<{ev['path']}>) · sequence={ev['sequence']} · module={cell(r['module_id'])} · PATH={cell(r['path_id'])}", '']
    if report['human_report']:
        text += ['## 人工待决', '', f"原因：{cell(report['human_report'].get('reason'))}",
                 f"完整根因与证据：[审计人工报告](<{report['human_report_path']}>)", '']
    text += ['本报告为 Ledger 可重建投影；不生成新验收，不触发全量复测。未执行/证据缺失保持 Yellow，原因不明明确待诊断。', '']
    return '\n'.join(text)
