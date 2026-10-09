"""Version-bound, role-specific context receipts; no new business state machine."""
import copy
from pathlib import Path

from contracts import Rejected, check_ref, cited, digest, nonempty, read_json, require
import decomposition
import dimensions


CHECKS = {
    'global-discovery': ('global-inputs', 'feature-inventory', 'source-target', 'architecture-knowledge', 'reuse-sources', 'host-capabilities'),
    'global-planning': ('global-inputs', 'feature-inventory', 'allocation-coverage', 'interfaces-ownership', 'reuse-sources'),
    'decomposition': ('global-inputs', 'feature-inventory', 'assigned-scope', 'source-target', 'interfaces-ownership', 'reuse-sources'),
    'planning': ('global-inputs', 'feature-inventory', 'assigned-scope', 'source-closure', 'target-feasibility', 'interfaces-ownership', 'test-design', 'reuse-mapping'),
    'test-design': ('assigned-scope', 'spec-cases', 'task-coverage', 'independence'),
    'coding': ('frozen-spec', 'task-trace', 'source-closure', 'target-feasibility', 'interfaces-ownership', 'reuse-mapping', 'permissions-tools'),
    'building': ('frozen-spec', 'accepted-code', 'build-command', 'build-environment', 'permissions-tools'),
    'testing': ('frozen-spec', 'test-paths', 'accepted-code', 'provider-binding', 'test-environment', 'permissions-tools'),
    'fixing': ('frozen-spec', 'task-trace', 'interfaces-ownership', 'reuse-mapping', 'failure-diagnosis', 'repair-history', 'permissions-tools'),
    'audit-analysis': ('module-summaries', 'findings', 'spec-paths', 'dependency-owners', 'reuse-mapping', 'independence'),
    'audit-code-review': ('module-summaries', 'whole-change-diff', 'spec-paths', 'dependency-owners', 'reuse-mapping', 'shared-capabilities', 'fidelity', 'independence'),
    'audit-testing': ('module-summaries', 'spec-paths', 'accepted-code', 'provider-binding', 'test-environment', 'independence'),
    'audit-verdict': ('module-summaries', 'findings', 'spec-paths', 'verification-results', 'independence'),
}
CHECKS['audit-execution'] = CHECKS['audit-testing']
ROLES = {stage: ('auditor' if stage.startswith('audit-') else
                 'global-orchestrator' if stage.startswith('global-') else
                 {'decomposition': 'module-orchestrator', 'planning': 'spec-designer',
                  'coding': 'implementer', 'building': 'test-runner', 'testing': 'test-runner', 'test-design': 'test-runner', 'fixing': 'fixer'}[stage])
         for stage in CHECKS}
ROLES['audit-execution'] = 'test-runner'
GLOBAL = {stage for stage in CHECKS if stage.startswith(('global-', 'audit-'))}
# The actor that preflights is the actor that acts: its report is registered with the operation itself.
# A worker (coding, building, testing, fixing) reports with context-submit inside its dispatch; only the audit
# dispatch (audit-testing) still needs the Auditor's report beforehand.
SELF_REPORTED = ('register', 'global-plan', 'decompose', 'plan', 'audit-plan', 'audit-verdict', 'source-review', 'run-review', 'audit-code-review')
WORKERS = {'implementer': 'coding', 'test-runner': 'testing', 'fixer': 'fixing'}


# The stage whose preflight asks nothing the Ledger cannot check by itself: every input exists and is the bytes its
# reference names, and the subject is current. A build or a test run also approves commands and an environment, which
# only the worker that will run them can state; a repair round is spent when the Fixer says it can start.
MECHANICAL = {'implementer': 'coding'}


