"""Planning acceptance and explicit execution contracts on the Ledger bus."""
import copy
from contracts import check_ref, digest, keyed, nonempty, read_json, require

def acceptance(paths):
    """Execution commands and labels are planning details; assertions and coverage remain frozen."""
    return [{key: value for key, value in path.items() if key not in ('name', 'command', 'preparation')}
            for path in paths]


def acceptance_hash(m):
    paths = m['plan']['paths']
    return digest(acceptance(paths))


def boundary(review):
    require(isinstance(review, dict), 'structured boundary_review required')
    require(review.get('unresolved_questions') == [], 'unresolved planning questions require human check')
    require(type(review.get('semantic_change')) is bool and type(review.get('authorization_change')) is bool,
            'boundary review must classify semantic and authorization changes')
    require(review.get('reason'), 'boundary review reason required')
    for ref in nonempty(review.get('evidence_refs'), 'boundary review evidence'): check_ref(ref)
    return review['semantic_change'] or review['authorization_change']


def technical_review(m, ref, actor=None):
    review = read_json(check_ref(ref))
    require(review.get('plan_hash') == m['plan_hash'], 'MO plan review stale')
    require(not boundary(review), 'semantic/authorization changes require exact human decision')
    require(review.get('reviewer_instance_id') and review['reviewer_instance_id'] not in
            m.get('spec_authors', []) + m.get('design_authors', []), 'MO review must be independent of plan authors')
    if actor: require(review['reviewer_instance_id'] == actor['instance_id'], 'MO review identity mismatch')
    require(not execution_started(m) or not m.get('approved_envelope') or m['approved_envelope'] == digest(m['plan']['decision_envelope']),
            'decision boundary changed; human decision required')
    require(not execution_started(m) or not m.get('approved_acceptance') or m['approved_acceptance'] == acceptance_hash(m),
            'acceptance changed; human decision required')
    return review


def execution_started(m):
    return bool(m.get('code_baseline') or any(a['role'] in ('implementer', 'fixer') and not a.get('declined_ref')
        and not (a.get('closed') and a.get('no_code_change_ref'))
        and (a.get('context_ref') or not a.get('preflight_pending')) for a in m['assignments'].values()))


def execution_contract(m, p):
    tasks = keyed(m['plan']['tasks'], 'task_id')
    paths = {row['path_id']: row for row in m['plan']['paths']}
    selected = nonempty(p.get('task_ids'), 'assignment task_ids')
    require(len(set(selected)) == len(selected) and set(selected) <= set(tasks), 'assignment unknown/duplicate TASK')
    selected_paths = nonempty(p.get('path_ids'), 'assignment path_ids')
    require(len(set(selected_paths)) == len(selected_paths) and set(selected_paths) <= set(paths) | set(m.get('repair_findings', {})),
            'assignment unknown/duplicate PATH')
    if p['role'] == 'test-runner' and p.get('test_scope') == 'build':
        import test_validation as tv
        require(set(selected_paths) == {pid for pid, row in paths.items() if row.get('kind') in tv.PRE}, 'build assignment must select build/unit/static PATHs')
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
    scope = sorted({path for tid in selected for path in (tasks[tid].get('scope') or {}).get('write_paths', m['write_paths'])})
    return {'plan_hash': m['plan_hash'], 'plan_ref': copy.deepcopy(m['plan_ref']), 'task_ids': selected,
            'path_ids': selected_paths, 'write_paths': [] if p['role'] == 'test-runner' else scope,
            'accepted_task_ids': copy.deepcopy(m.get('accepted_task_ids', [])),
            'accepted_code_files': copy.deepcopy(m.get('code_files', [])),
            'accepted_task_files': copy.deepcopy(m.get('task_files', {})),
            'permissions': 'test-only' if p['role'] == 'test-runner' else 'code',
            'evidence_required': 'execution-receipts' if p['role'] == 'test-runner' else 'task-trace-and-production-binding'}


def result_scope(module, assignment):
    contract = assignment.get('execution_contract')
    if not contract: return None
    require(contract['plan_hash'] == module['plan_hash'] and contract['plan_ref'] == module['plan_ref'], 'execution contract stale')
    return set(contract['task_ids'])
