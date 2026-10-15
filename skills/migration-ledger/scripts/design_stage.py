"""Upstream test plans and optional independent design on the existing event bus."""
import copy
from pathlib import Path

from contracts import Rejected, check_ref, digest, intact, keyed, nonempty, read_json, require
import decomposition
import workflow
import prepared_tests
from prepared_tests import assets as test_assets

PHASES = ('context', 'specifying', 'change-review')


def upstream_refs(s):
    context = decomposition.planning_context(s)
    ref = context.get('project_sources', {}).get('test_cases_path')
    return [ref or s['global_spec']]


def definition_kind(kind):
    return kind if kind == 'test-source' else 'test-' + kind


def check_assets(s, result):
    assets = test_assets(result)
    owned = []
    if assets and s.get('project_context_ref'):
        import project_context
        run_root = Path(project_context.verify_snapshot(s['project_context_ref'])['run_root'])
        owned = [run_root/'staging', run_root/'runs/harmony/sandbox/design']
    for asset in assets:
        path = check_ref(asset['ref'])
        require(any(path.is_relative_to(root) for root in owned) or
                not owned and not any(path.is_relative_to(Path(s[root]).resolve()) for root in ('target_root', 'legacy_root') if s.get(root)),
                'prepared test asset belongs in staging, not production source roots')
    return assets


def coverage(s, m, result, tasks):
    paths = keyed(result.get('paths'), 'path_id')
    require({p.get('case_id') for p in paths.values()} == set(m['case_ids']), 'design must cover assigned cases exactly')
    reqs = {r for t in tasks for r in t['requirement_ids']}
    for path in paths.values():
        require(path.get('name') and path.get('requirement_id') in reqs and path.get('required', True) is True,
                'design PATH name/requirement/required invalid')
        require(not {'quality', 'executed', 'test_run_id', 'execution_receipt'}.intersection(path), 'design PATH cannot claim execution')
        for assertion in keyed(path.get('expected_assertions'), 'assertion_id').values():
            require('expected' in assertion and not {'actual', 'passed'}.intersection(assertion), 'design assertion must be an expectation only')
    prepared_tests.preparation(result, s.get('planning_coverage_required', False), freezing=True)
    check_assets(s, result)


def upstream_plan(s, m, plan, judge=True):
    """The test plan a SPEC brings with it. It is judged with the plan that submits it; the plan the Ledger already
    holds is only held to the upstream cases, allocation and context that are current now."""
    result = read_json(check_ref(plan.get('test_design_ref')))
    require(result.get('schema_version') == 1 and result.get('kind') == 'upstream-test-plan' and
            result.get('module_id') == m['module_id'], 'upstream test plan module/kind/schema mismatch')
    require(result.get('case_refs') == upstream_refs(s), 'test plan must bind authoritative upstream cases')
    for ref in result['case_refs']: check_ref(ref)
    require(result.get('subject_sha256') == subject(s, m), 'test plan allocation/context stale')
    if not judge:
        return result
    require(not {'actual', 'passed', 'quality', 'executed', 'code_baseline', 'freeze_id'}.intersection(result),
            'upstream test plan cannot claim execution')
    coverage(s, m, result, plan['tasks'])
    if s.get('behavior_contract_required'):
        import behavior_contract
        index = spec_scenarios(m, [d for d in plan['definitions'] if d['kind'] == 'spec'])
        behavior_contract.check_design(index, result['paths'])
        known = {row['scenario_id'] for row in index}
        for asset in prepared_tests.assets(result):
            if asset['kind'] == 'test-source':
                require({row['scenario_id'] for row in asset['scenarios']} <= known, 'test source maps a scenario the SPEC does not define')
    return result


def subject(s, m):
    continuation = m.get('planning_continuation') or {}
    if continuation.get('context_ref') == s.get('project_context_ref') and continuation.get('subject_sha256') and (
            continuation.get('generation') == m.get('design_generation', 0) and
            continuation.get('allocation_sha256') == digest({key: m.get(key) for key in (*decomposition.ALLOCATION_KEYS, 'dependencies')})):
        check_ref(continuation['review_ref'])
        return continuation['subject_sha256']
    context = decomposition.standing(s, m['module_id'])
    return digest({'context': context, 'allocation': decomposition.assigned_module(s, m),
                   'generation': m.get('design_generation', 0)})


def task_scope(task):
    return {k: task.get(k) for k in ('task_id', 'scope', 'requirement_ids', 'global_requirement_ids')}


def spec_scenarios(m, specs):
    """The scenarios the design's spec_refs define. Under the behavior contract they are the leaf's own SPEC draft: the
    designer's assertions answer to its Scenario-IDs, and the plan must cite the very same files."""
    import behavior_contract
    try:
        return behavior_contract.scenario_index({'module_id': m['module_id'], 'definitions': specs})
    except Rejected as exc:
        raise Rejected("design input spec_refs must be the leaf's own SPEC draft with Requirement-IDs and Scenario-IDs, staged by the "
                       'Spec-Designer before the design is dispatched; a global spec or a context file is not one (' + str(exc) + ')') from None


def materialize(s, m, plan, judge=True):
    """Complete a plan with what it takes unchanged from the accepted design, so its author does not copy it.

    The completed plan is what the Ledger stores, hashes and has approved; anything the submitted plan
    still carries must equal the design, which plan_check verifies."""
    if not s.get('test_design_required') and not plan.get('test_design_ref'): return plan
    result = upstream_plan(s, m, plan, judge)
    doc = {'tasks': plan['tasks'], 'spec_refs': [d for d in plan['definitions'] if d['kind'] == 'spec']}
    ref = plan['test_design_ref']
    plan = copy.deepcopy(plan)
    plan.setdefault('test_design_ref', copy.deepcopy(ref))
    plan.setdefault('paths', copy.deepcopy(result['paths']))
    if test_assets(result): plan['test_asset_contract_version'] = 1
    designed = {t['task_id']: t for t in doc['tasks']}
    for task in plan.get('tasks') or []:
        for key in ('scope', 'requirement_ids', 'global_requirement_ids'):
            if key not in task and key in designed.get(task.get('task_id'), {}):
                task[key] = copy.deepcopy(designed[task['task_id']][key])
    definitions = list(plan.get('definitions') or [])
    kinds = {d.get('kind') for d in definitions}
    if 'spec' not in kinds:
        definitions += copy.deepcopy(doc['spec_refs'])
    if 'test-design' not in kinds:
        definitions.append({**result['design_ref'], 'kind': 'test-design'})
    for asset in test_assets(result):
        definition = {**asset['ref'], 'kind': definition_kind(asset['kind'])}
        if definition not in definitions: definitions.append(definition)
    plan['definitions'] = definitions
    return plan


def plan_check(s, m, plan, author=None, judge=True):
    """A plan carries the paths of its design unchanged. `judge` is off for the plan the Ledger already holds."""
    if not s.get('test_design_required') and not plan.get('test_design_ref'): return
    result = upstream_plan(s, m, plan, judge)
    require(plan['paths'] == result['paths'], 'plan PATH/assertions differ from accepted design')
    defs = [r for r in plan['definitions'] if r['kind'] == 'test-design']
    require(len(defs) == 1 and {k: defs[0][k] for k in ('path', 'sha256')} == result['design_ref'],
            'plan test-design definition differs from accepted design')
    require([r for r in plan['definitions'] if r['kind'] in ('test-script', 'test-fixture', 'test-adapter', 'test-source')] ==
            [{**row['ref'], 'kind': definition_kind(row['kind'])} for row in test_assets(result)],
            'plan test assets differ from accepted design')
