"""Bounded views over the full Ledger status, for hosts that poll after every event.

The full status grows with the number of modules and stays on disk as projections; a host
deciding its next dispatch needs the cursor, and the one module it is about to act on. A role
acting on a step needs that step, the readiness requirement of its stage and its own allocation,
not the other modules. Steps refer to their reading card by digest; the card's rows come from
`reading.py render` (or the full view), so a poll carries only the card's size. A poll that passes
the sequence it already saw gets a brief answer while nothing has changed.
"""
import reading

CURSOR_KEYS = ('run_id', 'last_sequence', 'quality', 'projection', 'source_change_next_step', 'global_next_step',
               'next_steps', 'ready_modules', 'module_rounds', 'observed_invalidations')
VIEWS = ('full', 'cursor', 'module', 'step')
# What a role needs of its module and of the assignment its step refers to.
MODULE_KEYS = ('phase', 'plan_ref', 'freeze_id', 'code_baseline', 'blocked')
ASSIGNMENT_KEYS = ('assignment_id', 'role', 'instance_id', 'fencing_token', 'mode', 'test_scope', 'freeze_id',
                   'code_baseline', 'context_ref', 'design_input_ref')


def _attention(progress):
    """Signals and worker watches without their evidence; the evidence stays in the full view and the reports."""
    return {'state': progress.get('state'), 'notify_user': progress.get('notify_user'),
            'signals': [{k: x.get(k) for k in ('module_id', 'reason', 'severity', 'owner', 'next_action')}
                        for x in progress.get('signals', [])],
            'runnable_actions': progress.get('runnable_actions', []),
            'worker_watches': [{k: x.get(k) for k in ('module_id', 'assignment_id', 'idle_seconds', 'timeout_seconds')}
                               for x in progress.get('worker_watches', [])],
            'report_path': progress.get('report_path')}


def _slim(step, cards):
    step = dict(step)
    rows = step.pop('must_read', None)
    if rows is not None:
        sha = step.get('card_sha256') or reading.digest_card(rows)
        cards.setdefault(sha, reading.summary(rows))
        step['card_sha256'] = sha
    fresh = step.pop('must_read_new', None)
    if fresh is not None:
        step['card_new'] = reading.summary(fresh)
    return step


def _cursor(st, cards):
    out = {k: st[k] for k in CURSOR_KEYS if k in st}
    out['next_steps'] = [_slim(x, cards) for x in st['next_steps']]
    out['global_next_step'] = _slim(st['global_next_step'], cards)
    out['workflow_progress'] = _attention(st['workflow_progress'])
    out['module_summary'] = {mid: {'phase': m['phase'], 'quality': m.get('effective_quality') or m['quality'],
                                   'blocked': (m.get('blocked') or {}).get('reason_code')}
                             for mid, m in st['modules'].items()}
    adoption = st['hint_adoption']
    out['hint_adoption'] = {k: adoption[k] for k in ('session', 'card')}
    return out


def _step(st, module_id):
    """The state one role needs to act on the current step of a module (or on the global step)."""
    if module_id is None:
        step, revision = st['global_next_step'], st['revision']
    else:
        step = next((x for x in st['next_steps'] if x.get('module_id') == module_id), None)
        if step is None:
            raise ValueError('unknown module for status view: ' + str(module_id))
        revision = step['expected_revision']
    cards = {}
    slim = _slim(step, cards)
    operation = step.get('operation')
    out = {'view': 'step', 'run_id': st['run_id'], 'last_sequence': st['last_sequence'], 'step': slim, 'cards': cards,
           # The envelope of the request this step asks for; the worker of a running assignment submits its result.
           'request': {'schema_version': 1, 'run_id': st['run_id'], 'module_id': module_id, 'expected_revision': revision,
                       'operation': 'submit' if operation == 'await-result' else operation}}
    gate = slim.pop('context_gate', None) or {}
    stage = gate.get('stage') or ('test-design' if operation == 'await-result' and step.get('mode') == 'design' else None)
    if stage:  # one object says what the preflight report of this stage must contain and which reports exist
        out['context'] = {'stage': stage, **st['context_requirements'].get(module_id or 'GLOBAL', {}).get(stage, {}), **gate}
    if module_id is not None:
        m = st['modules'].get(module_id) or st.get('module_groups', {}).get(module_id) or {}
        out['module_input'] = st['module_inputs'].get(module_id)
        out['module'] = {'quality': m.get('effective_quality') or m.get('quality'),
                         **{k: m[k] for k in MODULE_KEYS if m.get(k) is not None},
                         'results': {pid: row.get('quality') for pid, row in (m.get('results') or {}).items()}}
        assignment = (m.get('assignments') or {}).get(step.get('assignment_id'))
        if assignment:
            out['assignment'] = {k: assignment[k] for k in ASSIGNMENT_KEYS if assignment.get(k) is not None}
        submission = (m.get('submissions') or {}).get(step.get('assignment_id'))
        if submission:
            out['submission'] = submission
    if operation in reading.PLANNING_OPERATIONS or step.get('mode') == 'design':
        out['planning_context'] = st['planning_context']
    return out


def select(st, view='full', module_id=None, since=None):
    if view == 'full':
        return st
    if view not in VIEWS:
        raise ValueError('unknown status view: ' + str(view))
    if (since is not None and since == st['last_sequence'] and not st['observed_invalidations']
            and st['projection'].get('status') == 'current'):
        return {'view': view, 'unchanged': True, 'last_sequence': since, 'workflow_progress': _attention(st['workflow_progress'])}
    if view == 'step':
        return _step(st, module_id)
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
    out['cards'] = {sha: size for sha, size in cards.items()
                    if sha in {x.get('card_sha256') for x in out['next_steps'] + [out['global_next_step']]}}
    return out
