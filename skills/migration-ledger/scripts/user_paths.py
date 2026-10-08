"""A case the user sees is verified where the user sees it: on a device or on the rendered screen."""
from contracts import check_ref, keyed, nonempty, read_json, require

DEVICE_PLATFORMS = ('android', 'harmony')


def on_device(path):
    """A path that drives or observes the running target: a visual path, a device interaction, or automation bound to
    a device platform. Any other automation runs inside a process and shows what the code returns, not the screen."""
    return path.get('kind') == 'visual' or path.get('kind', 'automation') == 'automation' and (
        path.get('platform') in DEVICE_PLATFORMS or bool(path.get('interaction_id')))


def visible_cases(module, analysis):
    """The cases this leaf accepts whose behaviour an applicable UI item of its allocation carries."""
    import behavior_contract
    shown = {cid for row in analysis.get('dimensions', []) if row.get('dimension') == 'UI' and row.get('status') == 'applicable'
             for item in row.get('items', []) for cid in item.get('case_ids', [])}
    return shown.intersection(behavior_contract.accepts(module))


def gaps(plan):
    """Cases a plan declares it cannot verify on a device or a rendered screen, with the stated reason."""
    return {row['case_id']: row for row in (plan or {}).get('device_gaps') or [] if isinstance(row, dict) and row.get('case_id')}


def plan_gate(module, plan):
    """Every user-visible case the leaf accepts has a device or visual path. A case that cannot have one is declared,
    with the reason and its evidence: the gap is reported and the case is not counted as fully verified."""
    ref = plan.get('dimension_analysis_ref')
    if not ref:
        return
    visible = visible_cases(module, read_json(check_ref(ref)))
    covered = {path['case_id'] for path in plan['paths'] if on_device(path)}
    declared = plan.get('device_gaps') or []
    require(isinstance(declared, list), 'device_gaps must be a list')
    declared = keyed(declared, 'case_id') if declared else {}
    require(set(declared) <= visible - covered,
            'device_gaps names a case that is not user-visible in this leaf or that a device or visual path already verifies')
    for gap in declared.values():
        require(isinstance(gap.get('reason'), str) and gap['reason'].strip(),
                'a device gap states why no device or visual path can verify the case')
        for evidence in nonempty(gap.get('evidence_refs'), 'device gap evidence'):
            check_ref(evidence)
    missing = sorted(visible - covered - set(declared))
    require(not missing, 'a user-visible case needs a device or visual path, or a declared device gap: ' + ', '.join(missing))
