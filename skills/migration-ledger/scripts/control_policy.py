"""Planning acceptance and explicit execution contracts on the Ledger bus."""
import copy
from pathlib import Path
from contracts import Rejected, check_ref, digest, keyed, nonempty, read_json, require

def acceptance(paths):
    """Execution commands and labels are planning details; assertions and coverage remain frozen."""
    return [{key: value for key, value in path.items() if key not in ('name', 'command', 'preparation')}
            for path in paths]


def acceptance_hash(m):
    paths = m['plan']['paths']
    return digest(acceptance(paths))


# What a path verifies and what each assertion expects; the rest of their text is how the test is exercised.
IDENTITY = ('path_id', 'case_id', 'requirement_id', 'requirement_ids', 'kind', 'platform', 'required', 'coverage', 'node_ids',
            'image_check_ids', 'interaction_id', 'unit_report', 'baseline_ref')
CORE = ('expected', 'matcher', 'verification', 'after_step')


def acceptance_digests(paths):
    """Per-path and per-assertion digests of the frozen acceptance: enough to verify that a revision keeps every expectation,
    without carrying the paths' text in the state."""
    return {path['path_id']: {'shape': digest({k: v for k, v in path.items() if k != 'expected_assertions'}),
                              'identity': digest({k: path.get(k) for k in IDENTITY}),
                              'assertions': {a['assertion_id']: digest(a) for a in path['expected_assertions']},
                              'core': {a['assertion_id']: digest({k: a.get(k) for k in CORE}) for a in path['expected_assertions']}}
            for path in acceptance(paths)}


def tests_revised(m):
    """The frozen paths whose exercise changed while what they verify did not: identity kept, every frozen assertion's
    expected / matcher / verification / after_step kept, nothing removed. Empty when the acceptance holds or really moved."""
    if preserves_acceptance(m):
        return []
    old = m.get('approved_acceptance_digests') or {}
    current = acceptance_digests(m['plan']['paths'])
    changed = []
    for pid, frozen in old.items():
        new = current.get(pid)
        if new is None or 'identity' not in frozen or new['identity'] != frozen['identity']:
            return []
        if any(new['core'].get(aid) != d for aid, d in frozen.get('core', {}).items()):
            return []
        if new['shape'] != frozen['shape'] or any(new['assertions'].get(aid) != d for aid, d in frozen['assertions'].items()):
            changed.append(pid)
    return changed if old else []


def preserves_acceptance(m):
    """Add coverage for original expectations; never erase or weaken frozen obligations."""
    if not m.get('approved_acceptance') or m['approved_acceptance'] == acceptance_hash(m): return True
    old = m.get('approved_acceptance_digests')
    if old is None: return False
    current = acceptance_digests(m['plan']['paths'])
    for path_id, frozen in old.items():
        new = current.get(path_id)
        if new is None or new['shape'] != frozen['shape']: return False
        if any(new['assertions'].get(aid) != d for aid, d in frozen['assertions'].items()): return False
    return bool(old)


# Reasons for which a step waits for a person's decision. Every other step proceeds on the roles' own review.
HUMAN_REASONS = ('human-decision-required', 'human-review-required', 'finding-awaits-human', 'run-approval-required',
                 'budget-exhausted', 'audit-budget-exhausted', 'await-delivery-authorization')


def human_required(step):
    """Whether this step cannot be taken until a person decides. A host asks nobody when it is False."""
    return not step.get('ready') and step.get('reason') in HUMAN_REASONS


def boundary(review):
    require(isinstance(review, dict), 'structured boundary_review required')
    require(review.get('unresolved_questions') == [], 'unresolved planning questions require human check')
    require(type(review.get('semantic_change')) is bool and type(review.get('authorization_change')) is bool,
            'boundary review must classify semantic and authorization changes')
    require(review.get('reason'), 'boundary review reason required')
    for ref in nonempty(review.get('evidence_refs'), 'boundary review evidence'): check_ref(ref)
    return review['semantic_change'] or review['authorization_change']


def boundary_hash(m):
    """What a person decides when approving a plan: its decision envelope and what it accepts. The rest of its text is
    reviewed by the MO."""
    return digest({'envelope': m['plan']['decision_envelope'], 'acceptance': acceptance(m['plan']['paths'])})


def content(value):
    """A plan value as what it says: a revision writes its files again, so a reference is the bytes it names, not where
    they lie."""
    if isinstance(value, dict):
        return value['sha256'] if set(value) == {'path', 'sha256'} else {k: content(v) for k, v in value.items()}
    return [content(v) for v in value] if isinstance(value, list) else value


