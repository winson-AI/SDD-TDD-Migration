#!/usr/bin/env python3
"""Fail-closed closure gate: prove a finished run really produced its OpenSpec projection.

A hand-written run can look complete on disk (staging files, a prose report, even a
stub ``openspec`` folder) yet never went through the Ledger. OpenSpec is a projection,
not a file to be authored by hand, so the only reliable proof is that the transactional
pipeline actually ran and bound a prepared storage layout:

    prepare -> ledger init(project_context_ref) -> apply  =>  top-level workspace/openspec

This gate turns that silent bypass into an explicit failure. It never mutates the run;
it only reads committed facts and the projected views. Exit 0 means verified, 1 means the
run is NOT complete regardless of what its own report claims.
"""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

import ledger
import run_storage
from contracts import Rejected


def verify(run_root):
    """Return failed checks (empty == the OpenSpec projection is real and complete)."""
    failures = []

    def fail(code, detail):
        failures.append({'check': code, 'detail': detail})

    root = Path(run_root).resolve()
    if not (root.is_dir() and root.parent.name == '.sdd-runs'):
        fail('managed-layout', 'run root must be <workspace_root>/.sdd-runs/<run_id>')
        return failures  # nothing else is meaningful off the managed layout
    run_id = root.name
    workspace = root.parent.parent

    # 1. The sole source of truth. No journal means the Ledger controller never ran,
    #    so every other artifact (registry, report, openspec stub) was authored by hand.
    journal = root / 'ledger' / 'events.jsonl'
    if not (journal.is_file() and journal.stat().st_size > 0):
        fail('events-journal', 'ledger/events.jsonl missing or empty; Ledger controller never ran')
        return failures
    try:
        state, _ = ledger.read_events(root)
    except (Rejected, OSError, ValueError, KeyError) as exc:
        fail('events-integrity', str(exc))
        return failures
    if not state:
        fail('events-state', 'journal produced no state')
        return failures

    # 2. Prepared storage binding is what sends OpenSpec to the top level instead of the
    #    in-run fallback. Missing binding => openspec silently landed inside the run.
    if not (root / 'context' / 'snapshot.json').is_file():
        fail('prepared-snapshot', 'context/snapshot.json missing; run was not prepared')
    if not state.get('project_context_ref'):
        fail('context-bound', 'state has no project_context_ref; OpenSpec falls back inside the run')
    layout = None
    try:
        layout = run_storage.for_state(root, state)
    except (Rejected, OSError, ValueError, KeyError) as exc:
        fail('storage-layout', str(exc))
    if not layout:
        fail('storage-layout', 'no prepared storage_layout; cannot resolve top-level openspec')
        return failures

    # 3. The projected navigation hub must exist at the top level, and no in-run fallback
    #    tree should remain (its presence signals an earlier unprepared/bypassed run).
    openspec_root = Path(layout['openspec_root'])
    hub = Path(layout['hub_root'])
    if not ((hub / 'workflow.json').is_file() and (hub / 'workflow.md').is_file()):
        fail('workflow-hub', 'top-level openspec/runs/<run_id>/workflow.{json,md} missing')
    if (root / 'openspec').exists():
        fail('no-fallback-openspec', 'unexpected .sdd-runs/<run_id>/openspec fallback tree present')

    # 4. Every leaf that authored a plan must have a projected change with a manifest.
    #    manifest.json is the projection engine's signature; a hand-made change dir lacks it.
    for mid, module in state.get('modules', {}).items():
        if module.get('decomposition_required'):
            continue  # decomposition roots project through their child leaves
        if not (module.get('plan') or module.get('planning_history')):
            continue
        manifest = openspec_root / 'changes' / (run_id + '-' + mid.lower()) / 'manifest.json'
        if not manifest.is_file():
            fail('change-manifest', 'missing OpenSpec projection manifest for ' + mid)
            continue
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            fail('change-manifest', 'unreadable OpenSpec manifest for ' + mid)
            continue
        if not (isinstance(data, dict) and data.get('run_root') == str(root) and data.get('module_id') == mid):
            fail('change-manifest', 'OpenSpec manifest ownership mismatch for ' + mid)

    # 5. The GO migration report must be the Ledger projection (structured JSON the
    #    projection always emits), not a hand-written prose .md standing in for it.
    report_json = root / 'reports' / 'migration-report.json'
    if not report_json.is_file():
        fail('migration-report', 'reports/migration-report.json missing; report was not projected from the Ledger')
    else:
        try:
            data = json.loads(report_json.read_text())
        except (OSError, ValueError):
            data = None
        if not (isinstance(data, dict) and data.get('schema_version') == 1 and data.get('run_id') == run_id
                and isinstance(data.get('cases'), list) and isinstance(data.get('paths'), list) and data.get('report_stage')):
            fail('migration-report', 'migration-report.json is not a valid Ledger projection')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='run root: <workspace_root>/.sdd-runs/<run_id>')
    args = parser.parse_args()
    failures = verify(args.root)
    result = {'run_root': str(Path(args.root).resolve()), 'verified': not failures, 'failures': failures,
              'next_action': None if not failures else
              'run prepare -> ledger init(project_context_ref) -> apply; a hand-written run is not complete'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
