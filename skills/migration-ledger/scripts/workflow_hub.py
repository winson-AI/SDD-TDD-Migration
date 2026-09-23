"""OpenSpec navigation and state view, regenerated only from Ledger facts."""
import json
import os
from pathlib import Path

import run_storage


def location(root, state):
    storage = run_storage.for_state(root, state)
    return Path(storage['hub_root']) if storage else Path(root) / 'openspec'


def materialize(root, state, sequence, routing=None):
    from openspec_projection import write
    base = location(root, state)
    rows = []
    for mid, module in {**state.get('module_groups', {}), **state['modules']}.items():
        parent = mid in state.get('module_groups', {}) or module.get('decomposition_required', False)
        change, error = None, None
        if not parent and (module.get('plan') or module.get('planning_history')):
            try:
                change = str(run_storage.change_root(root, state, mid))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                error = str(exc)
        rows.append({'module_id': mid, 'kind': 'parent' if parent else 'leaf',
            'agent_name': 'parent-mo-' + mid if parent else None,
            'parent_module_id': module.get('parent_module_id'), 'children': module.get('children', []),
            'phase': module.get('phase'), 'quality': module.get('effective_quality', module.get('quality')),
            'state_path': str(root / 'ledger/modules' / (mid + '.json')),
            'change_path': change, 'projection_error': error})
    data = {'schema_version': 1, 'run_id': state['run_id'], 'sequence': sequence,
        'run_root': str(root), 'quality': state['quality'], 'state_authority': str(root / 'ledger/events.jsonl'),
        'project_context_ref': state.get('project_context_ref'), 'modules': rows,
        'migration_report': str(root / 'reports/migration-report.md'),
        'routing_refresh_required': routing is None, 'routing': routing}
    write(base / 'workflow.json', json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    def link(label, path):
        return f'[{label}](<{os.path.relpath(path, base)}>)'
    lines = ['# OpenSpec workflow hub', '', f"Run: `{state['run_id']}` · sequence: {sequence} · quality: {state['quality']}", '',
        'Generated view. Refresh Ledger status before dispatch; transitions use plan / freeze / accept / invalidate events.', '',
        ' · '.join([link('Ledger events', root / 'ledger/events.jsonl'), link('Global state', root / 'ledger/global.json'),
                    link('CASE report', root / 'reports/migration-report.md')]), '',
        '| Module | Role | Phase | Quality | Records |', '| --- | --- | --- | --- | --- |']
    for row in rows:
        links = link('state', row['state_path'])
        if row['change_path']:
            links += ' · ' + link('SPEC/status', Path(row['change_path']) / 'status.md')
        lines.append(f"| {row['module_id']} | {row['agent_name'] or 'leaf MO'} | {row['phase']} | {row['quality']} | {links} |")
    lines += ['', '## Routing', '', 'Run Ledger status to refresh host routing.' if routing is None else
              '```json\n' + json.dumps(routing, ensure_ascii=False, indent=2) + '\n```', '']
    monitoring = root / 'reports/watchdog/latest.json'
    if monitoring.resolve() == monitoring and monitoring.is_file() and not monitoring.is_symlink():
        lines += ['## Optional observation', '', link('Watchdog diagnostics (not business state)', monitoring), '']
    write(base / 'workflow.md', '\n'.join(lines))
    return {'json': str(base / 'workflow.json'), 'markdown': str(base / 'workflow.md')}