def mechanical(root, s, mid, assignment):
    """Write and register, in the worker's name, the preflight of a dispatch the Ledger can check by itself; None when
    the stage needs the worker's own report or an input is not as referenced (the worker then reports what is missing)."""
    stage = MECHANICAL.get(assignment.get('role'))
    if not stage or root is None:
        return None
    m = scope(s, mid)
    actor = {'role': assignment['role'], 'instance_id': assignment['instance_id']}
    try:
        verify_inputs(s, mid, stage, deep=True)
        refs = input_refs(s, mid, stage)
        proof = {'frozen-spec': m['plan_ref'], 'reuse-mapping': (m.get('plan') or {}).get('reuse_plan_ref'),
                 'source-closure': dimensions.of_leaf(m),
                 'failure-diagnosis': (diagnosis_report(m) or {}).get('diagnosis_ref')}
        fact = {'frozen-spec': 'freeze ' + str(m.get('freeze_id'))[:12], 'task-trace': str(len(m['plan']['tasks'])) + ' tasks traced to their paths',
                'repair-history': str(len(m.get('fix_memory', []))) + ' earlier repair records', 'permissions-tools': 'write scope ' + ', '.join(m.get('write_paths', []))}
        checks = {name: {'status': 'ready', 'evidence_refs': [proof.get(name) or m['plan_ref']],
                         'summary': 'checked by the Ledger: the %d inputs of this stage exist and match their hashes; %s'
                                    % (len(refs), fact.get(name, 'bound to the frozen plan'))} for name in CHECKS[stage]}
        report = {'schema_version': 1, 'run_id': s['run_id'], 'module_id': mid, 'stage': stage, 'producer': actor, 'mechanical': True,
                  'subject_sha256': subject(s, mid, stage), 'checks': checks, 'verdict': 'ready'}
        import project_context
        ref = project_context.archive(Path(root) / 'artifacts/preflight', project_context.encoded(report), '.json')
        submit(s, {'payload': {'report_ref': ref}, 'module_id': mid}, actor)
        return ref
    except (Rejected, OSError, KeyError, TypeError):
        return None


def enabled(s):
    return s.get('context_readiness_required', False)


def scope(s, mid):
    return s if mid is None else s['modules'].get(mid) or s.get('module_groups', {})[mid]


def execution_context(s, mid, stage):
    ref = scope(s, mid).get('execution_context_ref') if mid and stage in set(WORKERS.values()) | {'building'} else None
    return read_json(check_ref(ref)) if ref else None


def pin_execution(root, s, affected):
    """Keep frozen, unaffected workers on the accepted context across upstream revisions."""
    from project_context import archive, encoded
    pending = [m for mid, m in s['modules'].items() if mid not in affected
               and m.get('freeze_id') and not m.get('execution_context_ref')]
    if pending:
        data = encoded({'planning_context': decomposition.planning_context(s), 'global_refs': global_refs(s),
            'harmony_environment_revision': s.get('harmony_environment_revision'),
            'assigned_modules': {mid: decomposition.assigned_module(s, m) for mid, m in s['modules'].items()}})
        ref = archive(root / 'artifacts/contexts', data, '.json')
        for m in pending: m['execution_context_ref'] = ref


