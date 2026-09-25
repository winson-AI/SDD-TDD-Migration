"""Rebuild owned OpenSpec change views from immutable Ledger definition snapshots."""
import hashlib
import json
from pathlib import Path
import re

from contracts import require
import context_links
import project_context
import run_storage


def write(path, text):
    path = run_storage.checked_path(path)
    if path.is_file() and path.read_text() == text:
        return
    run_storage.atomic_bytes(path, text.encode('utf-8'))


def definition(root, ref):
    content = (root / 'artifacts' / ref['sha256']).read_bytes()
    require(hashlib.sha256(content).hexdigest() == ref['sha256'], 'definition snapshot corrupt')
    return content.decode('utf-8')


def attempt(errors, stage, action, module_id=None):
    """A failed view cannot turn a committed event into a rejected operation."""
    try:
        return action()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append({'stage': stage, 'module_id': module_id, 'reason': str(exc),
                       'next_action': 'repair projection storage/ownership; refresh status; continue independently valid actions'})
        return None


def module_view(root, state, sequence, mid, m, targets, context_warnings):
    if not m.get('plan'):
        if m.get('planning_history'):
            change = run_storage.change_root(root, state, mid, claim=True)
            previous = change / 'manifest.json'
            if previous.exists():
                for relative in json.loads(previous.read_text()).get('files', []):
                    candidate = run_storage.checked_path(change / relative, change)
                    candidate.unlink(missing_ok=True)
            status = {'phase': m['phase'], 'freeze_id': None, 'sequence': sequence,
                      'next_action': 'replan-or-review-allocation', 'history_preserved': True}
            write(change / 'status.md', '# Replanning required — previous plan is historical\n\n```json\n' +
                  json.dumps(status, ensure_ascii=False, indent=2) + '\n```\n')
            write(previous, json.dumps({**status, 'run_root': str(root), 'module_id': mid, 'files': ['status.md'],
                  'historical_plan_ref': m['planning_history'][-1]['plan_ref']}, ensure_ascii=False, indent=2) + '\n')
        return
    change = run_storage.change_root(root, state, mid, claim=True)
    manifest = {'sequence': sequence, 'run_root': str(root), 'module_id': mid, 'freeze_id': m['freeze_id'],
                'validation': 'structural-only', 'definitions': m['plan']['definitions'], 'files': []}
    destinations = {**targets, **{str(Path(ref['path']).resolve()): str(change / (
        f"specs/{ref.get('capability', mid.lower())}/spec.md" if ref['kind'] == 'spec' else ref['kind'] + '.md'))
        for ref in m['plan']['definitions'] if ref['kind'] in ('proposal', 'spec', 'design', 'tasks', 'checklist')}}
    manifest['link_warnings'] = list(context_warnings)
    for ref in m['plan']['definitions']:
        kind = ref['kind']
        if kind not in ('proposal', 'spec', 'design', 'tasks', 'checklist'):
            continue
        relative = f"specs/{ref.get('capability', mid.lower())}/spec.md" if kind == 'spec' else kind + '.md'
        text = definition(root, ref)
        text, warnings = context_links.rewrite(text, ref['path'], destinations)
        manifest['link_warnings'].extend(warnings)
        if kind == 'tasks':
            completed = set(m.get('accepted_task_ids', [])) if m.get('code_baseline') else set()
            for task in m['plan']['tasks']:
                tid = task['task_id']
                text = re.sub(r'(?m)^(\s*- )\[[ xX]\](\s+' + re.escape(tid) + r'\b)',
                              lambda match: match[1] + ('[x]' if tid in completed else '[ ]') + match[2], text)
        if kind == 'checklist':
            checks = [('SPEC frozen', bool(m['freeze_id'])), ('Code accepted', bool(m['code_baseline'])),
                      ('All paths Green on current baseline', bool(m['results']) and not m['stale'] and
                       all(r['quality'] == 'green-passed' for r in m['results'].values())),
                      ('DoD accepted', m['phase'] == 'completed')]
            text += '\n\n## Ledger evidence (generated)\n\n' + '\n'.join(
                f"- [{'x' if passed else ' '}] {label}" for label, passed in checks) + '\n'
        write(change / relative, text)
        manifest['files'].append(relative)
    status = {k: m.get(k) for k in ('phase', 'quality', 'stale', 'blocked', 'revision', 'freeze_id', 'code_baseline', 'local_fix_used')}
    status.update(schema_version=1, run_id=state['run_id'], module_id=mid, last_sequence=sequence,
                  execution_status='completed' if m['phase'] == 'completed' else 'suspended' if m['phase'].startswith('waiting-')
                  else 'running' if any(not a.get('closed') for a in m['assignments'].values()) else 'pending',
                  fix_rounds_used=m['fix_rounds_used'], no_progress_rounds=m['no_progress_rounds'],
                  unresolved_paths=[pid for pid, result in m['results'].items() if result['quality'] != 'green-passed'])
    status['effective_quality'] = m.get('effective_quality', m['quality'])
    status.update(sequence=sequence, next_step=state.get('projection_steps', {}).get(mid),
                  audit_resolution=state.get('audit_resolutions', {}).get(mid))
    write(change / 'status.md', '# Ledger status (generated)\n\n```json\n' + json.dumps(status, ensure_ascii=False, indent=2) + '\n```\n')
    write(change / 'memory.md', '# Repair memory (generated)\n\nOnly verified entries may inform a new repair; recheck applicability and current SPEC.\n\n```json\n' +
          json.dumps(m.get('fix_memory', []), ensure_ascii=False, indent=2) + '\n```\n')
    manifest['files'] += ['status.md', 'memory.md']
    if m['plan'].get('reuse_plan_ref'):
        ref = m['plan']['reuse_plan_ref']
        write(change / 'reuse.md', '# Reuse guidance (Ledger plan projection)\n\n' +
              'Executable only after freeze acceptance. Requirements remain the acceptance authority; verify selected provider versions before use.\n\n```json\n' +
              definition(root, ref) + '\n```\n')
        manifest['reuse_plan_ref'] = ref
        manifest['files'].append('reuse.md')
    if m['plan'].get('dimension_analysis_ref'):
        ref = m['plan']['dimension_analysis_ref']
        write(change / 'dimensions.md', '# Dimension coverage (Ledger projection)\n\n' +
              'Analysis order: UI -> Logic -> Adhesive -> Resource. N/A requires source evidence.\n\n```json\n' +
              definition(root, ref) + '\n```\n\n## Task / PATH / ASSERT trace\n\n```json\n' +
              json.dumps(m['plan']['dimension_trace'], ensure_ascii=False, indent=2) + '\n```\n\n## Task scope and dimension analysis\n\n```json\n' +
              json.dumps([{k: task[k] for k in ('task_id', 'scope', 'dimension_analysis')}
                          for task in m['plan']['tasks']], ensure_ascii=False, indent=2) + '\n```\n')
        manifest['dimension_analysis_ref'] = ref
        manifest['files'].append('dimensions.md')
        # Read the immutable archived analysis (not the possibly-removed staging path).
        import semantics
        sem_rows = semantics.models_from_analysis(json.loads(definition(root, ref)))
        if sem_rows:
            write(change / 'semantics.md', '# Semantic extraction (Ledger projection)\n\n' +
                  'Machine-readable UI/Logic/Resource models frozen with the SPEC. Each records result '
                  '(model_ref), source (origin/locator) and target implementation_location.\n\n```json\n' +
                  json.dumps(sem_rows, ensure_ascii=False, indent=2) + '\n```\n')
            manifest['files'].append('semantics.md')
    previous = change / 'manifest.json'
    if previous.exists():
        for obsolete in set(json.loads(previous.read_text()).get('files', [])) - set(manifest['files']):
            candidate = run_storage.checked_path(change / obsolete, change)
            candidate.unlink(missing_ok=True)
    write(previous, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


def materialize(root, state, sequence):
    targets, context_warnings = {}, []
    if state.get('project_context_ref'):
        snapshot = project_context.verify_snapshot(state['project_context_ref'])
        targets, context_warnings = context_links.mapping(snapshot)
    errors = []
    for mid, m in state['modules'].items():
        attempt(errors, 'openspec-module', lambda: module_view(root, state, sequence, mid, m, targets, context_warnings), mid)
    # Global semantic context: aggregate every module's frozen UI/Logic/Resource models and coverage.
    import semantics
    index = {'sequence': sequence, 'models': [], 'coverage': {}}
    for mid, m in state['modules'].items():
        ref = (m.get('plan') or {}).get('dimension_analysis_ref')
        if not ref:
            continue
        try:
            analysis = json.loads(definition(root, ref))
        except (OSError, ValueError, KeyError):
            continue
        index['models'] += semantics.models_from_analysis(analysis, mid)
        coverage = semantics.coverage_from_analysis(analysis)
        if coverage['applicable']:
            index['coverage'][mid] = coverage
    if index['models'] or index['coverage']:
        attempt(errors, 'semantic-index', lambda: write(root / 'ledger/semantic-index.json', json.dumps(index, ensure_ascii=False, indent=2) + '\n'))
    memories = [{'module_id': mid, **entry} for mid, m in state['modules'].items() for entry in m.get('fix_memory', [])]
    attempt(errors, 'repair-memory', lambda: write(root / 'ledger' / 'repair-memory.json', json.dumps({'sequence': sequence, 'entries': memories}, ensure_ascii=False, indent=2) + '\n'))

    if state.get('audit_batch'):
        b = state['audit_batch']
        attempt(errors, 'audit-batch', lambda: write(root / 'ledger/audit-batch.json', json.dumps(b, ensure_ascii=False, indent=2) + '\n'))
        if b.get('human_report'):
            report = json.dumps(b['human_report'], ensure_ascii=False, indent=2)
            attempt(errors, 'audit-report-json', lambda: write(root / 'audit-reports' / (b['batch_id'] + '.json'), report + '\n'))
            attempt(errors, 'audit-report-markdown', lambda: write(root / 'audit-reports' / (b['batch_id'] + '.md'), '# Audit failure — human review required\n\n```json\n' + report + '\n```\n'))

    # GO reads this complete case inventory when reporting the run outcome.
    import migration_report
    report = migration_report.build(root, state, sequence)
    attempt(errors, 'migration-report-json', lambda: write(root / 'reports/migration-report.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n'))
    attempt(errors, 'migration-report-markdown', lambda: write(root / 'reports/migration-report.md', migration_report.render(report)))
    from workflow_hub import materialize as hub
    attempt(errors, 'workflow-hub', lambda: hub(root, state, sequence))
    return errors
