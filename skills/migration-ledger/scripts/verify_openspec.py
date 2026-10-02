#!/usr/bin/env python3
"""Read-only Ledger/OpenSpec consistency checks, scoped to the caller's purpose.

A valid hash chain and matching projection establish consistency, not authentication
of Host execution. This checker neither dispatches work nor repairs or rewrites facts.
"""
import argparse
import copy
import json
import re
from pathlib import Path
import sys
sys.dont_write_bytecode = True

import context_links
import decomposition
import dimensions
import ledger
import migration_report
import openspec_projection
import project_context
import run_storage
import workflow_hub
from contracts import Rejected, check_ref, require

ERRORS = (Rejected, OSError, ValueError, KeyError, TypeError, AttributeError)
SCOPES = ('global', 'module', 'projection', 'final')
REFRESH = 'repair projection storage/ownership, then refresh Ledger status; preserve committed events and independent work'
EVIDENCE_RECOVERY = 'restore the referenced immutable artifact from a verified copy/backup; preserve accepted qualities and historical source versions; do not rerun or invent evidence automatically'
REPLAN = 'inspect affected scope and evidence; use existing invalidate/replan or dependency recovery protocol; do not overwrite history'
PARENT_ALLOCATION_KEYS = ('module_id', 'parent_module_id', 'children', 'scope', 'context_refs',
                          'dependencies', 'write_paths', 'decomposition_ref', 'decomposition_review_ref',
                          'dimension_analysis_ref')


def _selected(state, module_id):
    """Current node, ancestors and actual dependencies, never unrelated siblings."""
    nodes = {**state.get('module_groups', {}), **state['modules']}
    require(module_id in nodes, 'unknown module_id')
    selected, pending = set(), [module_id]
    while pending:
        mid = pending.pop()
        if mid in selected:
            continue
        require(mid in nodes, 'allocated parent/dependency missing: ' + str(mid))
        selected.add(mid)
        node = nodes[mid]
        pending.extend(node.get('dependencies', []))
        for dependency in node.get('dependencies', []):
            if dependency in state.get('module_groups', {}):
                pending.extend(decomposition.leaves(state, dependency))
        if node.get('parent_module_id'):
            pending.append(node['parent_module_id'])
    return selected


def _module_sequences(events):
    """A peer-only event need not invalidate an otherwise current module view."""
    previous, sequences = {}, {}
    for event, state, changed in ledger.replay(events):
        for kind in ('modules', 'module_groups'):
            for mid, node in (state.get(kind, {}) if kind in changed else {}).items():
                subject = {k: node.get(k) for k in PARENT_ALLOCATION_KEYS} if kind == 'module_groups' else node
                if previous.get(mid) != subject:
                    sequences[mid] = event['sequence']
                    previous[mid] = subject
    return sequences