def subject(s, mid, stage):
    """Do not bind sibling progress or receipt revisions into a leaf receipt."""
    require(stage in CHECKS and ((mid is None) == (stage in GLOBAL)), 'context stage/scope mismatch')
    shared = decomposition.planning_context(s)
    pinned = execution_context(s, mid, stage)
    if pinned:
        shared = pinned['planning_context']
    if stage == 'global-discovery':
        shared = {k: v for k, v in shared.items() if k not in ('modules', 'parents', 'dimension_allocations')}
    value = {'run_id': s['run_id'], 'module_id': mid, 'stage': stage, 'planning_context': shared}
    if stage in ('global-discovery', 'global-planning', 'decomposition', 'planning'):
        value['history_ref'] = scope(s, mid).get('planning_lessons_ref') if mid else s.get('lessons_ref')
    if mid:
        m = scope(s, mid)
        value['assigned_module'] = pinned['assigned_modules'][mid] if pinned else decomposition.assigned_module(s, m)
        if stage == 'test-design':
            value['design_input_ref'] = m.get('design_input_ref')
            value['design_generation'] = m.get('design_generation', 0)
        if stage in set(WORKERS.values()) | {'building'}:
            value['execution'] = {k: m.get(k) for k in (
                'plan_ref', 'freeze_id', 'code_baseline', 'recovery_cycle', 'diagnosis',
                'results', 'repair_findings', 'fix_memory', 'local_fix_used', 'audit_fix_grant')}
            if stage == 'fixing':
                # Bind the diagnosis content, accepted or still the submitted draft, so a Fixer may
                # preflight before MO acceptance and stay valid after it.
                value['execution']['diagnosis'] = diagnosis_report(m)
            value['dependencies'] = {d: {k: s['modules'][d].get(k) for k in ('freeze_id', 'code_baseline', 'stale', 'phase')}
                                     for d in m['dependencies']}
    elif stage.startswith('audit-'):
        value['modules'] = {mid: {k: m.get(k) for k in (
            'plan_ref', 'freeze_id', 'code_baseline', 'results', 'blocked', 'phase', 'stale', 'authors')}
                           for mid, m in s['modules'].items()}
        value['summaries'] = {mid: {k: g.get(k) for k in ('summary_ref', 'summary_subject')}
                              for mid, g in s.get('module_groups', {}).items()}
        value['audit_batch'] = s.get('audit_batch')
        value['audit_queue'] = s.get('audit_queue')
        value['global_paths'] = s['global_paths']
        value['audit_assignment'] = s.get('audit_assignment')
        value['audit_code_review'] = s.get('audit_code_review')
    return digest(value)


