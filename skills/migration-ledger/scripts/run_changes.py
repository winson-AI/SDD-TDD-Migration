"""Reviewed root allocations and context revisions within one migration task/Run."""
import copy
from pathlib import Path

from contracts import check_ref, digest, keyed, nonempty, read_json, require, verify_plan
import decomposition
import dimensions
import project_context
import workflow
import control_policy

OPS = {'run-review', 'revise-run'}
CONFIG_KEYS = {'architecture_path', 'knowledge_paths', 'project_rules_path', 'build', 'test_adapter', 'runtime', 'target_resources'}
ROOT_KEYS = set(decomposition.ALLOCATION_KEYS) | {'module_id', 'dependencies'}
CONTRACT_KEYS = {'requirement_ids', 'case_ids', 'global_paths'}
RETIREMENT_KEYS = {'requirement': 'requirement_ids', 'case': 'case_ids', 'global-path': 'global_paths'}


def roots(s):
    return {**s.get('module_groups', {}), **{mid: m for mid, m in s['modules'].items() if not m.get('parent_module_id')}}


def retirements(s):
    """Historical dispositions, never successful tests or a second active contract."""
    return [{**copy.deepcopy(row), 'revision_ref': h['report_ref'], 'decision_id': h['decision_id'],
             'human_source_ref': h['human_source_ref'], 'previous_spec_ref': h['previous_global_spec'],
             **({'previous_path': next(p for p in h['previous_contract']['global_paths'] if p['path_id'] == row['id']),
                 'previous_result': h.get('retired_path_results', {}).get(row['id'])} if row['kind'] == 'global-path' else {})}
            for h in s.get('run_change_history', []) for row in h.get('retirements', [])]


def retirement_check(s, report, proposed):
    def ids(contract, kind):
        value = contract[RETIREMENT_KEYS[kind]]
        if kind == 'global-path':
            require(isinstance(value, list), 'global paths must be an array')
            return set(keyed(value, 'path_id')) if value else set()
        return set(value)
    removed = {(kind, rid) for kind in RETIREMENT_KEYS for rid in ids(s, kind) - ids(proposed, kind)}
    rows = report.get('retirements', [])
    require(isinstance(rows, list), 'retirements must be an array')
    seen = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'kind', 'id', 'replacement_ids', 'reason', 'evidence_refs'},
                'retirement requires kind/id/replacement_ids/reason/evidence_refs')
        kind, rid = row['kind'], row['id']
        require(kind in RETIREMENT_KEYS and isinstance(rid, str), 'invalid retirement identity')
        require((kind, rid) not in seen and (kind, rid) in removed, 'retirement must name a removed active contract item once')
        seen.add((kind, rid))
        replacements = row['replacement_ids']
        require(isinstance(replacements, list) and all(isinstance(i, str) for i in replacements)
                and len(set(replacements)) == len(replacements) and set(replacements) <= ids(proposed, kind),
                'replacement IDs must be active items of the same kind')
        require(isinstance(row['reason'], str) and row['reason'].strip(), 'retirement reason required')
        for ref in nonempty(row['evidence_refs'], 'retirement evidence'): check_ref(ref)
    require(seen == removed, 'existing requirement/case/global path cannot be removed without an explicit retirement')
    if rows:
        require((report.get('boundary_review') or {}).get('semantic_change') is True,
                'contract retirement is a semantic change requiring human decision')
    for row in retirements(s):
        require(row['id'] not in ids(proposed, row['kind']), 'retired contract IDs cannot be reused; allocate a new ID')


def contract(s, report):
    patch = report.get('contract_patch', {})
    require(isinstance(patch, dict) and set(patch) <= CONTRACT_KEYS, 'invalid task contract patch')
    proposed = {key: copy.deepcopy(patch.get(key, s[key])) for key in CONTRACT_KEYS}
    for key in ('requirement_ids', 'case_ids'):
        ids = nonempty(proposed[key], key)
        require(isinstance(ids, list) and all(isinstance(i, str) and i.strip() for i in ids)
                and len(set(ids)) == len(ids), 'unique nonempty contract IDs required')
    retirement_check(s, report, proposed)
    workflow.global_paths_check(proposed['global_paths'], proposed['case_ids'])
    if any(proposed[key] != s[key] for key in CONTRACT_KEYS):
        require(report.get('global_spec_ref'), 'contract changes require revised global business specification')
    return proposed


