"""Behavior closure and OpenSpec-derived scenario coverage.

These checks validate the review's structure and references, not business semantics.
Prepared runs always enable the contract; `behavior_contract_required` is off only in low-level fixtures.
"""
import argparse
import json
import re
import sys
sys.dont_write_bytecode = True

from contracts import check_ref, digest, intact, keyed, nonempty, require


def review(module, value):
    require(isinstance(value, dict), 'behavior_review required')
    # A review covers the allocation it is attached to; a scope digest or coverage list, when written, must match it.
    scope = digest(module.get('scope'))
    require(value.get('scope_sha256', scope) == scope, 'behavior review scope mismatch')
    for field in ('entry', 'observable_result', 'production_binding', 'boundary_rationale'):
        require(isinstance(value.get(field), str) and value[field].strip(), 'behavior review missing ' + field)
    for field, expected in (('requirement_ids', module.get('scope', {}).get('requirement_ids', [])),
                            ('case_ids', module.get('case_ids', []))):
        values = nonempty(value.get(field, expected), 'behavior review ' + field)
        require(len(set(values)) == len(values) and set(values) == set(expected), 'behavior review coverage: ' + field)
    require(value.get('unresolved') == [], 'unresolved behavior boundary; request parent/GO or human decision')
    for ref in nonempty(value.get('evidence_refs'), 'behavior review evidence'):
        check_ref(ref)
    shared = value.get('shared_capabilities')
    require(isinstance(shared, list), 'shared_capabilities must be explicit (may be empty)')
    seen = set()
    for row in shared:
        cid = row.get('capability_id')
        require(isinstance(cid, str) and cid and cid not in seen, 'duplicate/missing shared capability')
        seen.add(cid)
        require(row.get('owner_module_id') and row.get('integration_responsibility'), 'shared provider owner/integration responsibility required')
        nonempty(row.get('consumer_module_ids'), 'shared capability consumers')
        nonempty(row.get('integration_case_ids'), 'shared integration cases')


def global_review(state):
    """What holds across the registered allocations. Each allocation was judged when it was registered and is only read here."""
    if not state.get('behavior_contract_required'):
        return
    modules = {**state.get('module_groups', {}), **state['modules']}
    distinct(list(state['modules'].values()))
    owners = {}
    for mid, module in modules.items():
        intact(lambda: (review(module, module.get('behavior_review')), mid in state['modules'] and verification(module)))
        for row in (module.get('behavior_review') or {}).get('shared_capabilities') or []:
            cid, owner = row['capability_id'], row['owner_module_id']
            require(owner in modules and set(row['consumer_module_ids']) <= set(modules), 'shared capability unknown owner/consumer')
            consumer_cases = {cid for mid in row['consumer_module_ids'] for cid in modules[mid]['case_ids']}
            require(set(row['integration_case_ids']) <= consumer_cases, 'shared integration case has no declared consumer owner')
            owners.setdefault(cid, set()).add(owner)
    for cid, declared in owners.items():
        # GO names root ownership before children exist; parents refine it to one leaf writer.
        # Treat that refinement as the same ownership, not a competing implementation.
        writers = declared.intersection(state['modules'])
        require(len(writers) == 1, 'shared capability has competing owners or no executable owner: ' + cid)
        writer = next(iter(writers))
        for owner in declared - writers:
            require(writer in state.get('module_groups', {}).get(owner, {}).get('children', []),
                    'shared capability owner outside parent allocation: ' + cid)


def verification(module):
    value = (module.get('behavior_review') or {}).get('verification')
    require(isinstance(value, dict), 'verification boundary required')
    require(value.get('acceptance_owner') == module['module_id'], 'verification acceptance owner mismatch')
    for field in ('independent_observation', 'isolation_strategy', 'integration_responsibility'):
        require(isinstance(value.get(field), str) and value[field].strip(), 'verification missing ' + field)
    check_ref(value.get('fixture_contract_ref'))
    require(set(nonempty(value.get('case_ids'), 'verification cases')) == set(module['case_ids']), 'verification case coverage mismatch')
    require(isinstance(value.get('integration_case_ids'), list) and set(value['integration_case_ids']) <= set(module['case_ids']),
            'verification integration cases outside allocation')
    inputs = value.get('provider_inputs')
    require(isinstance(inputs, list), 'verification provider inputs required (may be empty)')
    providers = keyed(inputs, 'module_id') if inputs else {}
    require(set(providers) == set(module['dependencies']), 'verification providers must match actual dependencies')
    for row in providers.values():
        require(row.get('required_stage') in ('implemented', 'verified'), 'provider stage must be implemented or verified')
        check_ref(row.get('contract_ref'))
    return value