def verify_refs(value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            check_ref(value)
        for item in value.values():
            verify_refs(item)
    elif isinstance(value, list):
        for item in value:
            verify_refs(item)


def diagnosis_report(m):
    return m.get('diagnosis') or (m.get('diagnosis_submission') or {}).get('report')


def global_refs(s):
    refs = [s['global_spec'], s['new_architecture']]
    if (s.get('global_plan') or {}).get('source_review_ref'):
        change_ref = s['global_plan']['source_review_ref']
        refs += [change_ref, read_json(check_ref(change_ref))['catalog_ref']]
    inventory = (s.get('global_plan') or {}).get('content', {}).get('feature_inventory_ref')
    if inventory:
        refs.append(inventory)
    if s.get('project_context_ref'):
        refs.append(s['project_context_ref'])
        for key, source in read_json(check_ref(s['project_context_ref'])).get('source_refs', {}).items():
            if key != 'slicing_skill_ref':  # read where slicing is decided, not by every stage: see standing_refs
                refs.extend(source if isinstance(source, list) else [source])
    return refs


SLICING_STAGES = ('global-discovery', 'global-planning', 'decomposition')


def slicing_skill(s):
    """The slicing skill earlier runs of the project left, as frozen into this run; None on a project's first runs."""
    if not s.get('project_context_ref'):
        return None
    return read_json(check_ref(s['project_context_ref'])).get('source_refs', {}).get('slicing_skill_ref')


def target_rules(s, pinned):
    """What code is written against: the target architecture, the project rules and the knowledge documents."""
    context = pinned['planning_context'] if pinned else decomposition.planning_context(s)
    refs = [context['new_architecture']]
    for name in ('project_rules_path', 'knowledge_paths'):
        source = (context.get('project_sources') or {}).get(name)
        refs.extend(source if isinstance(source, list) else [source] if source else [])
    return refs


def worker_refs(s, m, stage, pinned):
    """A worker's inputs are what its step executes: a Test-Runner runs the frozen plan with its prepared assets; a code
    author also holds the allocation the plan implements and the target's rules, a Fixer the diagnosis as well. The
    legacy sources an allocation lists are reference material, taken item by item where a task's analysis points."""
    refs = []
    if stage in ('coding', 'fixing'):
        refs += target_rules(s, pinned)
        if dimensions.of_leaf(m):
            refs.append(dimensions.of_leaf(m))  # the leaf's refinement when its plan binds one
        if stage == 'fixing' and diagnosis_report(m):
            refs.append(diagnosis_report(m)['diagnosis_ref'])  # the Fixer must have read the diagnosis
    if m.get('plan_ref'):
        refs.append(m['plan_ref'])
        refs += [r for r in m['plan'].get('definitions', []) if r['kind'] in ('test-script', 'test-fixture', 'test-adapter')]
        if m['plan'].get('reuse_plan_ref'):
            refs.append(m['plan']['reuse_plan_ref'])
    return list({(ref['path'], ref['sha256']): ref for ref in refs}.values())


def input_refs(s, mid, stage):
    """What a role has to have read for a stage; its ready report is bound to their digest."""
    if mid and stage in set(WORKERS.values()) | {'building'}:
        return worker_refs(s, scope(s, mid), stage, execution_context(s, mid, stage))
    refs = standing_refs(s, mid, stage)
    if mid and stage in ('planning', 'decomposition'):
        # The legacy and target trees are opened where an item's locator points; the analysis, the parent's context and
        # the upstream cases are what a plan or a split is written from. The whole set still may not drift.
        trees = [Path(s[key]).resolve() for key in ('legacy_root', 'target_root') if s.get(key)]
        refs = [ref for ref in refs if not any(Path(ref['path']).resolve().is_relative_to(tree) for tree in trees)]
    return refs


def standing_refs(s, mid, stage):
    """Everything a ready report of a stage stands on. A worker reads less than this, but no report is accepted or used
    over drifted evidence, whether or not its author had to read that evidence."""
    pinned = execution_context(s, mid, stage)
    refs = list(pinned['global_refs']) if pinned else global_refs(s)
    if stage in ('global-discovery', 'global-planning', 'decomposition', 'planning'):
        history = scope(s, mid).get('planning_lessons_ref') if mid else s.get('lessons_ref')
        if history: refs.append(history)
    if stage in SLICING_STAGES and slicing_skill(s):
        refs.append(slicing_skill(s))
    if mid:
        m = scope(s, mid)
        if stage == 'test-design' and m.get('design_input_ref'):
            refs.append(m['design_input_ref'])
            assignment = next((a for a in reversed(list(m['assignments'].values()))
                               if a.get('mode') == 'design'), {})
            refs += assignment.get('input_refs', [])
        if stage == 'planning' and m.get('accepted_test_design'):
            refs.append(m['accepted_test_design']['result_ref'])
        refs += m.get('context_refs', [])
        if m.get('dimension_analysis_ref'):
            refs.append(m['dimension_analysis_ref'])
        parent = (pinned['assigned_modules'][mid] if pinned else decomposition.assigned_module(s, m)).get('parent_context')
        if parent:
            refs += parent['context_refs']
            if parent.get('dimension_analysis_ref'):
                refs.append(parent['dimension_analysis_ref'])
        if stage == 'fixing' and diagnosis_report(m):
            refs.append(diagnosis_report(m)['diagnosis_ref'])
        if stage in set(WORKERS.values()) | {'building'} and m.get('plan_ref'):
            refs.append(m['plan_ref'])
            refs += [r for r in m['plan'].get('definitions', []) if r['kind'] in ('test-script', 'test-fixture', 'test-adapter')]
            if m['plan'].get('reuse_plan_ref'):
                refs.append(m['plan']['reuse_plan_ref'])
    elif stage.startswith('audit-'):
        refs += [m['dimension_analysis_ref'] for m in s['modules'].values() if m.get('dimension_analysis_ref')]
        refs += [m['plan_ref'] for m in s['modules'].values() if m.get('plan_ref')]
        refs += [g['summary_ref'] for g in s.get('module_groups', {}).values() if g.get('summary_ref')]
        refs += [m['plan']['reuse_plan_ref'] for m in s['modules'].values() if (m.get('plan') or {}).get('reuse_plan_ref')]
        if stage == 'audit-execution':
            import prepared_tests
            for module in s['modules'].values():
                for path in (module.get('plan') or {}).get('paths', []):
                    previous = module.get('results', {}).get(path['path_id'])
                    if previous and (previous.get('stale') or previous['quality'] != 'green-passed'):
                        binding = prepared_tests.binding(module, path)
                        if binding:
                            refs.append(binding['test_design_ref'])
                            refs.extend(a['ref'] for a in binding['assets'])
            for path in s.get('global_paths', []):
                if path.get('test_design_ref'):
                    refs.append(path['test_design_ref'])
                    refs.extend(a['ref'] for a in prepared_tests.assets(read_json(check_ref(path['test_design_ref'])))
                                if path['path_id'] in a['path_ids'])
        if stage != 'audit-code-review' and s.get('audit_code_review'):
            refs.append(s['audit_code_review']['report_ref'])
    if stage == 'global-planning':
        refs += list(decomposition.planning_context(s).get('dimension_allocations', {}).values())
    return list({(ref['path'], ref['sha256']): ref for ref in refs}.values())


def inputs(s, mid, stage, refs=None):
    """What a ready report of the stage is bound to: the mandatory inputs the Ledger derives, as a count and a digest.

    An author never lists them back (nothing could prove it read them); the report goes stale when any of them changes."""
    refs = input_refs(s, mid, stage) if refs is None else refs
    return {'inputs_sha256': digest(sorted((ref['path'], ref['sha256']) for ref in refs)), 'input_count': len(refs)}


def verify_inputs(s, mid, stage, deep=False, refs=None):
    """No ready report stands on drifted evidence: everything it stands on is as referenced and, with `deep`, so is
    what its JSON cites. Nested live target code may legitimately drift; everything else may not."""
    seen, root = set(), s.get('target_root')
    def walk(value, nested):
        if isinstance(value, dict):
            if cited(value, nested):
                if (value['path'], value['sha256']) in seen:
                    return
                seen.add((value['path'], value['sha256']))
                try:
                    path = check_ref(value)
                except Rejected:
                    if nested and root and Path(value['path']).resolve().is_relative_to(Path(root).resolve()):
                        return
                    raise
                if deep and path.suffix == '.json':
                    try:
                        document = read_json(path)
                    except Rejected:
                        raise
                    except ValueError:  # not JSON after all
                        document = None
                    walk(document, True)
                return
            for item in value.values():
                walk(item, nested)
        elif isinstance(value, list):
            for item in value:
                walk(item, nested)
    walk(standing_refs(s, mid, stage) if refs is None else refs, False)


def submit(s, req, actor):
    p, mid = req['payload'], req.get('module_id')
    report = read_json(check_ref(p.get('report_ref')))
    stage = report.get('stage')
    require(stage in CHECKS and actor.get('role') == ROLES[stage] and actor.get('instance_id'), 'context producer role denied')
    require(report.get('schema_version') == 1 and report.get('run_id') == s['run_id'] and report.get('module_id') == mid,
            'context report run/module mismatch')
    require(report.get('producer') == actor, 'context producer identity mismatch')
    if stage == 'test-design':
        m = scope(s, mid)
        require(any(a.get('mode') == 'design' and not a.get('closed') and a['instance_id'] == actor['instance_id']
                    for a in m['assignments'].values()), 'test-design context requires active design assignment')
    require(report.get('subject_sha256') == subject(s, mid, stage), 'context subject stale')
    if stage.startswith('audit-'):
        import audit_closure
        if not audit_closure.active(s):
            require(not audit_closure.collection_blockers(s), 'all module rounds must settle before Auditor context review')
        require(all(actor['instance_id'] not in m['authors'] for m in s['modules'].values()), 'Auditor must be independent')
        if s.get('audit_batch', {}).get('status') not in (None, 'released', 'verified', 'completed-with-unverified-tests'):
            require(actor['instance_id'] == s['audit_batch']['auditor_instance_id'], 'context auditor mismatch')
    checks = report.get('checks')
    require(isinstance(checks, dict) and set(checks) == set(CHECKS[stage]), 'context checklist incomplete/unknown')
    for name, item in checks.items():
        require(isinstance(item, dict) and item.get('status') in ('ready', 'blocked'), 'invalid context check: ' + name)
        require(isinstance(item.get('summary'), str) and item['summary'].strip(), 'context understanding summary required: ' + name)
        if item['status'] == 'ready':
            for ref in nonempty(item.get('evidence_refs'), 'context evidence: ' + name):
                check_ref(ref)
        else:
            require(item.get('missing') and item.get('next_action') and item.get('owner'), 'context blocker needs missing/owner/next_action')
    require(report.get('verdict') == ('blocked' if any(c['status'] == 'blocked' for c in checks.values()) else 'ready'),
            'context verdict disagrees with checks')
    required = input_refs(s, mid, stage) if report['verdict'] == 'ready' else None
    if required is not None:
        verify_inputs(s, mid, stage, deep=True)
    if report['verdict'] == 'ready' and stage in ('building', 'testing', 'audit-testing', 'audit-execution'):
        execution = report.get('execution', {})
        argv = execution.get('argv')
        require(isinstance(argv, list) and argv and all(isinstance(arg, str) for arg in argv)
                and Path(argv[0]).is_absolute(), 'context approved test argv required')
        require(Path(execution.get('cwd', '')).is_absolute() and Path(execution['cwd']).is_dir(), 'context test cwd missing')
        check_ref(execution.get('environment_ref'))
    verify_refs(report)
    # Most recent receipt for this role instance wins; an old ready report cannot
    # bypass a newer missing-context report from the same instance.
    key = stage + ':' + actor['instance_id']
    # The receipt is the hash-bound reference; the report itself stays in its file and archive.
    receipt = scope(s, mid).setdefault('context_receipts', {})[key] = {
        'report_ref': copy.deepcopy(p['report_ref']), 'stage': stage,
        'producer': copy.deepcopy(report['producer']), 'verdict': report['verdict'],
        **({'inputs_sha256': inputs(s, mid, stage, required)['inputs_sha256']} if required is not None else {})}
    return receipt


def requirement(op, p, s=None):
    if op == 'audit-test-assign': return 'audit-execution'
    if op == 'audit-assign' and s is not None:
        from ledger import audit_scope
        return 'audit-testing' if audit_scope(s)['plan']['paths'] else 'audit-verdict'
    if op == 'assign':
        if p.get('mode') == 'design':
            return None  # MO commits design inputs first; designer preflights before submit.
        return 'building' if p.get('role') == 'test-runner' and p.get('test_scope') == 'build' else WORKERS.get(p.get('role'))
    return {'register': 'global-discovery', 'global-plan': 'global-planning', 'source-review': 'global-planning', 'run-review': 'global-planning',
            'decompose': 'decomposition', 'decompose-accept': 'decomposition',
            'plan': 'planning', 'freeze': 'planning', 'audit-plan': 'audit-analysis', 'audit-code-review': 'audit-code-review',
            'audit-assign': 'audit-testing',
            'audit-verdict': 'audit-verdict'}.get(op)


def validate(s, mid, stage, ref, instance=None, draft=None, allow_blocked=False):
    report = read_json(check_ref(ref))
    require(report.get('stage') == stage, 'wrong context stage')
    producer = report.get('producer', {})
    require(producer.get('role') == ROLES[stage], 'wrong context producer role')
    require(instance is None or producer.get('instance_id') == instance, 'context receipt belongs to another worker')
    receipt = scope(s, mid).get('context_receipts', {}).get(stage + ':' + producer.get('instance_id', ''))
    require(receipt and receipt['report_ref'] == ref, 'context receipt not submitted/current')
    require(report['subject_sha256'] == subject(s, mid, stage), 'context subject stale; re-read and resubmit')
    require(report['verdict'] == 'ready' or allow_blocked, 'context blocked; record suspension or resolve missing inputs')
    if report['verdict'] == 'ready':
        required = input_refs(s, mid, stage)
        require(receipt.get('inputs_sha256') == inputs(s, mid, stage, required)['inputs_sha256'],
                'context report is stale: its mandatory inputs changed; re-read them and report again')
        verify_inputs(s, mid, stage)
    if draft:
        require(report.get('draft_ref') == draft, 'context report must bind the reviewed draft')
    verify_refs(report)
    return report


def reported(s, mid, p):
    """What the worker of a dispatch has already reported for its stage: a current ready report is bound to the
    assignment at once; a report in which this instance is still blocked on the current subject stops the dispatch."""
    stage, instance = requirement('assign', p), p.get('instance_id')
    receipt = scope(s, mid).get('context_receipts', {}).get(stage + ':' + str(instance))
    if not receipt:
        return None
    try:
        report = validate(s, mid, stage, receipt['report_ref'], instance, allow_blocked=True)
    except (Rejected, OSError, ValueError):
        return None  # outdated: the worker reports again inside the assignment
    require(report['verdict'] == 'ready', 'context blocked; record suspension or resolve missing inputs')
    return receipt['report_ref']


def owed(s, mid, step):
    """The stage a running worker still has to report on: a designer's report rides its submit, any other
    worker's report authorizes the work and is owed until it is bound to the assignment."""
    assignment = scope(s, mid).get('assignments', {}).get(step.get('assignment_id')) or {}
    if assignment.get('mode') == 'design':
        return 'test-design'
    return None if assignment.get('context_ref') else requirement('assign', assignment)


def gate(s, req, actor):
    """Existing owner action accepts the read-only preflight; no extra human approval."""
    if not enabled(s):
        return
    op, p, mid = req['operation'], req.get('payload', {}), req.get('module_id')
    stage = requirement(op, p, s)
    if not stage:
        return
    obj = scope(s, mid)
    ref = p.get('context_ref')
    if op == 'assign' and not ref:
        return  # dispatch first: the worker reports inside its assignment
    if op in ('freeze', 'decompose-accept'):
        ref = obj.get('context_acceptances', {}).get('plan' if op == 'freeze' else 'decompose', {}).get('report_ref')
    require(ref, 'context readiness receipt required for ' + op)
    instance = p.get('instance_id') if op in ('assign', 'audit-assign', 'audit-test-assign') else None
    if op in ('register', 'global-plan', 'decompose', 'plan', 'audit-plan', 'audit-verdict', 'source-review', 'run-review', 'audit-code-review'):
        instance = actor['instance_id']
    draft = p.get('plan_ref') if op in ('global-plan', 'decompose', 'plan', 'audit-plan') else obj.get('plan_ref') if op == 'freeze' else None
    if op in ('source-review', 'run-review', 'audit-code-review'): draft = p.get('report_ref')
    if op in SELF_REPORTED and obj.get('context_receipts', {}).get(stage + ':' + instance, {}).get('report_ref') != ref:
        submit(s, {'payload': {'report_ref': ref}, 'module_id': mid}, actor)
    validate(s, mid, stage, ref, instance, draft)
    obj.setdefault('context_acceptances', {})[op] = {'report_ref': copy.deepcopy(ref), 'accepted_by': copy.deepcopy(actor)}


def requirements(s):
    """Read-only host API; receipts never authorize execution without owner gates."""
    if not enabled(s):
        return {}
    result = {}
    for mid in [None, *s['modules']]:
        stages = GLOBAL if mid is None else ('decomposition',) if s['modules'][mid].get('decomposition_required') else ('planning', 'test-design', 'coding', 'building', 'testing', 'fixing')
        result[mid or 'GLOBAL'] = {stage: {'subject_sha256': subject(s, mid, stage),
            'producer_role': ROLES[stage], 'required_checks': list(CHECKS[stage]),
            'required_input_refs': input_refs(s, mid, stage), **inputs(s, mid, stage)} for stage in sorted(stages)}
    return result


def annotate(s, mid, step):
    waiting = step.get('operation') == 'await-result'
    stage = (owed(s, mid, step) if waiting else
             requirement(step.get('operation'), {'role': step.get('worker_role'), 'test_scope': step.get('test_scope'), 'mode': step.get('mode')}, s))
    if not enabled(s) or not stage:
        return step
    step = copy.deepcopy(step)
    step['context_gate'] = {'stage': stage, 'producer_role': ROLES[stage],
                            'subject_sha256': subject(s, mid, stage), 'required_checks': list(CHECKS[stage])}
    if waiting:
        return step
    available = []
    accepted = None
    if step.get('operation') in ('freeze', 'decompose-accept'):
        original = 'plan' if step['operation'] == 'freeze' else 'decompose'
        accepted = scope(s, mid).get('context_acceptances', {}).get(original, {}).get('report_ref')
    for receipt in scope(s, mid).get('context_receipts', {}).values():
        if receipt['stage'] != stage:
            continue
        if step.get('operation') in ('freeze', 'decompose-accept') and receipt['report_ref'] != accepted:
            continue
        try:
            validate(s, mid, stage, receipt['report_ref'])
            available.append(receipt['report_ref'])
        except (Rejected, OSError, ValueError):
            pass
    step['context_gate']['ready_receipts'] = available
    if step.get('ready') and not available:
        if stage in ('testing', 'audit-testing'):
            import test_validation as tv
            for receipt in scope(s, mid).get('context_receipts', {}).values():
                ref = receipt['report_ref']
                try:
                    tv.blocked_report(s, mid, ref, stage)
                    if mid:
                        require(tv.build_ready(s['modules'][mid]), 'build not ready')
                        require(tv.can_defer(s['modules'][mid]), 'observed failure')
                    step.update(operation='automation-unavailable' if mid else 'audit-unavailable',
                                role='module-orchestrator' if mid else 'auditor', ready=True,
                                payload={'context_ref': ref}, reason='record-automation-not-run-and-continue')
                    return step
                except (Rejected, OSError, ValueError):
                    pass
        if step.get('operation') in SELF_REPORTED:
            step['context_gate']['with_operation'] = True  # the report rides the operation: pass it as context_ref
            return step
        if step.get('operation') == 'assign':
            # Dispatch first; only a report that is still blocked on the current subject holds the dispatch back.
            blocked = []
            for receipt in scope(s, mid).get('context_receipts', {}).values():
                if receipt['stage'] == stage and receipt['verdict'] == 'blocked':
                    try:
                        validate(s, mid, stage, receipt['report_ref'], allow_blocked=True)
                        blocked.append(receipt['report_ref'])
                    except (Rejected, OSError, ValueError):
                        pass
            if blocked:
                step['context_gate']['blocked_receipts'] = blocked
                step.update(ready=False, reason='context-blocked',
                            context_next_action='resolve the reported gap, then the worker reports again; or record explicit blocker')
            return step
        step.update(ready=False, reason='context-readiness-required', context_next_action='context-submit or record explicit blocker')
        if step.get('operation') in ('freeze', 'decompose-accept'):
            step['context_next_action'] = 'refresh context-submit and resubmit plan/decompose, or record explicit blocker'
    return step


def check_execution(s, assignment, argv, cwd, path_id=None):
    if not enabled(s):
        return
    require(assignment.get('context_ref'), 'test context missing; context-submit the preflight of this assignment first')
    report = read_json(check_ref(assignment['context_ref']))
    require(report['stage'] in ('building', 'testing', 'audit-testing', 'audit-execution') and report['verdict'] == 'ready', 'test context missing')
    verify_refs(report)
    expected = report['execution'].get('commands', {}).get(path_id, report['execution'])
    require(argv == expected['argv'] and str(Path(cwd).resolve()) == str(Path(expected['cwd']).resolve()),
            'test command differs from approved context; obtain a new preflight/assignment')