def subject(s, report_ref):
    report = read_json(check_ref(report_ref))
    affected = {row['module_id'] for row in report['modules'] if row['action'] != 'unchanged'}
    return digest({'run_id': s['run_id'], 'context_ref': s.get('project_context_ref'),
        'global_spec': s['global_spec'], 'contract': {k: s[k] for k in CONTRACT_KEYS},
        'global_plan': s.get('global_plan'), 'sources': s.get('reuse_sources', []),
        'roots': {mid: {key: m.get(key) for key in ROOT_KEYS | {'realloc_request'}} for mid, m in roots(s).items()},
        'modules': {mid: m if mid in affected else {key: m.get(key) for key in
            (*decomposition.ALLOCATION_KEYS, 'dependencies', 'parent_module_id', 'plan_hash', 'freeze_id', 'blocked', 'realloc_request',
             'design_generation', 'design_input_ref', 'accepted_test_design')}
            for mid, m in s['modules'].items()},
        'audit': {k: v for k, v in s.items() if k.startswith('audit')}, 'report_ref': report_ref})


def validate(s, ref):
    report = read_json(check_ref(ref))
    required = {'schema_version', 'run_id', 'reason', 'context_patch', 'root_updates', 'modules'}
    require(required <= set(report) <= required | {'global_spec_ref', 'contract_patch', 'retirements', 'lessons_ref', 'boundary_review'}, 'invalid run revision report')
    require(report['schema_version'] == 1 and report['run_id'] == s['run_id'] and report['reason'], 'run revision identity/reason required')
    proposed_contract = contract(s, report)
    control_policy.boundary(report.get('boundary_review'))
    if report.get('lessons_ref'):
        import experience
        experience.validate_lessons(report['lessons_ref'])
    patch = report['context_patch']
    require(isinstance(patch, dict) and set(patch) <= CONFIG_KEYS, 'run revision cannot change task identity, roots, budgets or quality gates')
    if patch:
        require(s.get('project_context_ref'), 'context revision requires a prepared run')
        config = project_context.merge(project_context.current_config(project_context.verify_snapshot(s['project_context_ref'])), patch)
        # Frozen snapshots contain source paths as well as bookkeeping references.
        project_context.validate({k: v for k, v in config.items() if k in project_context.FIELDS})
        require(config.get('architecture_path'), 'architecture required')
        for key in project_context.DOCUMENTS:
            if key in patch and patch[key] is not None:
                require(Path(patch[key]).is_file(), 'context document missing')
        for path in patch.get('knowledge_paths') or []:
            require(Path(path).is_file(), 'knowledge document missing')
    current = roots(s)
    require(isinstance(report['root_updates'], list), 'root updates must be an array')
    updates = keyed(report['root_updates'], 'module_id') if report['root_updates'] else {}
    require(set(updates) <= set(current), 'revise existing roots; register new roots through GO')
    for mid, update in updates.items():
        require(set(update) <= ROOT_KEYS and {'module_id', 'scope', 'case_ids', 'write_paths', 'context_refs', 'dependencies'} <= set(update),
                'root update must contain its complete allocation')
        candidate = {**current[mid], **update}
        nonempty(candidate['case_ids'], 'root cases')
        nonempty(candidate['write_paths'], 'root write scope')
        decomposition.check_scope(candidate)
        require(set(candidate['scope']['requirement_ids']) <= set(proposed_contract['requirement_ids']) and set(candidate['case_ids']) <= set(proposed_contract['case_ids']),
                'root revision outside migration task requirements/cases')
        require(all(Path(p).is_absolute() and Path(p).resolve().is_relative_to(Path(s['target_root'])) for p in candidate['write_paths']),
                'root write scope outside target')
        dimensions.allocation(s, candidate)
        if s.get('behavior_contract_required') and any(current[mid].get(key) != candidate.get(key) for key in ROOT_KEYS):
            import behavior_contract
            behavior_contract.review(candidate, candidate.get('behavior_review'))
    proposed = {mid: {**root, **updates.get(mid, {})} for mid, root in current.items()}
    paths = proposed_contract['global_paths']
    def covered(registry, global_paths):
        requirements = {rid for path in global_paths for rid in path.get('requirement_ids', [path['requirement_id']] if path.get('requirement_id') else [])}
        for mid, m in registry.items():
            requirements.update(m['scope']['requirement_ids'] if m.get('scope') else
                (rid for rid, owners in (s.get('global_plan') or {}).get('content', {}).get('requirement_owners', {}).items()
                 if set(decomposition.leaves(s, mid)).intersection(owners)))
        return requirements, {c for m in registry.values() for c in m['case_ids']} | {p['case_id'] for p in global_paths}
    # A registry that covered the task keeps covering it. One still being registered is judged when its global plan is accepted.
    if covered(current, s['global_paths']) == (set(s['requirement_ids']), set(s['case_ids'])):
        requirements, cases = covered(proposed, paths)
        require(requirements == set(proposed_contract['requirement_ids']), 'root revision loses requirement coverage')
        require(cases == set(proposed_contract['case_ids']), 'root revision loses case coverage')
    graph = {mid: set(m['dependencies']) for mid, m in proposed.items()}
    def visit(mid, trail):
        require(mid not in trail, 'root revision dependency cycle')
        require(mid in current or mid in s['modules'], 'unknown root dependency')
        for dep in graph.get(mid, s['modules'].get(mid, {}).get('dependencies', [])):
            owner = s['modules'].get(dep, {}).get('parent_module_id') or dep
            visit(owner, trail | {mid})
    for mid in graph:
        visit(mid, set())
    rows = keyed(report['modules'], 'module_id') if report['modules'] else {}  # no leaf yet: nothing to review
    require(set(rows) == set(s['modules']), 'run impact must review every leaf')
    affected = set()
    retired_requirements = {r['id'] for r in report.get('retirements', []) if r['kind'] == 'requirement'}
    retired_cases = {r['id'] for r in report.get('retirements', []) if r['kind'] == 'case'}
    for mid, row in rows.items():
        require(set(row) == {'module_id', 'action', 'reason', 'evidence_refs', 'resume_blocker_sha256'}, 'invalid run impact row')
        require(row['action'] in ('replan', 'revise', 'reverify', 'unchanged') and row['reason'], 'run impact action/reason required')
        for evidence in nonempty(row['evidence_refs'], 'run impact evidence'): check_ref(evidence)
        m = s['modules'][mid]
        if retired_requirements.intersection((m.get('scope') or {}).get('requirement_ids', [])) or retired_cases.intersection(m['case_ids']):
            require(row['action'] == 'replan', 'retired contract owners must replan')
        if row['action'] != 'unchanged':
            affected.add(mid)
            if row['action'] == 'revise':
                # The leaf keeps its code and revises its contract: only for a frozen leaf whose boundary the revision keeps.
                update = updates.get(mid) or {}
                require(m.get('freeze_id') and not m.get('blocked') and decomposition.boundary_kept(
                    m, {**m, **update}, m['dependencies'] if 'dependencies' not in update else
                    sorted({leaf for dep in update['dependencies'] for leaf in decomposition.leaves(s, dep)})),
                    'run impact revise needs a frozen, unblocked leaf whose boundary the revision keeps; replan otherwise')
            if row['action'] == 'reverify':
                require(m.get('freeze_id') and m.get('code_baseline'), 'reverify needs existing frozen code')
                require(set(patch) <= {'runtime', 'test_adapter'} and not updates and not report.get('global_spec_ref')
                    and not report.get('contract_patch'), 'contract/source changes require replan, not reverify')
                verify_plan(m['plan'])
        else:
            if m.get('plan'): verify_plan(m['plan'])
            require(not row['resume_blocker_sha256'], 'unchanged module cannot release blocker')
        if row['resume_blocker_sha256']:
            require(m.get('blocked') and row['resume_blocker_sha256'] == digest(m['blocked']), 'run blocker decision stale')
    spec_ref = report.get('global_spec_ref')
    if spec_ref:
        check_ref(spec_ref)
        require(spec_ref != s['global_spec'], 'global spec revision must change the specification')
    changed_roots = {mid for mid, update in updates.items() if any(current[mid].get(k) != update.get(k, current[mid].get(k)) for k in ROOT_KEYS - {'module_id'})}
    for mid in changed_roots:
        root, was = proposed[mid], current[mid]
        leaves = set(decomposition.leaves(s, mid))
        analysed = mid in s.get('module_groups', {}) and root.get('dimension_analysis_ref') and was.get('dimension_analysis_ref')
        if analysed and root['dimension_analysis_ref'] != was['dimension_analysis_ref']:
            added = set(dimensions.load(root['dimension_analysis_ref'], mid)[1]) - set(dimensions.load(was['dimension_analysis_ref'], mid)[1])
            require(not added or affected.intersection(leaves), 'root revision adds work no leaf is asked to take: '
                    + ', '.join(sorted(added)[:8]) + '; the leaf that takes it plans again')
        for leaf in leaves - affected:
            child = s['modules'][leaf]
            require(set(child['scope']['requirement_ids']) <= set(root['scope']['requirement_ids'])
                and set(child['case_ids']) <= set(root['case_ids'])
                and all(any(Path(p).resolve().is_relative_to(Path(w).resolve()) for w in root['write_paths']) for p in child['write_paths']),
                'retained child outside revised root boundary')
            if analysed and child.get('dimension_analysis_ref'):
                # A child stands under the revised root while the root has not changed what the child cites of it.
                found = dimensions.touched(root, *dimensions.load(child['dimension_analysis_ref'], leaf))
                require(not found, 'retained child %s cites what the revision changes (%s); its impact is replan or revise'
                        % (leaf, ', '.join(found[:8])))
            else:
                require(set(root['scope']['out']) <= set(child['scope']['out']), 'retained child outside revised root boundary')
    require(patch or spec_ref or changed_roots or any(m.get('realloc_request') for m in current.values()), 'empty run revision')
    return report, affected, changed_roots