def additions(m):
    """The TASKs and PATHs a revision of a coded plan only adds (an empty list when it adds nothing), or None when it changes
    anything that was frozen: every frozen PATH is as it was, every frozen TASK too except for PATHs added to it, the
    decision envelope stands and every frozen definition keeps all its lines."""
    before = ((m.get('change_request') or {}).get('previous_plan') or {}).get('plan')
    if not before or not m.get('plan') or content(before.get('decision_envelope')) != content(m['plan'].get('decision_envelope')):
        return None
    tasks, paths = keyed(m['plan']['tasks'], 'task_id'), keyed(m['plan']['paths'], 'path_id')
    for old in before['paths']:
        if content(paths.get(old['path_id'])) != content(old):
            return None
    for old in before['tasks']:
        new = tasks.get(old['task_id'])
        if not new or content({k: v for k, v in new.items() if k != 'path_ids'}) != content({k: v for k, v in old.items() if k != 'path_ids'}) \
                or not set(old['path_ids']) <= set(new['path_ids']):
            return None
    def kept(old, new):  # every line of the frozen text is still there, in order: the revision only adds to it
        lines = iter(check_ref(new).read_text().splitlines()) if new else iter(())
        return all(any(line == other for other in lines) for line in check_ref(old).read_text().splitlines())
    texts = {d['kind']: d for d in m['plan'].get('definitions') or []}
    if not all(kept(d, texts.get(d['kind'])) for d in before.get('definitions') or []):
        return None
    added = sorted(set(tasks) - {x['task_id'] for x in before['tasks']}) + sorted(set(paths) - {x['path_id'] for x in before['paths']})
    return added


def needs_human(m):
    """Why the MO's own review cannot freeze this plan, or None: code exists and the plan moved what was approved."""
    if not execution_started(m):
        return None
    if m.get('approved_envelope') and m['approved_envelope'] != digest(m['plan']['decision_envelope']):
        return 'decision boundary changed'
    return None if preserves_acceptance(m) or tests_revised(m) else 'acceptance changed'


def technical_review(m, ref, actor=None, decided=False):
    """`decided`: a person has approved this plan's decision boundary, so the review speaks for its text only."""
    review = read_json(check_ref(ref))
    require(review.get('plan_hash') == m['plan_hash'], 'MO plan review stale')
    require(not boundary(review), 'semantic/authorization changes require exact human decision')
    require(review.get('reviewer_instance_id') and review['reviewer_instance_id'] not in
            m.get('spec_authors', []) + m.get('design_authors', []), 'MO review must be independent of plan authors')
    if actor: require(review['reviewer_instance_id'] == actor['instance_id'], 'MO review identity mismatch')
    require(decided or not needs_human(m), str(needs_human(m)) + '; human decision required')
    import task_revalidation
    task_revalidation.prepare(m, ref)
    return review


def execution_started(m):
    return bool(m.get('code_baseline') or any(a['role'] in ('implementer', 'fixer') and not a.get('declined_ref')
        and not (a.get('closed') and a.get('no_code_change_ref'))
        and (a.get('context_ref') or not a.get('preflight_pending')) for a in m['assignments'].values()))


def repair_route(report):
    """Classify existing execution feedback; do not add a planning round."""
    cause = report.get('root_cause', {})
    category = cause.get('category') if isinstance(cause, dict) else cause
    inferred = ('upstream' if category in ('scope', 'scope-insufficient') else
                'spec' if category in ('spec', 'planning-gap', 'dependency-gap', 'function-gap', 'fidelity-gap', 'test-source') else 'fixer')
    route = report.get('repair_route', inferred)
    require(route in ('fixer', 'spec', 'upstream'), 'unknown repair_route')
    require(inferred == 'fixer' or route != 'fixer', 'planning/scope gap cannot route directly to Fixer')
    require(inferred != 'upstream' or route == 'upstream', 'scope gap requires upstream allocation review')
    return route


def repair_step(report):
    route = repair_route(report)
    if route == 'fixer': return None
    ref = report['diagnosis_ref']
    if route == 'spec':
        return {'operation': 'change', 'role': 'module-orchestrator', 'ready': True, 'reason': 'execution-feedback-spec-gap',
                'payload': {'request_ref': ref, 'impact_ref': report.get('impact_ref', ref)}}
    return {'operation': 'realloc-request', 'role': 'module-orchestrator', 'ready': True, 'reason': 'execution-feedback-scope-gap',
            'payload': {'reason': 'Execution feedback exceeds allocated scope', 'evidence_refs': [ref]}}


