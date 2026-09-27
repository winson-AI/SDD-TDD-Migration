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

import semantics
from contracts import check_ref, file_ref, read_json, require


def ui_evidence(capture_entry, ui_tree_ref):
    """lean capture manifest entry + extracted ui-tree -> SDD semantic_model.ui_evidence."""
    require(isinstance(capture_entry, dict), 'capture entry must be an object')
    page, state, coverage = capture_entry.get('page_id'), capture_entry.get('state_id'), capture_entry.get('coverage')
    require(all(isinstance(x, str) and x for x in (page, state)), 'capture entry needs page_id/state_id')
    require(coverage in ('viewport', 'scroll'), 'capture coverage must be viewport/scroll')
    status = capture_entry.get('status')
    require(status in ('COMPLETE', 'SOURCE_ONLY'), 'capture status must be COMPLETE/SOURCE_ONLY')
    check_ref(ui_tree_ref)
    evidence = {'ui_tree_ref': ui_tree_ref, 'coverage': page + ':' + state + ':' + coverage,
                'visual_mode': 'runtime' if status == 'COMPLETE' else 'source-only'}
    semantics._ui_evidence({'ui_evidence': evidence})  # single source of truth for the gate
    return evidence


def visual_alignment(alignment_result, result_ref):
    """lean alignment-result -> SDD semantic_conformance.visual_alignment (never invents ALIGNED)."""
    check_ref(result_ref)
    status = alignment_result.get('status')
    require(status in ('ALIGNED', 'RUNNABLE_PARTIAL'),
            'alignment not ALIGNED/RUNNABLE_PARTIAL; route NEEDS_UI_FIX back to the owner')
    return {'status': 'aligned' if status == 'ALIGNED' else 'source-only', 'result_ref': result_ref}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    ue = sub.add_parser('ui-evidence', help='capture entry + ui-tree file -> ui_evidence')
    ue.add_argument('--capture', required=True, help='JSON file with page_id/state_id/coverage/status')
    ue.add_argument('--ui-tree', required=True, help='extracted ui-tree.json (file_ref computed here)')
    va = sub.add_parser('visual-alignment', help='alignment-result file -> visual_alignment')
    va.add_argument('--alignment', required=True, help='lean alignment-result.json (file_ref computed here)')
    args = parser.parse_args()
    try:
        if args.command == 'ui-evidence':
            out = ui_evidence(read_json(args.capture), file_ref(Path(args.ui_tree).resolve()))
        else:
            out = visual_alignment(read_json(args.alignment), file_ref(Path(args.alignment).resolve()))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