class AcceptanceEvidence:
    """Read the current acceptance closure using the event-declared archive index.

    Original paths in a receipt can name an older target version. Immutable archive
    bytes, not today's target contents, are the source for this historical check.
    This does not relax current SPEC/code checks or attest real execution.
    """
    def __init__(self, root, events, target_root):
        self.root = root
        self.target_root = Path(target_root).resolve()
        self.index, self.drifted, self.legacy = {}, set(), set()
        self.resolved, self.walked = {}, set()
        self.legacy_live, self.unarchived_target = set(), set()
        for event in events:
            if 'artifact_snapshots' not in event:
                self.legacy.update((ref['path'], ref['sha256']) for ref in migration_report.refs(event.get('effect', {})))
            snapshots = event.get('artifact_snapshots', [])
            require(isinstance(snapshots, list), 'event artifact index must be a list')
            for item in snapshots:
                require(isinstance(item, dict), 'event artifact index entry must be an object')
                if item.get('source_path') and item.get('sha256'):
                    self.index[(item['source_path'], item['sha256'])] = item
                elif item.get('status') == 'drifted-or-missing-live-target-code':
                    self.drifted.add((item.get('source_path'), item.get('expected_sha256')))

    def check(self, ref):
        require(isinstance(ref, dict) and isinstance(ref.get('path'), str) and Path(ref['path']).is_absolute(),
                'absolute acceptance evidence path required')
        require(isinstance(ref.get('sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', ref['sha256']),
                'acceptance evidence SHA-256 required')
        key = (ref['path'], ref['sha256'])
        if key in self.resolved:
            return self.resolved[key]
        entry = self.index.get(key)
        if entry:
            archive = run_storage.checked_path(self.root / 'artifacts' / ref['sha256'], self.root / 'artifacts')
            require(entry.get('path') == str(archive), 'event artifact location differs from managed archive')
            # An explicitly promised archive must exist, even if live bytes survive.
            path = check_ref({'path': str(archive), 'sha256': ref['sha256']})
        else:
            require(key in self.legacy, 'accepted evidence has no event archive entry: ' + ref['path'])
            path = check_ref(ref)
            self.legacy_live.add(key)
        self.resolved[key] = path
        return path

    def visit(self, value, nested=False):
        for ref in migration_report.refs(value):
            key = (ref['path'], ref['sha256'])
            if key in self.walked:
                continue
            if (nested and key in self.drifted and key not in self.index and
                    Path(ref['path']).resolve().is_relative_to(self.target_root)):
                # Older commits explicitly retained only this historical expectation;
                # it is not a test pass or proof of those missing historical bytes.
                self.unarchived_target.add(key)
                self.walked.add(key)
                continue
            path = self.check(ref)
            self.walked.add(key)
            if Path(ref['path']).suffix == '.json':
                try:
                    document = json.loads(path.read_text())
                except (ValueError, UnicodeDecodeError):
                    continue  # preserve_refs treats non-JSON bytes as an opaque artifact.
                self.visit(document, nested=True)

    def summary(self):
        def rows(items):
            return [{'path': path, 'sha256': sha} for path, sha in sorted(items)]
        return {'checked_refs': len(self.resolved), 'legacy_live_only_refs': rows(self.legacy_live),
                'historical_target_unarchived_refs': rows(self.unarchived_target)}


def _acceptance_roots(state, report):
    """Current CASE/PATH and governance roots; never sweep historical submissions."""
    for row in report['paths']:
        yield row['module_id'], [row['evidence_refs'], row['spec_ref']]
    if state.get('audit', {}).get('report_ref'):
        yield None, state['audit']['report_ref']
    for mid, module in state['modules'].items():
        yield mid, module.get('code_files', [])
    review = state.get('audit_code_review', {})
    yield None, [review.get('report_ref'), review.get('change_inventory_ref'), review.get('evidence_refs', [])]
    for mid, parent in state.get('module_groups', {}).items():
        if parent.get('summary_subject') == decomposition.summary_subject(state, parent):
            yield mid, parent.get('summary_ref')


def inspect(run_root, scope='projection', module_id=None):
    """Inspect existing assets only. verified is not permission to bypass Ledger gates."""
    root = Path(run_root).resolve()
    failures = []
    result = {'run_root': str(root), 'scope': scope, 'module_id': module_id,
              'sequence': None, 'checked_modules': [], 'verified': False, 'failures': failures,
              'next_actions': [], 'limitations': [
                  'Checks committed-record/projection consistency, not authentic Host dispatch or real test execution.',
                  'Does not grant dispatch permission or turn Yellow/unexecuted tests Green.']}

    def fail(code, detail, area='global', mid=None, recovery=REFRESH):
        failures.append({'check': code, 'detail': str(detail), 'scope': area,
                         'module_id': mid, 'recovery_action': recovery})

    def finish():
        result['verified'] = not failures
        result['next_actions'] = list(dict.fromkeys(f['recovery_action'] for f in failures))
        result['next_action'] = result['next_actions'][0] if result['next_actions'] else None
        return result

    def compare(path, expected, code, area='projection', mid=None, structured=False):
        try:
            path = run_storage.checked_path(path)
            actual = path.read_text()
            matches = json.loads(actual) == expected if structured else actual == expected
            if not matches:
                fail(code, 'stale or modified projection: ' + str(path), area, mid)
        except ERRORS as exc:
            fail(code, str(path) + ': ' + str(exc), area, mid)

    if scope not in SCOPES or (scope == 'module' and not module_id) or (scope != 'module' and module_id):
        fail('verification-scope', 'module scope requires module_id; other scopes do not accept it',
             recovery='select global, module + module_id, projection, or final verification')
        return finish()
    try:
        run_storage.checked_path(root)
        require(root.is_dir() and root.parent.name == '.sdd-runs',
                'run root must be <workspace_root>/.sdd-runs/<run_id>')
    except ERRORS as exc:
        fail('managed-layout', exc, recovery='use prepare returned absolute run_root; inspect legacy layout before migration')
        return finish()
    journal = root / 'ledger/events.jsonl'
    try:
        run_storage.checked_path(journal, root)
        require(journal.is_file() and journal.stat().st_size > 0, 'ledger/events.jsonl missing or empty; no committed run is available')
    except ERRORS as exc:
        fail('events-journal', exc, recovery='preserve existing artifacts; inspect backup or initialize a new prepared run; never invent historical events')
        return finish()
    try:
        before_journal = journal.read_bytes()
        state, events = ledger.read_events(root)
        require(state and state['run_id'] == root.name, 'journal state/run identity mismatch')
        require(isinstance(state.get('modules'), dict), 'journal module state missing')
        result['sequence'] = sequence = len(events)
    except ERRORS as exc:
        fail('events-integrity', exc, recovery='stop affected run dispatch; recover the journal from verified backup with Host review; do not reinitialize over it')
        return finish()
    if not (root / 'context/snapshot.json').is_file():
        fail('prepared-snapshot', 'context/snapshot.json missing', recovery='restore prepared snapshot from its verified archive; otherwise preserve run for reviewed recovery')
    if not state.get('project_context_ref'):
        fail('context-bound', 'state has no project_context_ref', recovery='preserve legacy run; bind a new run through prepare and Ledger init; do not rewrite old events')
    try:
        layout = run_storage.for_state(root, state)
        require(layout, 'no prepared storage_layout; cannot resolve top-level openspec')
    except ERRORS as exc:
        fail('storage-layout', exc, recovery='verify context snapshot and OpenSpec owner against archived hashes; restore known owned records; never claim a foreign directory')
        return finish()
    if (root / 'openspec').exists():
        fail('no-fallback-openspec', 'unexpected .sdd-runs/<run_id>/openspec fallback tree present',
             recovery='review and retain legacy fallback assets before controlled migration; do not blindly move or delete them')
    if scope == 'global':
        # The common hub must actually exist. A correct layout declaration alone
        # cannot detect the observed run-without-top-level-OpenSpec failure.
        try:
            hub = Path(layout['hub_root'])
            data = json.loads(run_storage.checked_path(hub / 'workflow.json').read_text())
            identity = {'schema_version': 1, 'run_id': state['run_id'], 'run_root': str(root),
                        'state_authority': str(journal), 'project_context_ref': state['project_context_ref']}
            require(isinstance(data, dict) and all(data.get(k) == v for k, v in identity.items()),
                    'OpenSpec hub identity/context differs from Ledger')
            require(run_storage.checked_path(hub / 'workflow.md').is_file(), 'OpenSpec workflow.md missing')
        except ERRORS as exc:
            fail('workflow-hub', exc)
        if journal.read_bytes() != before_journal:
            fail('events-changed', 'journal changed during verification', recovery='retry read-only verification at the latest sequence')
        return finish()

    try:
        selected = _selected(state, module_id) if scope == 'module' else set(state['modules']) | set(state.get('module_groups', {}))
    except ERRORS as exc:
        fail('module-allocation', exc, 'module', module_id, REPLAN)
        return finish()
    result['checked_modules'] = sorted(selected)
    min_sequences = _module_sequences(events)
    # Use immutable event records for the archive index; read_events' replay state
    # may share the first effect dictionary with later aggregate values.
    evidence = None
    if scope == 'final':
        try:
            evidence = AcceptanceEvidence(root, [json.loads(line) for line in before_journal.splitlines()], state['target_root'])
        except ERRORS as exc:
            fail('acceptance-evidence-index', exc, 'final', recovery=EVIDENCE_RECOVERY)
    ref_check = evidence.check if evidence else check_ref

    # Reproduce status observation in memory. No status() call: it would write views.
    observed_state = copy.deepcopy(state)
    invalid = []
    for mid in selected:
        node = observed_state['modules'].get(mid) or observed_state.get('module_groups', {}).get(mid)
        if scope in ('module', 'final'):
            try:
                dimensions.allocation(observed_state, node)
            except ERRORS as exc:
                fail('module-allocation', exc, 'module', mid, REPLAN)
        m = observed_state['modules'].get(mid)
        if m and m.get('plan'):
            try:
                ledger.current(m, observe_worker=True)
                if scope in ('module', 'final') and m.get('scope'):
                    decomposition.check_assignment(observed_state, m)
            except ERRORS as exc:
                m['effective_quality'] = 'yellow-blocked'
                invalid.append(mid)
                if scope in ('module', 'final'):
                    fail('module-evidence', exc, 'module', mid, REPLAN)
        parent = state.get('module_groups', {}).get(mid)
        if parent and scope in ('module', 'final'):
            try:
                # Only the parent's allocation matters here, not siblings' results.
                decomposition.check_scope(parent)
                for key in ('decomposition_ref', 'decomposition_review_ref'):
                    if parent.get(key):
                        check_ref(parent[key])
            except ERRORS as exc:
                fail('parent-allocation', exc, 'module', mid, REPLAN)
    if scope != 'module':
        decomposition.refresh_groups(observed_state, ref_check)
        compare(root / 'ledger/global.json', {**observed_state, 'last_sequence': sequence,
                'parent_mo_names': decomposition.parent_mo_names(observed_state)}, 'global-state', structured=True)
    expected_state = {**observed_state, 'projection_steps': {
        mid: ledger.next_step(observed_state, observed_state['modules'][mid])
        for mid in selected if mid in observed_state['modules']}}
    try:
        snapshot = project_context.verify_snapshot(state['project_context_ref'])
        targets, warnings = context_links.mapping(snapshot)
    except ERRORS as exc:
        fail('context-links', exc, recovery='restore frozen context/link map from verified archives; do not use mutable input files')
        return finish()

    for mid in sorted(selected):
        node = expected_state['modules'].get(mid) or expected_state.get('module_groups', {}).get(mid)
        path = root / 'ledger/modules' / (mid + '.json')
        try:
            projected = json.loads(run_storage.checked_path(path).read_text())
            node_sequence = projected.get('last_sequence')
            require(type(node_sequence) is int and min_sequences[mid] <= node_sequence <= sequence,
                    'module state projection sequence is stale')
            expected_node = {**node, 'last_sequence': node_sequence if scope == 'module' else sequence}
            if scope == 'module' and mid in state.get('module_groups', {}):
                # A sibling may change summary status without changing this allocation.
                keys = PARENT_ALLOCATION_KEYS
                require(all(projected.get(k) == expected_node.get(k) for k in keys),
                        'parent allocation projection changed')
            else:
                require(projected == expected_node, 'module state projection differs from Ledger facts')
        except ERRORS as exc:
            fail('module-state', str(path) + ': ' + str(exc), 'module', mid)
        m = expected_state['modules'].get(mid)
        if not m or not (m.get('plan') or m.get('planning_history')):
            continue
        change = Path(layout['openspec_root']) / 'changes' / (state['run_id'] + '-' + mid.lower())
        seq = sequence
        if scope == 'module':
            try:
                manifest = json.loads(run_storage.checked_path(change / 'manifest.json').read_text())
                seq = manifest['sequence']
                require(type(seq) is int and min_sequences[mid] <= seq <= sequence,
                        'module projection predates current module facts or comes from a future sequence')
            except ERRORS as exc:
                fail('change-manifest', exc, 'module', mid)
                continue
        rendered = {}
        try:
            openspec_projection.module_view(root, expected_state, seq, mid, m, targets, warnings,
                emit=lambda path, text: rendered.__setitem__(Path(path), text), claim=False)
        except ERRORS as exc:
            fail('change-manifest', exc, 'module', mid)
            continue
        for path, text in rendered.items():
            compare(path, json.loads(text) if path.name == 'manifest.json' else text,
                    'change-manifest' if path.name == 'manifest.json' else 'change-content',
                    'module', mid, structured=path.name == 'manifest.json')

    hub = Path(layout['hub_root'])
    try:
        data = json.loads(run_storage.checked_path(hub / 'workflow.json').read_text())
        require(isinstance(data, dict), 'workflow hub must be an object')
        # Routing is advisory. Validate it with status()'s same pure derivation;
        # paired JSON/Markdown agreement alone cannot establish a valid route.
        hub_state = copy.deepcopy(observed_state)
        if invalid and hub_state['quality'] != 'red-bug':
            hub_state['quality'] = 'yellow-blocked'
        routing = data.get('routing')
        if routing is not None:
            require(isinstance(routing, dict) and isinstance(routing.get('next_steps'), list),
                    'hub routing must be a Ledger status snapshot')
            if scope != 'module':
                require(routing == ledger.routing(observed_state, invalid, ref_check), 'hub routing differs from current Ledger derivation')
            routed = {row['module_id']: row for row in routing['next_steps']}
            for mid in selected.intersection(expected_state['modules']):
                require(routed.get(mid) == expected_state['projection_steps'][mid],
                        'hub module routing stale: ' + mid)
        expected, markdown = workflow_hub.render(root, hub_state, sequence, routing)
        if scope == 'module':
            for key in ('schema_version', 'run_id', 'run_root', 'state_authority', 'project_context_ref'):
                require(data.get(key) == expected[key], 'hub identity/context mismatch: ' + key)
            rows = {row['module_id']: row for row in data['modules']}
            for row in expected['modules']:
                if row['module_id'] in selected:
                    # Parent quality/phase summarize siblings; module dispatch only
                    # needs parent ownership and structural allocation fields.
                    keys = ('module_id', 'kind', 'agent_name', 'parent_module_id', 'children', 'state_path', 'change_path')
                    if row['kind'] == 'leaf':
                        keys += ('phase', 'quality', 'projection_error')
                    require(all(rows.get(row['module_id'], {}).get(k) == row.get(k) for k in keys),
                            'hub module view stale: ' + row['module_id'])
            require((hub / 'workflow.md').is_file(), 'workflow.md missing')
        else:
            compare(hub / 'workflow.json', expected, 'workflow-hub', structured=True)
            actual_md = run_storage.checked_path(hub / 'workflow.md').read_text()
            if actual_md.split('\n## Optional observation\n')[0] != markdown.split('\n## Optional observation\n')[0]:
                fail('workflow-hub', 'stale or modified workflow.md', 'projection')
    except ERRORS as exc:
        fail('workflow-hub', exc, 'module' if scope == 'module' else 'projection', module_id)

    if scope != 'module':
        try:
            report = migration_report.build(root, observed_state, sequence, ref_check)
            compare(root / 'reports/migration-report.json', report, 'migration-report', structured=True)
            compare(root / 'reports/migration-report.md', migration_report.render(report), 'migration-report')
            if evidence:
                for mid, roots in _acceptance_roots(state, report):
                    try:
                        evidence.visit(roots)
                    except ERRORS as exc:
                        fail('acceptance-evidence', exc, 'final', mid, EVIDENCE_RECOVERY)
                result['evidence_verification'] = evidence.summary()
                if evidence.legacy_live:
                    result['limitations'].append('Legacy evidence without an event archive index was checked at its live path; historical recoverability is unverified.')
                if evidence.unarchived_target:
                    result['limitations'].append('Explicit historical target-drift records retain expected hashes only; missing historical target bytes are not claimed as verified evidence.')
            if scope == 'final' and report['report_stage'] not in ('completed', 'completed-with-unverified-tests'):
                fail('delivery-incomplete', 'report_stage=' + report['report_stage'], 'final',
                     recovery='continue Ledger-directed module/audit work or report unresolved human decisions; do not claim completed delivery')
        except ERRORS as exc:
            fail('migration-report', exc)
    if journal.read_bytes() != before_journal:
        fail('events-changed', 'journal changed during verification', recovery='retry read-only verification at the latest sequence')
    return finish()


def verify(run_root, scope='projection', module_id=None):
    """Compatibility API: failures only; planning runs can have current projections."""
    return inspect(run_root, scope, module_id)['failures']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='<workspace_root>/.sdd-runs/<run_id>')
    parser.add_argument('--scope', choices=SCOPES, default='projection')
    parser.add_argument('--module-id')
    args = parser.parse_args()
    result = inspect(args.root, args.scope, args.module_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['verified'] else 1


if __name__ == '__main__':
    sys.exit(main())
