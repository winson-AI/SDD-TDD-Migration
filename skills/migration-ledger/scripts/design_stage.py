"""Independent, read-only test design on the existing assignment/event bus."""
import copy
from pathlib import Path

from contracts import Rejected, check_ref, digest, keyed, nonempty, read_json, require
import decomposition
import workflow

PHASES = ('context', 'specifying', 'change-review')


def is_design(assignment):
    return assignment.get('mode') == 'design'


def required(s, m):
    # Prepared runs set the run-level gate. A low-level run without it enables the gate for a leaf on its
    # first design dispatch, and it stays on through revocation/invalidation.
    return s.get('test_design_required', False) or m.get('test_design_required', False)


def subject(s, m):
    context = decomposition.planning_context(s)
    return digest({'context': context, 'allocation': decomposition.assigned_module(s, m),
                   'generation': m.get('design_generation', 0)})


def task_scope(task):
    return {k: task.get(k) for k in ('task_id', 'scope', 'requirement_ids', 'global_requirement_ids')}


def input_check(s, m, ref):
    doc = read_json(check_ref(ref))
    require(doc.get('schema_version') == 1 and doc.get('module_id') == m['module_id'], 'design input module/schema mismatch')
    require(doc.get('planning_context') == decomposition.planning_context(s) and
            doc.get('assigned_module') == decomposition.assigned_module(s, m), 'design input allocation/context stale')
    specs = nonempty(doc.get('spec_refs'), 'design input specs')
    for item in specs:
        require(item.get('kind') == 'spec', 'design input requires spec definitions')
        check_ref(item)
    for item in nonempty(doc.get('case_refs'), 'design input cases'):
        check_ref(item)
    tasks = keyed(doc.get('tasks'), 'task_id')
    allowed = {r for r, owners in s['global_plan']['content']['requirement_owners'].items() if m['module_id'] in owners}
    covered = set()
    for task in tasks.values():
        reqs = set(nonempty(task.get('requirement_ids'), 'design task requirements'))
        covered.update(nonempty(task.get('global_requirement_ids', list(reqs)), 'design task global requirements'))
        scope = task.get('scope') or {}
        nonempty(scope.get('in'), 'design task scope')
        require(isinstance(scope.get('out'), list), 'design task exclusions required')
        for path in nonempty(scope.get('write_paths'), 'design task write scope'):
            require(Path(path).is_absolute() and any(Path(path).resolve().is_relative_to(Path(p).resolve())
                    for p in m['write_paths']), 'design task outside module write scope')
    require(covered == allowed, 'design tasks must cover assigned requirements exactly')
    return doc


def dispatch(s, m, p, actor, sequence):
    require(p.get('role') == 'test-runner' and not p.get('test_scope'), 'design mode requires Test-Runner without execution scope')
    require(m['phase'] in PHASES and not m.get('blocked') and not m.get('decomposition_required'), 'design requires an unblocked planning leaf')
    require(not any(not a.get('closed') for a in m['assignments'].values()), 'worker still active')
    require(p.get('assignment_id') and p['assignment_id'] not in m['assignments'] and p.get('instance_id'), 'invalid/duplicate design assignment')
    spec_authors = set(m.get('spec_authors', [])) | {r['report']['producer']['instance_id']
        for r in m.get('context_receipts', {}).values() if r['report']['stage'] == 'planning'}
    require(p['instance_id'] != actor['instance_id'] and p['instance_id'] not in spec_authors and
            not any(a['role'] in ('implementer', 'fixer') and a['instance_id'] == p['instance_id'] for a in m['assignments'].values()),
            'design author must be independent of MO, Spec and code authors')
    workflow.planning_guard(s, m['module_id'])
    require(not s.get('audit_batch') or s['audit_batch'].get('status') in ('released', 'verified', 'completed-with-unverified-tests'),
            'design unavailable during active audit; release before replanning')
    require(sum(not a.get('closed') for mod in s['modules'].values() for a in mod['assignments'].values()) < s['max_parallel_modules'],
            'parallel budget exhausted')
    inputs = input_check(s, m, p.get('design_input_ref'))
    m['test_design_required'] = True
    m.pop('accepted_test_design', None)
    m['design_input_ref'] = copy.deepcopy(p['design_input_ref'])
    m['assignments'][p['assignment_id']] = {**copy.deepcopy(p), 'run_id': s['run_id'], 'module_id': m['module_id'],
        'freeze_id': None, 'code_baseline': None, 'closed': False, 'fencing_token': sequence,
        'input_subject': subject(s, m), 'input_content': inputs,
        'assigned_by': copy.deepcopy(actor), 'resume_phase': m['phase']}
    for key in ('authors', 'design_authors'):
        if p['instance_id'] not in m.setdefault(key, []):
            m[key].append(p['instance_id'])


def current(s, m, a):
    require(is_design(a) and a.get('input_subject') == subject(s, m), 'design input stale; revoke or redesign')
    return input_check(s, m, a['design_input_ref'])


