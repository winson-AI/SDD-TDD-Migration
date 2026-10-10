"""A leaf that has its four-dimension specification plans with the minimal set.

What a plan repeats from the allocation the Ledger already accepted (the analysis and the behaviour review of the
leaf) is filled in when the plan is submitted: the understanding of the source, the feasibility on the target, the
approved boundary, each task's share of the four dimensions and which tasks a scenario belongs to. An author writes
one of these only to say something the allocation does not, and what is written is judged as before. The completed
plan is the one the Ledger stores, hashes and freezes, so no gate reads less than it did."""
import copy

from contracts import Rejected


def unique(values):
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def complete(s, m, plan):
    import dimensions
    ref = m.get('dimension_analysis_ref')
    if not ref or not isinstance(plan, dict):
        return plan  # no four-dimension specification: nothing follows from it
    own = plan.get('dimension_analysis_ref', ref)
    if own != ref and not dimensions.refines(ref, own):
        return plan  # a plan bound to another analysis: the gates refuse it
    ref = own  # the leaf's refinement of its allocation says everything the allocation says
    try:
        analysis, items = dimensions.load(ref, m['module_id'])
    except (Rejected, OSError):
        return plan  # the gates report an analysis that cannot be read
    plan['dimension_analysis_ref'] = copy.deepcopy(ref)
    evidence = unique(ref for item in items.values() for ref in item.get('evidence_refs') or [])
    accepted = unique(item.get('acceptance') for item in items.values())
    locators = unique(item.get('source_locator') for item in items.values())
    closure = plan.setdefault('source_closure', {})
    if isinstance(closure, dict) and locators:
        boundary, own = (m.get('behavior_review') or {}).get('verification'), closure.get('verification')
        if isinstance(boundary, dict) and isinstance(own, dict):
            # An author states what the allocation left to the leaf - its fixture; the rest is the allocation's.
            own.update({key: copy.deepcopy(value) for key, value in boundary.items() if own.get(key) is None})
        for key, value in {**copy.deepcopy(m.get('behavior_review') or {}), 'execution_chain': locators}.items():
            closure.setdefault(key, value)
        closure.setdefault('entry', locators[0])
        closure.setdefault('observable_result', '; '.join(accepted))
        closure.setdefault('production_binding', '; '.join(unique(item['target_binding'] for item in items.values() if item.get('target_binding'))))
        closure.setdefault('evidence_refs', copy.deepcopy(evidence))
        closure.setdefault('unresolved', [])
    target = (analysis.get('source_reviews') or {}).get('target') or {}
    if 'target_feasibility' not in plan and analysis.get('unresolved') == [] and target.get('evidence_refs'):
        plan['target_feasibility'] = {'verdict': 'ready', 'evidence_refs': copy.deepcopy(target['evidence_refs'])}
    envelope = plan.setdefault('decision_envelope', {})
    if isinstance(envelope, dict):
        for key, value in (('scope', list((m.get('scope') or {}).get('in') or [])), ('acceptance', accepted),
                           ('allowed_alternatives', []), ('forbidden_changes', ['scope-reduction', 'provider-substitution'])):
            envelope.setdefault(key, value)
    traces = {row.get('item_id'): row for row in plan.get('dimension_trace') or [] if isinstance(row, dict)}
    allocated = {row.get('dimension'): row for row in analysis.get('dimensions', [])}
    for task in plan.get('tasks') or []:
        if not isinstance(task, dict) or 'dimension_analysis' in task:
            continue
        rows = []
        for dimension in dimensions.ORDER:
            owned = sorted(iid for iid, trace in traces.items() if iid in items and items[iid]['dimension'] == dimension
                           and task.get('task_id') in (trace.get('task_ids') or []))
            row = allocated.get(dimension) or {}
            rows.append({'dimension': dimension, 'status': 'applicable' if owned else 'not-applicable', 'item_ids': owned,
                         'reason': row.get('reason') if owned or row.get('status') != 'applicable'
                         else 'no item of this dimension is traced to this task',
                         **({'implementation': '; '.join(f"{iid}: {items[iid]['target_strategy']} -> {items[iid].get('target_binding') or 'to be settled by the leaf'}"
                                                         for iid in owned)} if owned else {})})
        task['dimension_analysis'] = {'unresolved': [], 'dimensions': rows}
    if (s.get('behavior_contract_required') or plan.get('behavior_contract_required')) and 'scenario_trace' not in plan:
        import behavior_contract
        try:
            scenarios, found = behavior_contract.scenario_index(plan), behavior_contract.tagged(plan)
        except (Rejected, OSError, KeyError, TypeError):
            return plan  # the scenario contract reports a SPEC it cannot index
        plan['scenario_trace'] = [{'scenario_id': row['scenario_id'], 'task_ids': sorted(
            task['task_id'] for task in plan.get('tasks') or []
            if row['requirement_id'] in task.get('requirement_ids', [])
            and any(pid in task.get('path_ids', []) for pid, _ in found.get(row['scenario_id'], [])))} for row in scenarios]
    return plan
