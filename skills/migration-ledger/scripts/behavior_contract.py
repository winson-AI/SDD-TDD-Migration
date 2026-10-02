"""Behavior closure and OpenSpec-derived scenario coverage.

These checks validate the review's structure and references, not business semantics.
Prepared runs always enable the contract; `behavior_contract_required` is off only in low-level fixtures.
"""
import argparse
import json
import re
import sys
sys.dont_write_bytecode = True

from contracts import check_ref, digest, keyed, nonempty, require


def review(module, value):
    require(isinstance(value, dict), 'behavior_review required')
    require(value.get('scope_sha256') == digest(module.get('scope')), 'behavior review scope mismatch')
    for field in ('entry', 'observable_result', 'production_binding', 'boundary_rationale'):
        require(isinstance(value.get(field), str) and value[field].strip(), 'behavior review missing ' + field)
    for field, expected in (('requirement_ids', module.get('scope', {}).get('requirement_ids', [])),
                            ('case_ids', module.get('case_ids', []))):
        values = nonempty(value.get(field), 'behavior review ' + field)
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
    """Full allocation checks only at global acceptance, never during sibling dispatch."""
    if not state.get('behavior_contract_required'):
        return
    modules = {**state.get('module_groups', {}), **state['modules']}
    owners = {}
    for module in modules.values():
        value = module.get('behavior_review')
        review(module, value)
        for row in value['shared_capabilities']:
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
    covered_tasks, covered_assertions = set(), set()
    for sid, trace in traces.items():
        rid = scenarios[sid]['requirement_id']
        tids = set(nonempty(trace.get('task_ids'), 'scenario task coverage'))
        require(tids <= set(tasks) and all(rid in tasks[t]['requirement_ids'] for t in tids), 'scenario task/requirement mismatch')
        covered_tasks.update(tids)
        linked_paths = {pid for tid in tids for pid in tasks[tid]['path_ids']}
        for item in nonempty(trace.get('assertions'), 'scenario behavior assertions'):
            pid, aid = item.get('path_id'), item.get('assertion_id')
            require(pid in linked_paths and pid in paths, 'scenario assertion outside task paths')
            path = paths[pid]
            require(path.get('kind', 'automation') in ('unit', 'automation', 'visual'), 'build/static cannot prove scenario behavior')
            require(rid == path.get('requirement_id') or rid in path.get('requirement_ids', []), 'scenario path/requirement mismatch')
            require(path['case_id'] in module['case_ids'], 'scenario case outside module')
            require(aid in {a['assertion_id'] for a in path['expected_assertions']}, 'unknown scenario assertion')
            covered_assertions.add((pid, aid))
    require(covered_tasks == set(tasks), 'every task must contribute to a scenario, including supporting tasks')
    required = {(p['path_id'], a['assertion_id']) for p in paths.values()
                if p.get('kind', 'automation') in ('unit', 'automation', 'visual') for a in p['expected_assertions']}
    require(required <= covered_assertions, 'behavior assertions missing scenario trace')
    statics = [p for p in paths.values() if p.get('kind') == 'static']
    require(len(statics) == 1, 'scenario contract requires one static review PATH')
    require(statics[0].get('scenario_ids') in (None, sorted(scenarios)), 'static PATH covers every frozen scenario; omit scenario_ids')
    import unit_reports
    for path in paths.values():
        if path.get('kind') == 'unit':
            unit_reports.plan_check(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Print the derived scenario_index for a staged plan; store it in that plan before approval.')
    parser.add_argument('--plan', required=True)
    args = parser.parse_args()
    from contracts import read_json
    try:
        print(json.dumps(scenario_index(read_json(args.plan)), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}), file=sys.stderr)
        sys.exit(2)
