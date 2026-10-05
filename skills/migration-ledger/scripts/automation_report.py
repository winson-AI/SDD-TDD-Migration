"""Current automation coverage, derived from accepted PATH rows, never attempts."""
from collections import Counter


def summarize(rows, case_ids):
    paths = [r for r in rows if r.get('path_id') and r['kind'] in ('automation', 'test')]
    # TASK membership is many-to-many; a shared PATH counts once in the host total.
    paths = list({(r['module_id'], r['path_id']): r for r in paths}.values())
    covered = {(r['module_id'], r['case_id']) for r in paths}
    gaps = sorted({(r['module_id'], r['case_id']) for r in rows} - covered)
    missing = sorted((set(case_ids) - {r['case_id'] for r in paths}) | {cid for _, cid in gaps})
    counts = Counter(r['quality'] for r in paths)
    successful = [r for r in paths if r['quality'] == 'green-passed' and not r['stale']]
    executed = sum(bool(r['attempt_executed']) and not r['stale'] for r in paths)
    current = [r for r in paths if r['attempt_executed'] and not r['stale']]
    completed = sum(r.get('execution_status') == 'completed' or
                    (not r.get('execution_status') and r['quality'] == 'green-passed') for r in current)
    partial = sum(r.get('execution_status') == 'incomplete' for r in current)
    observed = [r for r in paths if any(a.get('passed') is False and a.get('actual') is not None
                                      for a in r['assertions'])]
    yellow = Counter('stale' if r['stale'] else 'flaky' if r.get('flaky') else
                     'not-executed' if not r['attempt_executed'] else 'blocked'
                     for r in paths if r['quality'] == 'yellow-blocked')
    identity = lambda r: {k: r[k] for k in ('module_id', 'task_ids', 'case_id', 'path_id', 'platform',
                                          'parameters', 'code_baseline', 'test_run_id', 'evidence_refs', 'stale', 'quality')}
    total = len(paths)
    return {'schema_version': 2, 'required_paths': total, 'current_executed_paths': executed,
            'attempted_paths': executed, 'completed_paths': completed, 'partial_paths': partial,
            'completion_unknown_paths': executed - completed - partial,
            'unattempted_paths': total - executed,
            'passed_paths': len(successful), 'red_paths': counts['red-bug'],
            'yellow_paths': counts['yellow-blocked'], 'yellow_reasons': dict(yellow),
            'missing_case_paths': missing, 'coverage_gaps': [{'module_id': mid, 'case_id': cid} for mid, cid in gaps],
            'coverage_complete': bool(total) and not missing,
            'definition_coverage_complete': bool(total) and not missing,
            'validation_complete': bool(total) and not missing and completed == total,
            'attempt_coverage': executed / total if total else None,
            'completion_coverage': completed / total if total else None,
            'execution_coverage': executed / total if total else None,
            'success_coverage': len(successful) / total if total else None,
            'successful_paths': [identity(r) for r in successful],
            'observed_failure_paths': [identity(r) for r in observed]}


def build(state, rows):
    result = summarize(rows, state['case_ids'])
    result['modules'] = {}
    result['tasks'] = {}
    for mid, module in state['modules'].items():
        selected = [r for r in rows if r['module_id'] == mid]
        result['modules'][mid] = summarize(selected, set(module['case_ids']) & set(state['case_ids']))
        for task in (module.get('plan') or {}).get('tasks', []):
            result['tasks'][mid + '/' + task['task_id']] = summarize(
                [r for r in selected if task['task_id'] in r['task_ids']], set(task.get('case_ids', [])) & set(state['case_ids']))
    return result


def render(summary, cell):
    lines = ['', '## Automation 路径统计', '',
             '仅统计当前任务的 automation PATH 实例；平台/参数实例由冻结 PATH 区分，重试不增加分母。'
             '成功列表只含当前有效且已接受的 Green；缺路径 CASE 单列，不能据已有路径宣称全量覆盖。', '',
             '已尝试不等于完整执行；完整执行要求步骤与断言齐全，仍须另看成功/失败。历史非 Green 缺完整性字段时记未知。', '',
             '| 范围 | 应测 | 已尝试 | 完整执行 | 部分执行 | 完整性未知 | 有效成功 | Red | Yellow | 缺路径 CASE |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for name, row in [('宿主任务', summary), *summary['modules'].items(), *summary['tasks'].items()]:
        lines.append('| ' + ' | '.join(cell(x) for x in (name, row['required_paths'], row['current_executed_paths'],
                     row.get('completed_paths'), row.get('partial_paths'), row.get('completion_unknown_paths'),
                     row['passed_paths'], row['red_paths'], row['yellow_paths'], row['missing_case_paths'])) + ' |')
    lines += ['', '成功路径：']
    for row in summary['successful_paths']:
        lines.append(f"- {cell(row['module_id'])} / {cell(row['path_id'])} · TASK={cell(row['task_ids'])} · "
                     f"CASE={cell(row['case_id'])} · {cell(row['platform'])} · 参数={cell(row['parameters'])} · "
                     f"test_run={cell(row['test_run_id'])}；证据见路径明细/JSON。")
    if not summary['successful_paths']: lines.append('- 无当前有效成功路径。')
    failures = [r['module_id'] + '/' + r['path_id'] for r in summary['observed_failure_paths']]
    lines += ['', f"已观察到失败断言的路径（可与 Yellow 重叠，不另加分母）：{cell(failures)}", '']
    return lines
