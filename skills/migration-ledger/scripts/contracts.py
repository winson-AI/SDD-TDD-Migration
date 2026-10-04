"""Structural/evidence checks; business review and caller identity belong to the host."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


class Rejected(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Rejected(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


REF_LISTS = ('evidence_refs', 'context_refs')


def expand_refs(document):
    """An authored JSON document may list a file reference once under `refs` ({id: {path, sha256}}) and cite it by id from
    any `evidence_refs` or `context_refs` list. Readers get the document with every citation written out and the table
    gone, so one content has one form; a cited entry is checked and archived like any other reference."""
    table = document.get('refs') if isinstance(document, dict) else None
    if not (isinstance(table, dict) and table and all(isinstance(key, str) and isinstance(ref, dict) and set(ref) == {'path', 'sha256'}
                                                    for key, ref in table.items())):
        return document

    def cite(item):
        if isinstance(item, str):
            require(item in table, 'unknown reference id ' + item + '; the document lists ' + ', '.join(sorted(table)[:6]))
            return dict(table[item])
        return walk(item)

    def walk(value):
        if isinstance(value, dict):
            return {key: [cite(item) for item in items] if key in REF_LISTS and isinstance(items, list) else walk(items)
                    for key, items in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value
    return walk({key: value for key, value in document.items() if key != 'refs'})


def read_json(path):
    return expand_refs(json.loads(Path(path).read_text()))


def file_ref(path):
    p = Path(path).resolve()
    require(p.is_file(), f'missing file: {p}')
    sha = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return {'path': str(p), 'sha256': sha.hexdigest()}


def check_ref(ref):
    require(isinstance(ref, dict) and Path(ref.get('path', '')).is_absolute(), 'absolute evidence path required, got ' + str(ref)[:100])
    actual = file_ref(ref['path'])
    # The message names the file and its real digest: a request holding dozens of references is otherwise unfixable.
    require(actual == {'path': str(Path(ref['path']).resolve()), 'sha256': ref.get('sha256')},
            f"evidence hash mismatch: {actual['path']} is {actual['sha256']}, the reference says {ref.get('sha256')}; recompute it with contracts.py ref")
    return Path(ref['path'])


def named(text, name):
    """Whether code names `name` itself, not a longer name that merely starts or ends with it."""
    return re.search(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', text) is not None


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
    require({'proposal', 'spec', 'design', 'tasks', 'test-design'} <=
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
        require(path.get('required', True) is True, 'runtime accepts only required paths')
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
    require(plan.get('freeze_checks_passed', True) is True, 'freeze checklist incomplete')
    import dimensions
    dimensions.validate_plan(plan, module)
    import telemetry
    telemetry.validate(plan)
    import behavior_contract
    behavior_contract.validate_plan(plan, module)
    return digest(plan)


def verify_plan(plan, module=None):
    require(isinstance(plan, dict), 'SPEC not frozen/prepared')
    for ref in plan['definitions']:
        check_ref(ref)
    for path in plan['paths']:
        if path.get('kind') in ('build', 'unit'):
            check_ref(path['command']['selection_ref'])
        if path.get('visual_execution') is not None:
            execution = path['visual_execution']
            require(isinstance(execution, dict) and path.get('kind') in ('automation', 'visual'),
                    'visual execution configuration requires an automation or visual PATH')
            check_ref(execution.get('environment_ref'))
        if path.get('visual_evidence') is not None:
            require(path.get('kind') == 'visual', 'explicit visual evidence requires a visual PATH')
            import visual_evidence
            visual_evidence.frozen_evidence({'plan': {}}, path)
    import reuse
    reuse.verify(plan)
    import dimensions
    dimensions.verify(plan)
    if plan.get('dimension_analysis_ref'):
        import resource_fidelity
        resource_fidelity.require_indexed_closure(read_json(check_ref(plan['dimension_analysis_ref'])))
    import telemetry
    telemetry.verify(plan)
    if plan.get('dependency_resolution_ref'):
        import knowledge_gate
        knowledge_gate.validate_resolution(plan['dependency_resolution_ref'], strict=True)


def baseline(refs):
    nonempty(refs, 'code files')
    for ref in refs:
        check_ref(ref)
    require(len({r['path'] for r in refs}) == len(refs), 'duplicate code files')
    return digest(sorted(refs, key=lambda r: r['path']))


def authoring_diagnostics(d):
    """Code authors fix changed-file diagnostics before handoff; without them, pinned sources replace memory."""
    require(isinstance(d, dict) and d.get('status') in ('passed', 'unavailable'),
            'authoring_diagnostics status passed|unavailable required')
    if d['status'] == 'passed':
        require(isinstance(d.get('tool'), str) and d['tool'].strip() and d.get('log_ref'),
                'authoring_diagnostics tool and log_ref required')
        check_ref(d['log_ref'])
        return
    require(isinstance(d.get('reason'), str) and d['reason'].strip(), 'authoring_diagnostics unavailable reason required')
    apis = d.get('version_sensitive_apis')
    require(isinstance(apis, list), 'authoring_diagnostics version_sensitive_apis list required (may be empty)')
    for item in apis:
        require(isinstance(item, dict) and isinstance(item.get('api'), str) and item['api'].strip() and item.get('source_ref'),
                'authoring_diagnostics: each version-sensitive API needs its pinned dependency source_ref')
        check_ref(item['source_ref'])


def validate_result(result, module, assignment, run_root=None):
    require(result.get('schema_version') == 1, 'unsupported result schema')
    for field in ('run_id', 'module_id', 'assignment_id'):
        require(result.get(field) == assignment[field], f'result {field} mismatch')
    require(result.get('freeze_id') == module['freeze_id'], 'result freeze mismatch')
    require(result.get('actor_instance_id') == assignment['instance_id'], 'result actor mismatch')
    verify_plan(module['plan'], module)
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
        authoring_diagnostics(result.get('authoring_diagnostics'))
        import reuse
        reuse.validate_implementation(module['plan'], result)
        import dimensions
        dimensions.implementation(module['plan'], result)
        if assignment['role'] == 'fixer':
            note = read_json(check_ref(result.get('fix_note_ref')))
            require(all(note.get(k) for k in ('root_cause', 'strategy', 'applicability', 'risks')), 'repair memory note incomplete')
        return kind
    import dimensions
    dimensions.current(module)
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
        require(scope in ('build', 'automation', 'visual'), 'test scope required')
        require(scope == 'build' or tv.static_ready(module), 'build, unit tests and the static review must pass before automation')
        require(scope != 'visual' or tv.functional_ready(module), 'functional tests must pass before visual')
        # One build-stage result carries build -> unit -> static and stops at the first kind that is not Green.
        planned = {p['path_id']: p for p in (tv.stage_paths(module, tests) if scope == 'build' else tv.paths(module, scope))}
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
        if quality == 'yellow-blocked' and not record.get('executed') and not record.get('execution_receipt'):
            require(record.get('host_completion_version') is None, 'host completion receipt required')
            continue
        # Receipt must come from the host execution adapter, not the worker's prose.
        receipt = read_json(check_ref(record.get('execution_receipt')))
        require(not receipt.get('termination', {}).get('executor_aborted'),
                'executor aborted; Host must review cancellation and revoke with stop/isolation evidence')
        require(not receipt.get('termination', {}).get('host_stop_required'),
                'execution process stop unconfirmed; Host must verify stop/isolation and revoke with evidence')
        for field, expected in (('run_id', result['run_id']), ('module_id', result['module_id']),
                                ('path_id', pid), ('test_run_id', record['test_run_id']),
                                ('code_baseline', module['code_baseline']), ('freeze_id', module['freeze_id']),
                                ('assignment_id', assignment['assignment_id']), ('actor_instance_id', assignment['instance_id'])):
            require(receipt.get(field) == expected, f'execution receipt {field} mismatch')
        require(receipt.get('producer') == 'host-executor' and receipt.get('argv') and
                receipt.get('started_at') and receipt.get('finished_at'), 'invalid host execution receipt')
        check_ref(receipt.get('log_ref'))
        from execution_capture import validate as validate_capture
        validate_capture(receipt)
        normalized = record.get('host_completion_version') is not None
        if normalized or not record.get('executed'):
            from test_completion import interpret
            captured = interpret(receipt, planned[pid])
            if normalized:
                require(all(record.get(k) == v for k, v in captured.items()), 'host completion interpretation changed')
            if not record.get('executed'):
                require(quality == 'yellow-blocked' and not captured['executed'], 'cannot conceal captured execution')
                continue
        else:
            captured = read_json(check_ref(receipt.get('result_ref')))
        require(record.get('executed') is True, 'execution evidence required')
        if planned[pid].get('kind') in ('build', 'unit'):
            expected_argv = planned[pid]['command']['argv']
            if receipt.get('storage_command_version') == 1:
                from runner_storage import build_command
                require(receipt.get('requested_argv') == expected_argv, 'requested build command differs from frozen plan')
                expected_argv = build_command(expected_argv, check_ref(receipt.get('query_ref')).parent,
                                              unit_report=bool(planned[pid].get('unit_report')))
            build_report = read_json(check_ref(receipt.get('result_ref')))
            require(build_report.get('producer') == 'build-executor' and receipt['argv'] == expected_argv
                    and receipt['cwd'] == str(Path(planned[pid]['command']['cwd']).resolve()), 'invalid build execution receipt')
            if planned[pid].get('unit_report'):
                import unit_reports
                unit_reports.validate(receipt, planned[pid], build_report)
                require(quality == build_report['quality'] and record.get('root_cause') == build_report['root_cause'],
                        'unit report classification/root cause cannot be overridden')
                require(record.get('unit_execution') == build_report['unit_execution'], 'unit execution summary changed')
        if planned[pid].get('kind') == 'static' and module.get('scenario_index'):
            query = read_json(check_ref(receipt['query_ref']))
            require(query.get('scenario_ids') == sorted(row['scenario_id'] for row in module['scenario_index']),
                    'static scenario selection changed')
            require(query.get('scenario_index') == module['scenario_index'], 'static scenario index differs from frozen SPEC')
            require(read_json(check_ref(receipt['result_ref'])).get('producer') == 'spec-closure-check',
                    'scenario review requires spec-closure adapter')
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
        if planned[pid].get('kind') == 'build':
            require(record.get('build_artifacts', []) == captured.get('build_artifacts', []), 'build artifact evidence changed')
            for ref in captured.get('build_artifacts', []):
                artifact = check_ref(ref)
                require(artifact.is_relative_to(check_ref(receipt['query_ref']).parent), 'build artifact outside this invocation')
        tv.visual_result(module, planned[pid], record, captured, run_root=run_root, assignment=assignment)
        tv.interaction_result(module, planned[pid], record, captured)
        require(captured.get('assertions') == record.get('assertions'), 'assertions differ from captured report')
        expected = keyed(planned[pid]['expected_assertions'], 'assertion_id')
        assertions = keyed(record.get('assertions'), 'assertion_id')
        require(set(assertions) == set(expected), 'missing/extra assertions')
        for aid, assertion in assertions.items():
            require(assertion.get('expected') == expected[aid]['expected'], 'acceptance changed')
        if quality == 'green-passed':
            require(receipt.get('exit_code') == 0 and not captured.get('skipped') and not captured.get('xfail')
                    and not record.get('flaky'), 'not a clean pass')
            require(all(a.get('passed') is True and 'actual' in a and a['actual'] == a['expected'] for a in assertions.values()), 'failed/missing assertion; assertions use JSON equality')
        elif quality == 'red-bug':
            require(receipt.get('exit_code') != 0 or any(a.get('passed') is False for a in assertions.values()), 'Red needs observed failure')
    return kind


def main():
    """Hashes for a role's artifacts, computed exactly the way the Ledger checks them."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name, text in (('ref', 'the {path, sha256} reference of each file'),
                       ('baseline', 'code_files and code_baseline of the given code files')):
        sub.add_parser(name, help=text).add_argument('paths', nargs='+')
    sub.add_parser('digest', help='canonical digest of one JSON document').add_argument('path')
    args = parser.parse_args()
    try:
        if args.command == 'digest':
            out = {'sha256': digest(read_json(args.path))}
        else:
            refs = [file_ref(path) for path in args.paths]
            out = refs if args.command == 'ref' else {'code_files': refs, 'code_baseline': baseline(refs)}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except (Rejected, OSError, ValueError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
