"""Bounded views over the full Ledger status, for hosts that poll after every event.

The full status grows with the number of modules and stays on disk as projections; a host
deciding its next dispatch needs the cursor, and the one module it is about to act on.
Reading cards are listed once per distinct card and steps refer to them by digest.
"""
import reading

CURSOR_KEYS = ('run_id', 'last_sequence', 'quality', 'projection', 'source_change_next_step', 'global_next_step',
               'next_steps', 'ready_modules', 'module_rounds', 'observed_invalidations', 'parent_mo_names',
               'openspec_binding', 'migration_report', 'run_root')
VIEWS = ('full', 'cursor', 'module')


def _strip(value):
    """Remove embedded reading cards (signal evidence repeats whole steps)."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != 'must_read'}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _slim(step, cards):
    step = dict(step)
    rows = step.pop('must_read', None)
    if rows is not None:
        sha = step.get('card_sha256') or reading.digest_card(rows)
        cards.setdefault(sha, rows)
        step['card_sha256'] = sha
    return step


def _cursor(st, cards):
    out = {k: st[k] for k in CURSOR_KEYS if k in st}
    out['next_steps'] = [_slim(x, cards) for x in st['next_steps']]
    out['global_next_step'] = _slim(st['global_next_step'], cards)
    out['workflow_progress'] = _strip(st['workflow_progress'])
    out['module_summary'] = {mid: {'phase': m['phase'], 'quality': m.get('effective_quality') or m['quality'],
                                   'blocked': (m.get('blocked') or {}).get('reason_code')}
                             for mid, m in st['modules'].items()}
    adoption = st['hint_adoption']
    out['hint_adoption'] = {k: adoption[k] for k in ('session', 'card')}
    return out


def select(st, view='full', module_id=None):
    if view == 'full':
        return st
    if view not in VIEWS:
        raise ValueError('unknown status view: ' + str(view))
    cards = {}
    out = _cursor(st, cards)
    out['view'] = view
    if view == 'module':
        if module_id not in st['modules'] and module_id not in st['module_inputs']:
            raise ValueError('unknown module for status view: ' + str(module_id))
        out['next_steps'] = [x for x in out['next_steps'] if x.get('module_id') == module_id]
        out['module'] = st['modules'].get(module_id) or st.get('module_groups', {}).get(module_id)
        out['module_input'] = st['module_inputs'].get(module_id)
        rounds = st['module_rounds']
        out['module_rounds'] = {'all_settled': rounds['all_settled'],
                                'blockers': [b for b in rounds['blockers'] if b.get('module_id') == module_id]}
    out['cards'] = {sha: rows for sha, rows in cards.items()
                    if sha in {x.get('card_sha256') for x in out['next_steps'] + [out['global_next_step']]}}
    return out