def distinct(modules):
    """Two slices with the same entry and the same observation are one slice, whatever their identifiers say."""
    seen = set()
    for module in modules:
        value = module.get('behavior_review') or {}
        boundary = value.get('verification')
        if not boundary:
            continue
        signature = (value.get('entry'), boundary.get('independent_observation'))
        require(signature not in seen, 'duplicate verification boundary; reslice or declare a distinct observation')
        seen.add(signature)


def scenario_index(plan):
    """Derive exact IDs/content hashes from the submitted OpenSpec, not a second spec."""
    rows = []
    for definition in plan['definitions']:
        if definition['kind'] != 'spec':
            continue
        text = check_ref(definition).read_text()
        # Do not interpret headings/IDs in examples as executable requirements.
        text = re.sub(r'(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$', '', text)
        text = re.sub(r'(?s)<!--.*?-->', '', text)
        blocks = re.split(r'(?m)^### Requirement:\s*', text)[1:]
        require(blocks, 'scenario contract needs OpenSpec requirements')
        for block in blocks:
            parts = re.split(r'(?m)^#### Scenario:\s*', block)
            ids = re.findall(r'(?m)^Requirement-ID:\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*$', parts[0])
            require(len(ids) == 1, 'each Requirement needs one Requirement-ID')
            require(len(parts) > 1, 'each requirement needs a verifiable Scenario (including removal/migration behavior)')
            for scenario in parts[1:]:
                sid = re.findall(r'(?m)^Scenario-ID:\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*$', scenario)
                require(len(sid) == 1, 'each Scenario needs one Scenario-ID')
                rows.append({'scenario_id': sid[0], 'requirement_id': ids[0],
                             'capability': definition.get('capability', plan['module_id'].lower()),
                             'spec_sha256': definition['sha256'], 'scenario_sha256': digest(scenario.strip())})
    keyed(rows, 'scenario_id')
    return sorted(rows, key=lambda row: row['scenario_id'])


def index(plan):
    """The scenario index of a plan under the contract: derived from its SPEC, never authored."""
    return scenario_index(plan) if plan.get('behavior_contract_required') else []


BEHAVIOR_KINDS = ('unit', 'automation', 'visual')  # what proves behavior; build and static PATHs do not


def tagged(plan):
    """{scenario_id: [(path_id, assertion_id)]}: the designer states which scenarios an assertion verifies (`scenario_ids`)."""
    found = {}
    for path in plan['paths']:
        for assertion in path.get('expected_assertions', []):
            for sid in assertion.get('scenario_ids') or []:
                found.setdefault(sid, []).append((path['path_id'], assertion['assertion_id']))
    return found


def complete(plan):
    """Each scenario_trace row takes its assertions from the assertions that name the scenario, so its author writes the
    tasks only; a row that lists assertions anyway must list exactly those, which validate_plan checks."""
    found = tagged(plan)
    for row in plan.get('scenario_trace') or []:
        if isinstance(row, dict) and 'assertions' not in row:
            row['assertions'] = [{'path_id': pid, 'assertion_id': aid} for pid, aid in found.get(row.get('scenario_id'), [])]


def check_design(rows, paths):
    """A design answers to the SPEC it is made from: every behavior assertion names the scenarios it verifies and every
    scenario is verified by one, so the Spec-Designer cannot relabel what the independent designer covered."""
    scenarios = {row['scenario_id']: row for row in rows}
    named = set()
    for path in paths:
        behavior = path.get('kind', 'automation') in BEHAVIOR_KINDS
        for assertion in path.get('expected_assertions', []):
            label = path['path_id'] + '/' + assertion['assertion_id']
            ids = assertion.get('scenario_ids')
            if not behavior:
                require(not ids, 'build/static cannot prove scenario behavior: ' + label + ' names scenarios')
                continue
            require(isinstance(ids, list) and ids and len(set(ids)) == len(ids) and all(isinstance(i, str) for i in ids),
                    'design assertion ' + label + ' needs scenario_ids: the SPEC scenarios it verifies')
            require(set(ids) <= set(scenarios), 'design assertion ' + label + ' names a scenario its SPEC does not define')
            for sid in ids:
                rid = scenarios[sid]['requirement_id']
                require(rid == path.get('requirement_id') or rid in path.get('requirement_ids', []),
                        'design assertion ' + label + ' names ' + sid + ', a scenario of another requirement')
            named.update(ids)
    missing = sorted(set(scenarios) - named)
    require(not missing, 'SPEC scenarios no design assertion verifies: ' + ', '.join(missing[:8]) + (' ...' if len(missing) > 8 else ''))


