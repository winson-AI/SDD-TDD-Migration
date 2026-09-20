"""Structural/evidence checks; business review and caller identity belong to the host."""
import hashlib
import json
import re
from pathlib import Path


class Rejected(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Rejected(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def file_ref(path):
    p = Path(path).resolve()
    require(p.is_file(), f'missing file: {p}')
    return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def check_ref(ref):
    require(isinstance(ref, dict) and Path(ref.get('path', '')).is_absolute(), 'absolute evidence path required')
    require(file_ref(ref['path']) == {'path': str(Path(ref['path']).resolve()),
                                     'sha256': ref.get('sha256')}, 'evidence hash mismatch')
    return Path(ref['path'])


def nonempty(value, label):
    require(isinstance(value, list) and bool(value), f'{label} must not be empty')
    return value


def keyed(items, field):
    nonempty(items, field)
    require(all(isinstance(x, dict) and isinstance(x.get(field), str) and x[field] for x in items), f'missing {field}')
    result = {x[field]: x for x in items}
    require(len(result) == len(items), f'duplicate {field}')
    return result


def validate_plan(plan, module):
    require(plan.get('schema_version') == 1, 'unsupported plan schema')
    require(plan.get('module_id') == module['module_id'], 'wrong plan module')
    defs = nonempty(plan.get('definitions'), 'definitions')
    require({'proposal', 'spec', 'design', 'tasks', 'checklist', 'test-design', 'global-contract'} <=
            {d.get('kind') for d in defs}, 'incomplete six-piece definitions')
    names = set()
    for item in defs:
        check_ref(item)
        key = (item['kind'], item.get('capability', module['module_id'].lower()) if item['kind'] == 'spec' else '')
        require(key not in names, 'duplicate definition output')
        names.add(key)
        if item['kind'] == 'spec':
            require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', key[1]), 'invalid capability path')
            text = check_ref(item).read_text()
            require(re.search(r'^## (ADDED|MODIFIED|REMOVED|RENAMED) Requirements', text, re.M), 'OpenSpec delta heading required')
            if re.search(r'^## (ADDED|MODIFIED) Requirements', text, re.M):
                require('### Requirement:' in text and '#### Scenario:' in text, 'OpenSpec requirement/scenario required')
            elif '## REMOVED Requirements' in text:
                require('### Requirement:' in text, 'removed requirement required')
    paths = keyed(plan.get('paths'), 'path_id')
    require(set(module['case_ids']) <= {x.get('case_id') for x in paths.values()}, 'unmapped module cases')
    for path in paths.values():
        require(path.get('name') and path.get('requirement_id'), 'path name/requirement required')
        require(path.get('required') is True, 'runtime v1 accepts only required paths')
        assertions = keyed(path.get('expected_assertions'), 'assertion_id')
        require(all('expected' in a for a in assertions.values()), 'assertion expected value required')
    tasks = keyed(plan.get('tasks'), 'task_id')
    task_text = check_ref(next(ref for ref in defs if ref['kind'] == 'tasks')).read_text()
    for tid in tasks:
        require(re.search(r'(?m)^\s*- \[[ xX]\]\s+' + re.escape(tid) + r'\b', task_text), 'task definition checkbox/ID missing')
    require({x['requirement_id'] for x in paths.values()} <=
            {v for t in tasks.values() for v in t.get('requirement_ids', [])}, 'unmapped requirements')
    for task in tasks.values():
        require(task.get('path_ids') and set(task['path_ids']) <= set(paths), 'task path trace missing')
    closure = plan.get('source_closure', {})
    for field in ('entry', 'execution_chain', 'observable_result', 'production_binding'):
        require(closure.get(field), f'source closure missing {field}')
    require(not closure.get('unresolved'), 'source closure unresolved')
    for ref in nonempty(closure.get('evidence_refs'), 'source evidence'):
        check_ref(ref)
    feasibility = plan.get('target_feasibility', {})
    require(feasibility.get('verdict') == 'ready', 'target feasibility not ready')
    for ref in nonempty(feasibility.get('evidence_refs'), 'feasibility evidence'):
        check_ref(ref)
    envelope = plan.get('decision_envelope', {})
    for field in ('scope', 'acceptance', 'allowed_alternatives', 'forbidden_changes'):
        require(field in envelope, f'envelope missing {field}')
    nonempty(envelope['scope'], 'approved scope')
    nonempty(envelope['acceptance'], 'approved acceptance')
    require(plan.get('freeze_checks_passed') is True, 'freeze checklist incomplete')
    return digest(plan)


def verify_plan(plan):
    require(isinstance(plan, dict), 'SPEC not frozen/prepared')
    for ref in plan['definitions']:
        check_ref(ref)
    for path in plan['paths']:
        if path.get('kind') == 'build':
            check_ref(path['command']['selection_ref'])
    import reuse
    reuse.verify(plan)


def baseline(refs):
    nonempty(refs, 'code files')
    for ref in refs:
        check_ref(ref)
    require(len({r['path'] for r in refs}) == len(refs), 'duplicate code files')
    return digest(sorted(refs, key=lambda r: r['path']))


def validate_result(result, module, assignment):
    require(result.get('schema_version') == 1, 'unsupported result schema')
    for field in ('run_id', 'module_id', 'assignment_id'):
        require(result.get(field) == assignment[field], f'result {field} mismatch')
    require(result.get('freeze_id') == module['freeze_id'], 'result freeze mismatch')
    require(result.get('actor_instance_id') == assignment['instance_id'], 'result actor mismatch')
    verify_plan(module['plan'])
    kind = result.get('kind')
    if kind == 'implementation':
        require(assignment['role'] in ('implementer', 'fixer'), 'implementation owner mismatch')
        require(result.get('code_baseline') == baseline(result.get('code_files')), 'code baseline mismatch')
        scope = [Path(p).resolve() for p in module['write_paths']]
        for ref in result['code_files']:
            require(any(Path(ref['path']).resolve().is_relative_to(p) for p in scope), 'code outside module scope')
        traces = keyed(result.get('task_trace'), 'task_id')
        require(set(traces) == {t['task_id'] for t in module['plan']['tasks']}, 'incomplete task trace')
        code_paths = {r['path'] for r in result['code_files']}
        require(code_paths == {str(Path(p).resolve()) for t in traces.values() for p in t.get('files', [])}, 'unowned code or missing task file')
        require(result.get('production_binding_evidence'), 'production binding evidence required')
        check_ref(result['production_binding_evidence'])
        import reuse
        reuse.validate_implementation(module['plan'], result)
        if assignment['role'] == 'fixer':
            note = read_json(check_ref(result.get('fix_note_ref')))
            require(all(note.get(k) for k in ('root_cause', 'strategy', 'applicability', 'risks')), 'repair memory note incomplete')
        return kind
    if kind == 'audit-review':
        require(assignment['role'] == 'auditor' and assignment.get('scope_policy') == 'non-green-only', 'review owner/scope mismatch')
        require(not module['plan']['paths'] and result.get('paths') == [], 'review cannot skip unresolved paths')
        require(result.get('execution_status') == 'no-retest-needed', 'explicit no-retest conclusion required')
        require(result.get('code_baseline') == module['code_baseline'] == baseline(module['code_files']), 'review baseline mismatch')
        check_ref(result.get('review_ref'))
        return kind
    require(kind == 'tests' and assignment['role'] in ('test-runner', 'auditor'), 'unsupported result kind/owner')
    require(result.get('code_baseline') == module['code_baseline'], 'test baseline mismatch')
    require(baseline(module['code_files']) == module['code_baseline'], 'current code changed')
    tests = keyed(result.get('paths'), 'path_id')
    planned = {p['path_id']: p for p in module['plan']['paths']}
    import test_validation as tv
    if tv.split(module) and assignment.get('role') == 'test-runner':
        scope = assignment.get('test_scope')
        require(scope in ('build', 'automation'), 'test scope required')
        require(scope == 'build' or tv.build_ready(module), 'build must pass before automation')
        planned = {p['path_id']: p for p in tv.paths(module, scope)}
    require(set(tests) == set(planned), 'result must account for every required path')
    for pid, record in tests.items():
        quality = record.get('quality')
        require(quality in ('green-passed', 'red-bug', 'yellow-blocked'), 'invalid quality')
        previous = module['results'].get(pid)
        if previous and (previous['quality'] != 'green-passed' or module['stale']):
            require(record.get('retest_of') == previous['test_run_id'], 'missing non-Green/stale retest chain')
            require(record.get('test_run_id') != previous['test_run_id'], 'retest must be a new run')
        require(record.get('test_run_id'), 'test_run_id required')
        if quality != 'green-passed':
            cause = record.get('root_cause', {})
            require(all(cause.get(k) for k in ('category', 'summary', 'confidence', 'owner', 'next_action')), 'root cause/owner required')
        if quality == 'yellow-blocked' and not record.get('executed'):
            continue
        require(record.get('executed') is True, 'execution evidence required')
        # Receipt must come from the host execution adapter, not the worker's prose.
        receipt = read_json(check_ref(record.get('execution_receipt')))
        for field, expected in (('run_id', result['run_id']), ('module_id', result['module_id']),
                                ('path_id', pid), ('test_run_id', record['test_run_id']),
                                ('code_baseline', module['code_baseline']), ('freeze_id', module['freeze_id']),
                                ('assignment_id', assignment['assignment_id']), ('actor_instance_id', assignment['instance_id'])):
            require(receipt.get(field) == expected, f'execution receipt {field} mismatch')
        require(receipt.get('producer') == 'host-executor' and receipt.get('argv') and
                receipt.get('started_at') and receipt.get('finished_at'), 'invalid host execution receipt')
        check_ref(receipt.get('log_ref'))
        captured = read_json(check_ref(receipt.get('result_ref')))
        if planned[pid].get('kind') == 'build':
            require(captured.get('producer') == 'build-executor' and receipt['argv'] == planned[pid]['command']['argv']
                    and receipt['cwd'] == str(Path(planned[pid]['command']['cwd']).resolve()), 'invalid build execution receipt')
        if captured.get('producer') == 'harmony-adapter':
            require(captured.get('quality') == quality and captured.get('flaky') == record.get('flaky', False),
                    'Harmony classification cannot be overridden')
            query = read_json(check_ref(receipt.get('query_ref')))
            require(captured.get('query_sha256') == digest(query), 'Harmony query mismatch')
            for field in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline'):
                require(captured.get(field) == receipt.get(field), 'Harmony context mismatch')
            observations = read_json(check_ref(captured.get('observations_ref')))
            for observation in observations:
                for evidence in observation.get('evidence_refs', []):
                    check_ref(evidence)
            for artifact in captured.get('artifacts', []):
                check_ref(artifact)
            if quality != 'green-passed':
                require(captured.get('root_cause') == record.get('root_cause'), 'Harmony root cause changed')
        require(captured.get('assertions') == record.get('assertions'), 'assertions differ from captured report')
        expected = keyed(planned[pid]['expected_assertions'], 'assertion_id')
        assertions = keyed(record.get('assertions'), 'assertion_id')
        require(set(assertions) == set(expected), 'missing/extra assertions')
        for aid, assertion in assertions.items():
            require(assertion.get('expected') == expected[aid]['expected'], 'acceptance changed')
        if quality == 'green-passed':
            require(receipt.get('exit_code') == 0 and not captured.get('skipped') and not record.get('flaky'), 'not a clean pass')
            require(all(a.get('passed') is True and 'actual' in a and a['actual'] == a['expected'] for a in assertions.values()), 'failed/missing assertion; v1 uses JSON equality')
        elif quality == 'red-bug':
            require(receipt.get('exit_code') != 0 or any(a.get('passed') is False for a in assertions.values()), 'Red needs observed failure')
    return kind