def valid(s, m, a):
    try:
        current(s, m, a)
        return True
    except (Rejected, OSError, KeyError, TypeError, ValueError):
        return False


def result_check(s, m, a, result):
    doc = current(s, m, a)
    require(result.get('schema_version') == 1 and result.get('kind') == 'test-design', 'design assignment only accepts test-design result')
    for field in ('run_id', 'module_id', 'assignment_id'):
        require(result.get(field) == a[field], 'design result ' + field + ' mismatch')
    require(result.get('actor_instance_id') == a['instance_id'], 'design result actor mismatch')
    require(result.get('input_ref') == a['design_input_ref'], 'design result input mismatch')
    require(result.get('freeze_id') is None and result.get('code_baseline') is None and not result.get('code_files'),
            'design result cannot claim code or a freeze')
    check_ref(result.get('design_ref'))
    paths = keyed(result.get('paths'), 'path_id')
    require({p.get('case_id') for p in paths.values()} == set(m['case_ids']), 'design must cover assigned cases exactly')
    reqs = {r for t in doc['tasks'] for r in t['requirement_ids']}
    for path in paths.values():
        require(path.get('name') and path.get('requirement_id') in reqs and path.get('required') is True,
                'design PATH name/requirement/required invalid')
        require(not {'quality', 'executed', 'test_run_id', 'execution_receipt'}.intersection(path), 'design PATH cannot claim execution')
        for assertion in keyed(path.get('expected_assertions'), 'assertion_id').values():
            require('expected' in assertion and not {'actual', 'passed'}.intersection(assertion), 'design assertion must be an expectation only')
    if s.get('split_testing_required') or any(p.get('kind') == 'build' for p in paths.values()):
        import test_validation
        test_validation.plan_check({'paths': result['paths'], 'tasks': doc['tasks']}, s['target_root'],
                                   static_required=s.get('spec_closure_required', False))
    return doc


def submission(s, m, a, p, actor=None):
    require(m['phase'] in PHASES and not m.get('blocked'), 'design result outside planning phase')
    result = read_json(check_ref(p['result_ref']))
    result_check(s, m, a, result)
    if s.get('context_readiness_required'):
        import context_readiness
        require(p.get('context_ref'), 'context readiness receipt required for test-design')
        if actor is not None:
            # The designer's read-only preflight rides its submit: one event carries the report and the result.
            context_readiness.submit(s, {'payload': {'report_ref': p['context_ref']}, 'module_id': m['module_id']}, actor)
        context_readiness.validate(s, m['module_id'], 'test-design', p.get('context_ref'), a['instance_id'], p['result_ref'])
    m['submissions'][a['assignment_id']] = {'ref': p['result_ref'], 'result': result, 'context_ref': p.get('context_ref')}


def accept(s, m, a, p, actor):
    sub = m['submissions'].get(a['assignment_id'])
    require(sub, 'no active design submission')
    require(actor['instance_id'] != a['instance_id'], 'design owner cannot accept own result')
    submission(s, m, a, {'result_ref': sub['ref'], 'context_ref': sub.get('context_ref')})
    check_ref(p.get('review_ref'))
    a['closed'] = True
    m['accepted_test_design'] = {'assignment_id': a['assignment_id'], 'result_ref': sub['ref'],
                               'review_ref': p['review_ref'], 'accepted_by': copy.deepcopy(actor)}


def accepted(s, m):
    record = m.get('accepted_test_design') or {}
    a = m['assignments'].get(record.get('assignment_id'), {})
    require(a.get('closed') and not a.get('revoked'), 'accepted independent test design required')
    result = read_json(check_ref(record.get('result_ref')))
    result_check(s, m, a, result)
    check_ref(record['review_ref'])
    return a, result


def ready(s, m):
    try:
        accepted(s, m)
        return True
    except (Rejected, OSError, KeyError, TypeError, ValueError):
        return False


def plan_check(s, m, plan, author=None):
    if not required(s, m):
        require(not plan.get('test_design_ref'), 'test_design_ref requires an accepted design assignment')
        return
    a, result = accepted(s, m)
    require(author is None or author not in m.get('design_authors', []), 'Spec author must be independent of design author')
    require(plan.get('test_design_ref') == m['accepted_test_design']['result_ref'], 'plan must bind accepted test_design_ref')
    require(plan['paths'] == result['paths'], 'plan PATH/assertions differ from accepted design')
    doc = read_json(check_ref(a['design_input_ref']))
    require([task_scope(t) for t in plan['tasks']] == [task_scope(t) for t in doc['tasks']], 'plan tasks differ from MO design input')
    specs = [r for r in plan['definitions'] if r['kind'] == 'spec']
    require(specs == doc['spec_refs'], 'plan specs differ from design input')
    defs = [r for r in plan['definitions'] if r['kind'] == 'test-design']
    require(len(defs) == 1 and {k: defs[0][k] for k in ('path', 'sha256')} == result['design_ref'],
            'plan test-design definition differs from accepted design')
