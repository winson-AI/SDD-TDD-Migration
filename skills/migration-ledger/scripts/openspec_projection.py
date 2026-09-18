"""Rebuild owned OpenSpec change views from immutable Ledger definition snapshots."""
import hashlib
import json
import os
from pathlib import Path
import re

from contracts import require


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w') as stream:
        stream.write(text); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)


def definition(root, ref):
    content = (root / 'artifacts' / ref['sha256']).read_bytes()
    require(hashlib.sha256(content).hexdigest() == ref['sha256'], 'definition snapshot corrupt')
    return content.decode('utf-8')


def materialize(root, state, sequence):
    for mid, m in state['modules'].items():
        if not m.get('plan'):
            continue
        change = root / 'openspec' / 'changes' / f"{state['run_id']}-{mid.lower()}"
        manifest = {'sequence': sequence, 'module_id': mid, 'freeze_id': m['freeze_id'],
                    'validation': 'structural-only', 'definitions': m['plan']['definitions'], 'files': []}
        for ref in m['plan']['definitions']:
            kind = ref['kind']
            if kind not in ('proposal', 'spec', 'design', 'tasks', 'checklist'):
                continue
            relative = f"specs/{ref.get('capability', mid.lower())}/spec.md" if kind == 'spec' else kind + '.md'
            text = definition(root, ref)
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
        previous = change / 'manifest.json'
        if previous.exists():
            for obsolete in set(json.loads(previous.read_text()).get('files', [])) - set(manifest['files']):
                candidate = (change / obsolete).resolve()
                require(candidate.is_relative_to(change.resolve()), 'invalid projection manifest path')
                candidate.unlink(missing_ok=True)
        write(previous, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    memories = [{'module_id': mid, **entry} for mid, m in state['modules'].items() for entry in m.get('fix_memory', [])]
    write(root / 'ledger' / 'repair-memory.json', json.dumps({'sequence': sequence, 'entries': memories}, ensure_ascii=False, indent=2) + '\n')

    if state.get('audit_batch'):
        b = state['audit_batch']
        write(root / 'ledger/audit-batch.json', json.dumps(b, ensure_ascii=False, indent=2) + '\n')
        if b.get('human_report'):
            report = json.dumps(b['human_report'], ensure_ascii=False, indent=2)
            write(root / 'audit-reports' / (b['batch_id'] + '.json'), report + '\n')
            write(root / 'audit-reports' / (b['batch_id'] + '.md'), '# Audit failure — human review required\n\n```json\n' + report + '\n```\n')