def shared_writers(state):
    """capability_id -> the one leaf that builds a shared capability, from the registered behavior reviews."""
    declared = {}
    for module in {**state.get('module_groups', {}), **state['modules']}.values():
        for row in (module.get('behavior_review') or {}).get('shared_capabilities', []):
            declared.setdefault(row['capability_id'], set()).add(row['owner_module_id'])
    return {cid: next(iter(owners & set(state['modules']))) for cid, owners in declared.items()
            if len(owners & set(state['modules'])) == 1}


def check_owners(state, selected):
    """One capability, one owner: a reuse catalogue provider owner must be the leaf the behavior reviews name."""
    writers = shared_writers(state)
    require(all(row['owner'] == writers[row['capability_id']] for row in selected if row['capability_id'] in writers),
            'shared capability owner differs from the reuse catalogue provider owner')


def validate_plan(plan, module):
    enabled = plan.get('behavior_contract_required', False)
    require(type(enabled) is bool, 'behavior_contract_required must be boolean')
    if not enabled:
        return
    review(module, plan.get('source_closure'))  # the leaf's source closure is its behavior review
    index = scenario_index(plan)
    require(plan.get('scenario_index') in (None, index), 'scenario_index is derived from the OpenSpec definitions; omit it')
    scenarios = keyed(index, 'scenario_id')
    tasks, paths = keyed(plan['tasks'], 'task_id'), keyed(plan['paths'], 'path_id')
    require({r['requirement_id'] for r in index} == {r for t in tasks.values() for r in t['requirement_ids']},
            'SPEC scenario requirements must match task requirements')
    traces = keyed(plan.get('scenario_trace'), 'scenario_id')
    require(set(traces) == set(scenarios), 'scenario_trace must cover every frozen Scenario exactly once')
    found = tagged(plan)
    require(set(found) <= set(scenarios), 'assertions name scenarios the SPEC does not define: ' + ', '.join(sorted(set(found) - set(scenarios))))
    covered_tasks, covered_assertions = set(), set()
    for sid, trace in traces.items():
        rid = scenarios[sid]['requirement_id']
        tids = set(nonempty(trace.get('task_ids'), 'scenario task coverage'))
        require(tids <= set(tasks) and all(rid in tasks[t]['requirement_ids'] for t in tids), 'scenario task/requirement mismatch')
        covered_tasks.update(tids)
        linked_paths = {pid for tid in tids for pid in tasks[tid]['path_ids']}
        derived = sorted(found.get(sid, []))
        listed = trace.get('assertions')
        require(listed is None or sorted((a.get('path_id'), a.get('assertion_id')) for a in listed) == derived,
                'scenario_trace assertions of ' + sid + ' differ from the assertions that name it; omit them')
        require(derived, 'no assertion names scenario ' + sid + ' (scenario_ids on the designed assertions)')
        for pid, aid in derived:
            require(pid in linked_paths and pid in paths, 'scenario assertion outside task paths')
            path = paths[pid]
            require(path.get('kind', 'automation') in BEHAVIOR_KINDS, 'build/static cannot prove scenario behavior')
            require(rid == path.get('requirement_id') or rid in path.get('requirement_ids', []), 'scenario path/requirement mismatch')
            require(path['case_id'] in module['case_ids'], 'scenario case outside module')
            covered_assertions.add((pid, aid))
    require(covered_tasks == set(tasks), 'every task must contribute to a scenario, including supporting tasks')
    required = {(p['path_id'], a['assertion_id']) for p in paths.values()
                if p.get('kind', 'automation') in BEHAVIOR_KINDS for a in p['expected_assertions']}
    require(required <= covered_assertions, 'behavior assertions name no scenario (scenario_ids): '
            + ', '.join(p + '/' + a for p, a in sorted(required - covered_assertions)[:8]))
    statics = [p for p in paths.values() if p.get('kind') == 'static']
    require(len(statics) == 1, 'scenario contract requires one static review PATH')
    require(statics[0].get('scenario_ids') in (None, sorted(scenarios)), 'static PATH covers every frozen scenario; omit scenario_ids')
    import unit_reports
    for path in paths.values():
        if path.get('kind') == 'unit':
            unit_reports.plan_check(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Preview the scenario_index the Ledger derives from a staged plan; the plan does not carry it.')
    parser.add_argument('--plan', required=True)
    args = parser.parse_args()
    from contracts import read_json
    try:
        print(json.dumps(scenario_index(read_json(args.plan)), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}), file=sys.stderr)
        sys.exit(2)
