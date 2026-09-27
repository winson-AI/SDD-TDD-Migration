#!/usr/bin/env python3
"""Map lean skill outputs into SDD evidence shapes, so the mapped lean skills act as SDD
workers (see lean-integration.md). The host dispatches the lean skill, then converts its
result here before submitting to the Ledger. Conversion is structural and produces exactly
the shapes semantics.py validates; it never fabricates evidence or an ALIGNED verdict.
"""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

import ui_evidence as ue
import semantics
from contracts import check_ref, file_ref, nonempty, read_json, require


def ui_evidence(capture_entry, ui_tree_ref):
    """lean capture manifest entry + extracted ui-tree -> SDD semantic_model.ui_evidence."""
    ue.validate_capture(capture_entry)
    page, state, coverage = capture_entry['page_id'], capture_entry['state_id'], capture_entry['coverage']
    status = capture_entry['status']
    check_ref(ui_tree_ref)
    evidence = {'ui_tree_ref': ui_tree_ref, 'coverage': page + ':' + state + ':' + coverage,
                'visual_mode': 'runtime' if status == 'COMPLETE' else 'source-only'}
    semantics._ui_evidence({'ui_evidence': evidence})  # single source of truth for the gate
    return evidence


VISUAL_QUALITY = {'ALIGNED': 'green-passed', 'ALIGNED_CARRIED': 'green-passed',
                  'NEEDS_UI_FIX': 'red-bug', 'NEEDS_IMPLEMENTATION_FIX': 'red-bug',
                  'CAPTURE_BLOCKED': 'yellow-blocked'}


def visual_results(alignment_result, declared_interactions=()):
    """lean alignment-result -> three-state rows for the visual test stage, keyed page:state:coverage.

    The visual stage is an ordinary test layer, so an unaligned target is a Red with a node-level root
    cause rather than a separate verdict. Declared gestures must carry PASSED device evidence bound to
    the aligned HAP. Nothing here invents a pass.
    """
    rows = {}
    for target in nonempty(alignment_result.get('target_results'), 'alignment target_results'):
        status = target.get('status')
        require(status in VISUAL_QUALITY, 'unknown alignment target status: ' + str(status))
        key = '{}:{}:{}'.format(target.get('page_id'), target.get('state_id'), target.get('coverage'))
        check_ref(target.get('evidence_ref'))
        row = {'quality': VISUAL_QUALITY[status], 'alignment_status': status,
               'evidence_ref': target['evidence_ref'], 'nodes': list(target.get('node_ids', []))}
        if row['quality'] != 'green-passed':
            row['root_cause'] = target.get('root_cause') or {
                'category': 'capture-environment' if status == 'CAPTURE_BLOCKED' else 'visual-alignment',
                'summary': status + ' at ' + key, 'confidence': 'confirmed',
                'owner': target.get('owner', 'lean'),
                'next_action': 'repair the named nodes, or restore capture evidence'}
        rows[key] = row
    ue.validate_interaction_checks(list(declared_interactions), alignment_result)
    return rows


def validation_summary(validation_result):
    """lean validation-result -> SDD three-state hint plus verified build artifacts (e.g. HAP).

    Artifact refs are hash-checked against the current files, so a recorded HAP must still be the
    one that was validated; a passed package check without its artifact is not accepted.
    """
    checks = nonempty(validation_result.get('checks'), 'validation checks')
    kinds = set()
    for check in checks:
        require(isinstance(check, dict) and check.get('kind'), 'validation check needs a kind')
        require(check.get('status') in ('passed', 'failed'), 'validation check status must be passed/failed')
        kinds.add(check['kind'])
    artifacts = [str(check_ref(ref)) for ref in validation_result.get('artifacts', [])]
    require('package' not in kinds or artifacts, 'a package check must record its built artifact (HAP)')
    failed = sorted({check['kind'] for check in checks if check['status'] == 'failed'})
    return {'quality': 'red-bug' if failed else 'green-passed', 'failed_checks': failed,
            'artifacts': artifacts, 'verdict': validation_result.get('verdict')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p_ui = sub.add_parser('ui-evidence', help='capture entry + ui-tree file -> ui_evidence')
    p_ui.add_argument('--capture', required=True, help='JSON file with page_id/state_id/coverage/status')
    p_ui.add_argument('--ui-tree', required=True, help='extracted ui-tree.json (file_ref computed here)')
    p_visual = sub.add_parser('visual-results', help='alignment-result file -> visual-stage three-state rows')
    p_visual.add_argument('--alignment', required=True, help='lean alignment-result.json')
    p_visual.add_argument('--interaction', action='append', default=[], help='declared interaction id (repeatable)')
    args = parser.parse_args()
    try:
        if args.command == 'ui-evidence':
            out = ui_evidence(read_json(args.capture), file_ref(Path(args.ui_tree).resolve()))
        else:
            out = visual_results(read_json(args.alignment), args.interaction)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