def revise_context(root, s, patch, review, decision):
    if not patch:
        return s.get('project_context_ref')
    snapshot = copy.deepcopy(project_context.verify_snapshot(s['project_context_ref']))
    require(snapshot['run_id'] == s['run_id'] and Path(snapshot['run_root']).resolve() == root.resolve(), 'context belongs to another run')
    files = root / 'context/files'
    frozen = project_context.freeze_refs(files, patch)
    for key in project_context.DOCUMENTS:
        if key in patch:
            if patch[key] is None:
                snapshot['source_refs'].pop(key, None); snapshot['source_paths'].pop(key, None)
            else:
                from contracts import file_ref
                ref = project_context.copy_ref(files, file_ref(patch[key]))
                snapshot['source_refs'][key] = ref
                snapshot['source_paths'][key] = patch[key]
                frozen[key] = ref['path']
    if 'knowledge_paths' in patch:
        from contracts import file_ref
        refs = [project_context.copy_ref(files, file_ref(p)) for p in patch['knowledge_paths'] or []]
        snapshot['source_refs']['knowledge_paths'] = refs
        snapshot['source_paths']['knowledge_paths'] = patch['knowledge_paths'] or []
        frozen['knowledge_paths'] = [r['path'] for r in refs]
    snapshot['effective_config'] = project_context.merge(project_context.current_config(snapshot), frozen)
    snapshot.update(previous_context_ref=s['project_context_ref'], run_change_ref=review['report_ref'],
                    run_decision_ref=decision.get('human_source_ref', review['report_ref']))
    data = project_context.encoded(snapshot)
    project_context.archive(files, data, '.snapshot')
    return project_context.archive(root / 'context/revisions', data, '.json')


