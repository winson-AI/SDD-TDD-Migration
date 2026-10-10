"""Bounded views over the full Ledger status, for hosts that poll after every event.

The full status grows with the number of modules and stays on disk as projections; a host
deciding its next dispatch needs the cursor, and the one module it is about to act on. A role
acting on a step needs that step, the readiness requirement of its stage and its own allocation,
not the other modules. Steps refer to their reading card by digest; the card's rows come from
`reading.py render` (or the full view), so a poll carries only the card's size. A poll that passes
the sequence it already saw gets a brief answer while nothing has changed.
"""
import issues
import reading

CURSOR_KEYS = ('run_id', 'last_sequence', 'quality', 'projection', 'source_change_next_step', 'run_change_next_step', 'global_next_step',
               'next_steps', 'ready_modules', 'module_rounds', 'observed_invalidations')
VIEWS = ('full', 'cursor', 'module', 'step')
# What a role needs of its module and of the assignment its step refers to.
MODULE_KEYS = ('phase', 'plan_ref', 'freeze_id', 'code_baseline', 'blocked', 'execution_context_ref', 'carried_files', 'allocation_changes')
ASSIGNMENT_KEYS = ('assignment_id', 'role', 'instance_id', 'fencing_token', 'mode', 'test_scope', 'freeze_id',
                   'code_baseline', 'context_ref', 'design_input_ref', 'execution_contract', 'path_ids', 'audit_assignment_id', 'result_ref')


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


def _body(module):
    """A module without the bodies its plan_ref, plan_hash and scenario trace stand for; a plan alone runs to hundreds of KB."""
    slim = {key: value for key, value in module.items() if key not in ('plan', 'scenario_index')}
    plan = module.get('plan')
    if isinstance(plan, dict):
        slim['plan'] = {'tasks': [t.get('task_id') for t in plan.get('tasks', [])], 'paths': [p.get('path_id') for p in plan.get('paths', [])]}
    return slim


def _cursor(st, cards):
    out = {k: st[k] for k in CURSOR_KEYS if k in st}
    out['next_steps'] = [_slim(x, cards) for x in st['next_steps']]
    out['global_next_step'] = _slim(st['global_next_step'], cards)
    out['workflow_progress'] = _attention(st['workflow_progress'])
    out['module_summary'] = {mid: {'phase': m['phase'], 'quality': m.get('effective_quality') or m['quality'],
                                   'blocked': (m.get('blocked') or {}).get('reason_code')}
                             for mid, m in st['modules'].items()}
    owed = [target for row in issues.of_module(st)[0] for target in row['open_for']]
    out['open_issues'] = {mid: owed.count(mid) for mid in sorted(set(owed))}  # the step view of a module lists them
    adoption = st['hint_adoption']
    out['hint_adoption'] = {k: adoption[k] for k in ('session', 'card')}
    return out


def _standing(st, module_id):
    """The planning context a step is handed: for a leaf, what it stands on in full and the other slices by name, write
    paths and dependencies only - enough to see whom to ask; their allocations are a `--view module` away."""
    import decomposition
    context = st['planning_context']
    if module_id not in st['modules']:
        return context
    scoped = decomposition.standing(st, module_id, context)
    others = {mid: {'name': m.get('name'), 'write_paths': m.get('write_paths'), 'dependencies': m.get('dependencies')}
              for mid, m in st['modules'].items() if mid not in scoped['modules']}
    return {**scoped, **({'other_modules': others} if others else {})}


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
    gate = slim.pop('context_gate', None)
    operation = step.get('operation')
    if operation == 'await-result':  # a running worker reports first if its report is still owed, then submits
        operation = 'context-submit' if gate and step.get('mode') != 'design' else 'submit'
    out = {'view': 'step', 'run_id': st['run_id'], 'last_sequence': st['last_sequence'], 'step': slim, 'cards': cards,
           # The envelope of the request this step asks for.
           'request': {'schema_version': 1, 'run_id': st['run_id'], 'module_id': module_id, 'expected_revision': revision,
                       'operation': operation}}
    out['open_issues'], out['standing_rules'] = issues.of_module(st, module_id)
    if gate:  # one object says what the preflight report of this stage must contain and which reports exist
        required = dict(st['context_requirements'].get(module_id or 'GLOBAL', {}).get(gate['stage'], {}))
        required.pop('required_input_refs', None)  # the Ledger derives them; the step carries their count and digest
        out['context'] = {**required, **gate}
    if module_id is not None:
        m = st['modules'].get(module_id) or st.get('module_groups', {}).get(module_id) or {}
        out['module_input'] = st['module_inputs'].get(module_id)
        if st.get('providers', {}).get(module_id):
            out['providers'] = st['providers'][module_id]  # what this leaf plans against, instead of a description of it
        out['module'] = {'quality': m.get('effective_quality') or m.get('quality'),
                         **{k: m[k] for k in MODULE_KEYS if m.get(k) is not None},
                         'results': {pid: row.get('quality') for pid, row in (m.get('results') or {}).items()}}
        assignment = (m.get('assignments') or {}).get(step.get('assignment_id'))
        if assignment:
            out['assignment'] = {k: assignment[k] for k in ASSIGNMENT_KEYS if assignment.get(k) is not None}
        submission = (m.get('submissions') or {}).get(step.get('assignment_id'))
        if submission:
            out['submission'] = submission
    if module_id is None and operation in ('audit', 'audit-assign', 'audit-test-assign', 'audit-test-submit'):
        import ledger
        assignment = st.get('audit_test_assignment') if operation == 'audit-test-submit' else st.get('audit_assignment')
        if assignment: out['assignment'] = {k: assignment[k] for k in ASSIGNMENT_KEYS if assignment.get(k) is not None}
        scope = ledger.audit_scope(st)
        out['audit_input'] = {'freeze_id': scope['freeze_id'], 'code_baseline': scope['code_baseline'],
            'paths': scope['plan']['paths'], 'code_files': scope['code_files'], 'results': scope['results']}
    if operation in reading.PLANNING_OPERATIONS or step.get('mode') == 'design':
        out['planning_context'] = _standing(st, module_id)
        out['history_refs'] = {'lessons': m.get('planning_lessons_ref') if module_id else st.get('lessons_ref')}
        if operation in ('run-review', 'revise-run'):
            import run_changes
            out['root_allocations'] = {mid: {k: root.get(k) for k in run_changes.ROOT_KEYS} for mid, root in run_changes.roots(st).items()}
            out['task_contract'] = {key: st[key] for key in run_changes.CONTRACT_KEYS}
            out['upstream_requests'] = {mid: root['realloc_request'] for mid, root in run_changes.roots(st).items() if root.get('realloc_request')}
        if module_id:
            history = m.get('planning_history', [])
            out['planning_history_count'] = len(history)
            out['planning_history_executable'] = False
            out['planning_history'] = [{k: h.get(k) for k in ('reason', 'evidence_ref', 'plan_ref', 'plan_hash')} for h in history[-5:]]
            out['reallocation_request'] = m.get('realloc_request')
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
        out['module'] = _body(st['modules'].get(module_id) or st.get('module_groups', {}).get(module_id))
        out['module_input'] = st['module_inputs'].get(module_id)
        rounds = st['module_rounds']
        out['module_rounds'] = {'all_settled': rounds['all_settled'],
                                'blockers': [b for b in rounds['blockers'] if b.get('module_id') == module_id]}
    out['cards'] = {sha: size for sha, size in cards.items()
                    if sha in {x.get('card_sha256') for x in out['next_steps'] + [out['global_next_step']]}}
    return out
