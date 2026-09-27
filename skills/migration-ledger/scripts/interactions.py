"""Gesture contract absorbed from the lean Spec/Aligner: a declared interaction needs device proof.

Only gestures the frozen Spec explicitly declares exist — they are never inferred from navigation
stacks, screenshots or source handlers. Each names its starting page/state, exact action modality,
expected destination (or app exit) and foreground expectation. Every declared interaction must carry
one PASSED check bound to the same HAP that was visually aligned; static route inspection never
substitutes for that runtime evidence.
"""
import re

from contracts import check_ref, require

ID = re.compile(r'^[a-z0-9][a-z0-9-]*$')


def validate_declarations(model):
    declared = model.get('interactions')
    if declared is None:
        return []
    require(isinstance(declared, list), 'interactions must be a list')
    seen = []
    for item in declared:
        require(isinstance(item, dict) and ID.match(str(item.get('id', ''))),
                'interaction needs a stable lowercase id')
        require(item['id'] not in seen, 'duplicate interaction id ' + item['id'])
        seen.append(item['id'])
        require(item.get('action'), 'interaction ' + item['id'] + ' needs an exact action modality')
        start = item.get('from') or {}
        require(start.get('page_id') and start.get('state_id'),
                'interaction ' + item['id'] + ' needs a starting page/state')
        expected = item.get('expected') or {}
        require(isinstance(expected.get('app_foreground'), bool),
                'interaction ' + item['id'] + ' needs expected app_foreground')
        require(expected['app_foreground'] is False or (expected.get('page_id') and expected.get('state_id')),
                'interaction ' + item['id'] + ' needs an expected page/state unless the app exits')
    return seen


def validate_checks(declared_ids, alignment):
    """Every declared gesture has a PASSED check against the aligned HAP."""
    if not declared_ids:
        return
    checks = {c.get('id'): c for c in (alignment or {}).get('interaction_checks', []) if isinstance(c, dict)}
    missing = sorted(set(declared_ids) - set(checks))
    require(not missing, 'declared interactions lack device checks: ' + ', '.join(missing))
    hap = (alignment or {}).get('hap_sha256')
    require(hap, 'interaction checks require the aligned hap_sha256')
    for iid in declared_ids:
        check = checks[iid]
        require(check.get('status') == 'PASSED', 'interaction check not PASSED: ' + iid)
        require(check.get('hap_sha256') == hap, 'interaction check must bind the aligned HAP: ' + iid)
        check_ref(check.get('evidence_ref'))