def handle(root, s, req, actor):
    from ledger import role, idle, open_change, replan_module, await_provider
    p = req['payload']
    if req['operation'] == 'run-review':
        role(actor, 'global-orchestrator')
        require(set(p) <= {'report_ref', 'context_ref'} and p.get('report_ref'), 'invalid run review payload')
        validate(s, p['report_ref'])
        s['run_change_review'] = {'report_ref': p['report_ref'], 'subject_sha256': subject(s, p['report_ref']),
                                  'reviewed_by': actor, 'status': 'reviewed'}
        return
    role(actor, 'host')
    require({'subject_sha256'} <= set(p) <= {'decision_id', 'subject_sha256'}, 'invalid run revision payload')
    review = s.get('run_change_review', {})
    require(review.get('status') == 'reviewed' and review['subject_sha256'] == p['subject_sha256'] == subject(s, review['report_ref']),
            'run impact review stale or missing')
    report, affected, changed_roots = validate(s, review['report_ref'])
    for mid in affected: idle(s['modules'][mid])
    decision = s['decisions'].get(p.get('decision_id'), {})
    needs_human = human_required(s, report)
    if needs_human or decision:
        require(decision.get('decision') == 'approved' and decision.get('module_id') is None and not decision.get('consumed', True)
            and decision.get('subject_sha256') == p['subject_sha256'], 'run revision requires exact human decision')
        check_ref(decision['human_source_ref'])
    previous = s.get('project_context_ref')
    previous_spec = s['global_spec']
    previous_contract = {key: copy.deepcopy(s[key]) for key in CONTRACT_KEYS}
    retirement_history = {}
    if report.get('retirements'):
        retirement_history = {'retirements': copy.deepcopy(report['retirements']),
            'decision_id': p['decision_id'], 'human_source_ref': decision['human_source_ref'],
            'retired_path_results': {r['id']: copy.deepcopy(s.get('audit_results', {}).get(r['id']))
                for r in report['retirements'] if r['kind'] == 'global-path'}}
    previous_plan = copy.deepcopy(s.get('global_plan'))
    import design_stage
    continuations = {mid: {'subject_sha256': design_stage.subject(s, m),
        'allocation_sha256': digest({key: m.get(key) for key in (*decomposition.ALLOCATION_KEYS, 'dependencies')}),
        'generation': m.get('design_generation', 0), 'review_ref': review['report_ref']}
        for mid, m in s['modules'].items() if mid not in affected}
    # Preserve reviewed unaffected execution inputs before replacing the shared context.
    import context_readiness
    context_readiness.pin_execution(root, s, affected)
    new_ref = revise_context(root, s, report['context_patch'], review, decision)
    rows = keyed(report['modules'], 'module_id') if report['modules'] else {}  # no leaf yet: nothing to review
    replanned = {mid for mid in affected if rows[mid]['action'] == 'replan'}
    for mid in decomposition.built_on(s, replanned) - affected:
        await_provider(s['modules'][mid])  # it keeps its plan and code and verifies again once its provider is back
    for mid, m in s['modules'].items():
        if mid in affected:
            if rows[mid]['action'] == 'reverify':
                m.setdefault('verification_history', []).append({'review_ref': review['report_ref'], 'results': copy.deepcopy(m['results'])})
                m.update(phase='testing', stale=True, build_baseline=None, build_artifacts=[])
                m.pop('execution_context_ref', None)
                m.pop('automation_retry_ready', None)
                for result in m['results'].values(): result['stale'] = True
            elif rows[mid]['action'] == 'revise':
                open_change(s, m, {'request_ref': review['report_ref'], 'impact_ref': review['report_ref'], 'upstream': True})
            else:
                replan_module(m, report['reason'], review['report_ref'], bool(rows[mid]['resume_blocker_sha256']))
            m.pop('realloc_request', None)
            s.get('audit_resolutions', {}).pop(mid, None)
        else:
            request = m.pop('realloc_request', None)
            if request and m['phase'] == 'waiting-upstream': m['phase'] = request['resume_phase']
            m['planning_continuation'] = {**continuations[mid], 'context_ref': new_ref}
            m['allocation_continuation'] = {'plan_hash': m.get('plan_hash'), 'review_ref': review['report_ref'], 'context_ref': new_ref}
        if mid in affected:
            if rows[mid]['action'] == 'reverify':
                m['allocation_continuation'] = {'plan_hash': m['plan_hash'], 'review_ref': review['report_ref'], 'context_ref': new_ref}
            m.pop('context_acceptances', None)
            m['revision'] += 1
    for update in report['root_updates']:
        mid = update['module_id']; m = roots(s)[mid]
        m.setdefault('allocation_history', []).append({'kind': 'planning-history', 'executable': False,
            **{k: copy.deepcopy(m.get(k)) for k in ROOT_KEYS}})
        m.update(copy.deepcopy(update))
        m['dependencies'] = sorted({leaf for dep in update['dependencies'] for leaf in decomposition.leaves(s, dep)})
        reached = sorted(affected.intersection(decomposition.leaves(s, mid)))
        if mid in s.get('module_groups', {}) and mid in changed_roots and reached:
            # The parent writes again only the children the revision reaches; the others stand and keep moving.
            m.update(replanning_required=True, replanning_children=reached)
            m.pop('redecomposition_submission', None)
    for group in s.get('module_groups', {}).values():
        group.pop('realloc_request', None)
        if affected.intersection(decomposition.leaves(s, group['module_id'])):
            group.pop('summary_ref', None); group.pop('summary_subject', None)
            group['revision'] += 1
    if new_ref:
        s['project_context_ref'] = new_ref
        if {'runtime', 'test_adapter'}.intersection(report['context_patch']):
            s['harmony_environment_revision'] = new_ref['sha256']
        snapshot = project_context.verify_snapshot(new_ref)
        s['new_architecture'] = snapshot['source_refs']['architecture_path']
        config = snapshot['effective_config']
        for key in ('build', 'test_adapter', 'runtime', 'target_resources'):
            if key in report['context_patch']:
                s[key] = copy.deepcopy(config.get(key, {}))
    if report.get('global_spec_ref'):
        s['global_spec'] = report['global_spec_ref']
    s.update(contract(s, report))
    for rid in retirement_history.get('retired_path_results', {}):
        s.get('audit_results', {}).pop(rid, None)
    old_paths = keyed(previous_contract['global_paths'], 'path_id') if previous_contract['global_paths'] else {}
    for path in s['global_paths']:
        prior = s.get('audit_results', {}).get(path['path_id'])
        if prior and old_paths.get(path['path_id']) != path:
            prior.update(stale=True, invalidated_by=review['report_ref'])
    if changed_roots or report.get('global_spec_ref') or 'architecture_path' in report['context_patch']:
        s['global_plan'] = None
    if s.get('audit'): s.setdefault('audit_history', []).append(copy.deepcopy(s['audit']))
    s['audit'] = {}
    s['context_acceptances'] = {}
    s.setdefault('run_change_history', []).append({**copy.deepcopy(review), **retirement_history,
        'kind': 'planning-history', 'executable': False, 'reason': report['reason'],
        'previous_context_ref': previous, 'project_context_ref': new_ref, 'previous_global_spec': previous_spec,
        'global_spec': s['global_spec'], 'previous_contract': previous_contract, 'previous_global_plan': previous_plan,
        'contract': {key: copy.deepcopy(s[key]) for key in CONTRACT_KEYS}, 'affected_modules': sorted(affected), 'changed_roots': sorted(changed_roots)})
    if report.get('lessons_ref'):
        s.setdefault('retrospectives', []).append({'lessons_ref': report['lessons_ref'], 'actor': review['reviewed_by']})
    if decision: decision['consumed'] = True
    review.update(status='applied', project_context_ref=new_ref, affected_modules=sorted(affected))