def execution_contract(m, p):
    tasks = keyed(m['plan']['tasks'], 'task_id')
    paths = {row['path_id']: row for row in m['plan']['paths']}
    selected = nonempty(p.get('task_ids'), 'assignment task_ids')
    require(len(set(selected)) == len(selected) and set(selected) <= set(tasks), 'assignment unknown/duplicate TASK')
    if p['role'] == 'implementer' and not p.get('path_ids'):  # an Implementer selects TASKs; their paths follow
        p['path_ids'] = sorted({pid for tid in selected for pid in tasks[tid].get('path_ids') or []})
    selected_paths = nonempty(p.get('path_ids'), 'assignment path_ids')
    require(len(set(selected_paths)) == len(selected_paths) and set(selected_paths) <= set(paths) | set(m.get('repair_findings', {})),
            'assignment unknown/duplicate PATH')
    if p['role'] == 'test-runner' and p.get('test_scope') == 'build':
        import test_validation as tv
        require(set(selected_paths) == {row['path_id'] for row in tv.due(m)}, 'build assignment must select build/unit/static PATHs due on the accepted TASKs')
    if p['role'] == 'implementer':
        require(not set(selected).intersection(m.get('accepted_task_ids', [])), 'TASK already implemented; use Fixer')
    if p['role'] == 'fixer':
        findings = nonempty(p.get('finding_ids'), 'Fixer finding_ids')
        known = set(m.get('repair_findings', {})) | {pid for pid, row in m.get('results', {}).items() if row['quality'] != 'green-passed'}
        known |= {row['finding_id'] for row in (m.get('diagnosis') or {}).get('findings', [])}
        known |= set((m.get('diagnosis') or {}).get('finding_ids', []))
        require(set(findings) <= known, 'Fixer findings outside accepted diagnosis')
        require(m.get('diagnosis'), 'Fixer accepted diagnosis required')
    require(set(selected_paths) <= {pid for tid in selected for pid in tasks[tid]['path_ids']} | set(m.get('repair_findings', {})),
            'assignment PATH outside selected TASKs')
    import prepared_tests
    scope = sorted({path for tid in selected for path in (tasks[tid].get('scope') or {}).get('write_paths', m['write_paths'])}
                   | (set(prepared_tests.frozen_paths(m, set(selected))) if p['role'] != 'test-runner' else set()))
    return {'plan_hash': m['plan_hash'], 'plan_ref': copy.deepcopy(m['plan_ref']), 'task_ids': selected,
            'path_ids': selected_paths, 'write_paths': [] if p['role'] == 'test-runner' else scope,
            'accepted_task_ids': copy.deepcopy(m.get('accepted_task_ids', [])),
            'accepted_code_files': copy.deepcopy(m.get('code_files', [])),
            'accepted_task_files': copy.deepcopy(m.get('task_files', {})),
            'permissions': 'test-only' if p['role'] == 'test-runner' else 'code',
            'evidence_required': 'execution-receipts' if p['role'] == 'test-runner' else 'task-trace-and-production-binding'}


def submission(m, task_ids):
    """What the Ledger asks of the implementation a dispatch returns, listed before the work: the selected TASKs'
    trace, the full code manifest, production binding, diagnostics, one trace per selected reuse mapping and, when
    the plan completes, evidence per four-dimension item (UI items with a baseline name what guided them)."""
    plan = m['plan']
    out = {'task_trace': sorted(task_ids), 'code_files': 'complete manifest', 'production_binding_evidence': 'ref',
           'authoring_diagnostics': 'host diagnostics of the changed files', 'complete': set(task_ids) | set(m.get('accepted_task_ids', [])) >= {t['task_id'] for t in plan['tasks']}}
    try:
        if plan.get('reuse_plan_ref'):
            out['reuse_trace'] = sorted(r['mapping_id'] for r in read_json(check_ref(plan['reuse_plan_ref']))['mappings'] if r['decision'] != 'new')
        if plan.get('dimension_analysis_ref'):
            import dimensions
            _, items = dimensions.load(plan['dimension_analysis_ref'], m['module_id'])
            out['dimension_evidence'] = {'items': sorted(items),
                'ui_guided': sorted(iid for iid, item in items.items() if (item.get('semantic_model') or {}).get('ui_evidence')),
                'resources': sorted(iid for iid, item in items.items() if item['dimension'] == 'Resource' and item.get('resource_strategy') != 'blocked')}
        import prepared_tests
        design = prepared_tests.source(m)
        if design:
            held = {pid for t in plan['tasks'] if t['task_id'] in task_ids for pid in t.get('path_ids', [])}
            out['frozen_tests'] = [{'target_path': a['target_path'], 'sha256': a['ref']['sha256']}
                                   for a in prepared_tests.assets(read_json(check_ref(design['test_design_ref'])))
                                   if a['kind'] == 'test-source' and held & set(a['path_ids'])]
    except (Rejected, OSError, KeyError, TypeError):
        pass  # a reference that no longer resolves is the submit's rejection, not the step's
    return out


def result_scope(module, assignment):
    contract = assignment.get('execution_contract')
    if not contract: return None
    require(contract['plan_hash'] == module['plan_hash'] and contract['plan_ref'] == module['plan_ref'], 'execution contract stale')
    return set(contract['task_ids'])
