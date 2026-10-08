"""What the Ledger accepted earlier and today's rules would not accept.

An accepted artifact keeps the contract it was accepted under: an allocation is judged when it is registered and, for what
a leaf's freeze asks of it, when the leaf is first frozen on it; a design when it is accepted; a plan when it is submitted
and when it is frozen. Afterwards the run only checks that the artifact is intact. This module does the judging again on
request and reports each difference. The report is for the whole-task Auditor; it is never a gate.
"""
from contracts import Drifted, Rejected, check_ref, read_json, validate_plan

FAILURES = (Rejected, OSError, KeyError, TypeError, ValueError, AttributeError, IndexError)


def collect(s):
    rows = []

    def judge(module_id, artifact, check):
        try:
            check()
        except Drifted:
            pass  # drift is refused where the artifact is used; it is not a difference between rules
        except FAILURES as exc:
            rows.append({'module_id': module_id, 'artifact': artifact, 'reason': str(exc)[:300]})

    import api_contract
    import behavior_contract
    import design_stage
    import dimensions
    import resource_fidelity
    import ui_fidelity

    def allocation(mid, m):
        data, _ = dimensions.judge(m['dimension_analysis_ref'], mid)
        dimensions.coverage_review(data, s.get('planning_coverage_required', False))
        api_contract.applicability(data, True)

    def boundary(m, leaf):
        behavior_contract.review(m, m.get('behavior_review'))
        if leaf:
            behavior_contract.verification(m)

    def design(m):
        record = m['accepted_test_design']
        design_stage.result_check(s, m, m['assignments'][record['assignment_id']], read_json(check_ref(record['result_ref'])))

    def plan(m):
        validate_plan(m['plan'], m)
        if m.get('freeze_id'):
            resource_fidelity.freeze_gate(s, m)
            ui_fidelity.freeze_gate(s, m)

    for mid, m in {**s.get('module_groups', {}), **s['modules']}.items():
        if m.get('dimension_analysis_ref'):
            judge(mid, 'allocation', lambda: allocation(mid, m))
        if s.get('behavior_contract_required'):
            judge(mid, 'allocation-boundary', lambda: boundary(m, mid in s['modules']))
    graph = {mid: m.get('dependencies', []) for mid, m in s['modules'].items()}
    for gid, group in s.get('module_groups', {}).items():
        children = [s['modules'][cid] for cid in group.get('children', []) if cid in s['modules']]
        if any(child.get('behavior_review') for child in children):
            judge(gid, 'split', lambda: behavior_contract.independence(
                group, children, graph, read_json(check_ref(group['decomposition_ref']))))
    for mid, m in s['modules'].items():
        if design_stage.required(s, m) and m.get('accepted_test_design'):
            judge(mid, 'test-design', lambda: design(m))
        if m.get('plan'):
            judge(mid, 'plan', lambda: plan(m))
    if s.get('planning_coverage_required'):
        # What a new registration or a new plan is asked today: how the target takes resources, where a user-visible
        # case is verified, and a device or visual path for each such case.
        import project_context
        import user_paths
        applicable = set()
        for m in {**s.get('module_groups', {}), **s['modules']}.values():
            try:
                applicable.update(row['dimension'] for row in read_json(check_ref(m['dimension_analysis_ref']))['dimensions']
                                  if row.get('status') == 'applicable')
            except FAILURES:
                pass
        judge('RUN', 'project-context', lambda: project_context.transfer_settled(s, applicable))
        judge('RUN', 'project-context', lambda: project_context.device_settled(s, applicable))
        for mid, m in s['modules'].items():
            if m.get('plan'):
                judge(mid, 'plan', lambda: user_paths.plan_gate(m, m['plan']))
    return rows