def human_required(s, report):
    return contract(s, report) != {k: s[k] for k in CONTRACT_KEYS} or control_policy.boundary(report.get('boundary_review'))


def next_action(s):
    review = s.get('run_change_review')
    if review and review.get('status') == 'reviewed':
        current = review['subject_sha256'] == subject(s, review['report_ref'])
        report = read_json(check_ref(review['report_ref']))
        affected = {row['module_id'] for row in report['modules'] if row['action'] != 'unchanged'}
        decision = next((d for d in s['decisions'].values() if not d.get('consumed') and d.get('module_id') is None
                         and d.get('subject_sha256') == review['subject_sha256']), None)
        needs_human = human_required(s, report)
        busy = any(not a.get('closed') for mid in affected for a in s['modules'].get(mid, {}).get('assignments', {}).values())
        import audit_closure
        auditing = workflow.audit_active(s) or audit_closure.active(s)
        return {'operation': 'revise-run' if current else 'run-review', 'role': 'host' if current else 'global-orchestrator',
            'ready': current and (bool(decision) or not needs_human) and not busy and not auditing,
            'reason': 'run-review-stale' if not current else 'run-approval-required' if needs_human and not decision
                      else 'wait-for-affected-workers' if busy else 'wait-for-audit' if auditing else 'run-context-switch-ready',
            'subject_sha256': review['subject_sha256'], 'report_ref': review['report_ref'],
            'payload': {'subject_sha256': review['subject_sha256'], **({'decision_id': decision['decision_id']} if decision else {})}}
    requests = [mid for mid, m in roots(s).items() if m.get('realloc_request')]
    if requests:
        return {'operation': 'run-review', 'role': 'global-orchestrator', 'ready': True,
                'reason': 'root-reallocation-requested', 'root_ids': requests}
    return None
