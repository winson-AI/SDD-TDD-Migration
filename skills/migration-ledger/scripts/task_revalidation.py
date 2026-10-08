"""Optional, MO-reviewed independence proof for a same-Run SPEC repair.

Execution receipts keep their original baseline. Only unchanged, already Green
paths can be carried forward; build/unit/static gates always run on new code.
"""
import copy
import json
import re
from pathlib import Path
from contracts import check_ref, keyed, read_json, require


def overlap(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    return a.is_relative_to(b) or b.is_relative_to(a)


def prepare(m, review_ref):
    full = {'mode': 'full', 'reason': 'independence-not-proven', 'retained_task_ids': [], 'retained_path_ids': []}
    try:
        review = read_json(check_ref(review_ref)) if review_ref else {}
    except json.JSONDecodeError:
        return full  # Existing human/batch review may be prose, without an isolation proof.
    if not isinstance(review, dict): return full
    ref = review.get('task_independence_ref')
    change = m.get('change_request')
    if not ref or not change: return full
    proof = read_json(check_ref(ref))
    require(review.get('plan_hash') == m['plan_hash'] and review.get('reviewer_instance_id') not in
            m.get('spec_authors', []) + m.get('design_authors', []), 'TASK independence needs current independent MO review')
    require(proof.get('schema_version') == 1 and proof.get('from_freeze_id') == change['from_freeze_id']
            and proof.get('to_plan_hash') == m['plan_hash'], 'TASK independence proof stale')
    require(proof.get('reviewer_instance_id') == review.get('reviewer_instance_id'), 'TASK independence reviewer mismatch')
    old, new = change['previous_plan']['plan'], m['plan']
    before, after = keyed(old['tasks'], 'task_id'), keyed(new['tasks'], 'task_id')
    # A revision may leave every TASK as it was (the allocation gained evidence, the contract did not move): none is affected.
    affected = set(proof.get('affected_task_ids', []))
    require(affected <= set(before) | set(after), 'TASK independence affected set invalid')
    require({tid for tid in set(before) | set(after) if before.get(tid) != after.get(tid)} <= affected,
            'TASK independence omits changed TASK')
    retained = set(after) - affected
    if not retained or not retained <= set(m.get('accepted_task_ids', [])): return full
    rows = keyed(proof.get('tasks'), 'task_id')
    require(set(rows) == set(before) | set(after), 'TASK independence requires all task read/dependency boundaries')
    writes = {}
    for tid, row in rows.items():
        task = after.get(tid, before.get(tid))
        scope = (task.get('scope') or {}).get('write_paths')
        if not scope: return full
        require(all(Path(p).is_absolute() and any(overlap(p, root) and Path(p).resolve().is_relative_to(Path(root).resolve())
                    for root in m['write_paths']) for p in scope), 'TASK independence write scope invalid')
        writes[tid] = sorted(set(scope + (before.get(tid, {}).get('scope') or {}).get('write_paths', [])))
        require(isinstance(row.get('depends_on'), list) and set(row['depends_on']) <= set(rows)
                and isinstance(row.get('input_refs'), list), 'TASK independence inputs/dependencies required')
        for evidence in row.get('evidence_refs', []): check_ref(evidence)
        require(row.get('evidence_refs'), 'TASK independence source/runtime isolation evidence required')
        for item in row['input_refs']: check_ref(item)
    # Shared writers, read-after-write dependencies or a cross-task execution path
    # cannot be treated as independent, even when a reviewer claims otherwise.
    for tid in retained:
        seen, pending = set(), list(rows[tid]['depends_on'])
        while pending:
            dep = pending.pop()
            if dep in seen: continue
            seen.add(dep); pending += rows[dep]['depends_on']
        reads = [r['path'] for r in rows[tid]['input_refs']]
        if seen & affected or any(overlap(p, q) for aid in affected for q in writes[aid]
                                  for p in writes[tid] + reads): return {**full, 'reason': 'shared-task-impact'}
    old_paths, paths = keyed(old['paths'], 'path_id'), keyed(new['paths'], 'path_id')
    wanted = {pid for tid in retained for pid in after[tid]['path_ids'] if paths[pid].get('kind') not in ('build', 'unit', 'static')}
    changed_paths = {pid for tid in affected if tid in after for pid in after[tid]['path_ids']
                     if paths[pid].get('kind') not in ('build', 'unit', 'static')}
    if wanted & changed_paths or any(old_paths.get(pid) != paths[pid] for pid in wanted): return {**full, 'reason': 'shared-or-changed-path'}
    def assets(plan):
        ref = plan.get('test_design_ref')
        rows = read_json(check_ref(ref)).get('test_assets', []) if ref else plan.get('test_assets', [])
        return {pid: [a for a in rows if pid in a.get('path_ids', [])] for pid in wanted}
    if assets(old) != assets(new): return {**full, 'reason': 'changed-test-assets'}
    # This evidence covers shared SPEC/design edits as well as runtime/resource
    # inputs: the MO must explicitly identify unchanged task semantics.
    require(set(proof.get('unchanged_task_ids', [])) == retained, 'TASK independence unchanged semantics review required')
    def requirements(plan):
        blocks = {}
        for definition in plan['definitions']:
            if definition['kind'] != 'spec': continue
            for block in re.split(r'(?m)^### Requirement:\s*', check_ref(definition).read_text())[1:]:
                ids = re.findall(r'(?m)^Requirement-ID:\s*(\S+)\s*$', block)
                if len(ids) == 1: blocks.setdefault(ids[0], []).append(block.strip())
        return blocks
    old_defs = [d for d in old['definitions'] if d['kind'] == 'spec']
    new_defs = [d for d in new['definitions'] if d['kind'] == 'spec']
    if old_defs != new_defs:
        a, b = requirements(old), requirements(new)
        reqs = {rid for tid in retained for rid in after[tid]['requirement_ids']}
        if any(rid not in a or a[rid] != b.get(rid) for rid in reqs): return {**full, 'reason': 'shared-spec-impact'}
    protected = {str(Path(p).resolve()) for tid in retained for p in m.get('task_files', {}).get(tid, [])}
    if not protected or any(not m.get('task_files', {}).get(tid) for tid in retained): return full
    code = {r['path']: r for r in m['code_files']}
    require(protected <= set(code), 'TASK independence code trace incomplete')
    refs = list({r['path']: r for r in [code[p] for p in protected] +
                 [r for tid in retained for r in rows[tid]['input_refs']]}.values())
    for item in refs: check_ref(item)
    source = {**m, 'plan_hash': change['previous_plan']['plan_hash'], 'task_revalidation': change.get('previous_revalidation') or {}}
    current(source)
    keep = sorted(pid for pid in wanted if m.get('results', {}).get(pid, {}).get('quality') == 'green-passed'
                  and m['results'][pid].get('executed') and valid(source, m['results'][pid]))
    return {'mode': 'partial', 'proof_ref': ref, 'plan_hash': m['plan_hash'], 'from_freeze_id': change['from_freeze_id'],
            'retained_task_ids': sorted(retained), 'retained_path_ids': keep, 'protected_refs': refs}


def current(m):
    proof = m.get('task_revalidation') or {}
    if proof.get('mode') != 'partial': return
    require(proof['plan_hash'] == m['plan_hash'], 'TASK independence binding stale')
    check_ref(proof['proof_ref'])
    for ref in proof['protected_refs']: check_ref(ref)


def carry(m, previous):
    """Mark validity separately from the original receipt and execution baseline."""
    proof = m.get('task_revalidation') or {}
    keep = set(proof.get('retained_path_ids', []))
    current(m)
    for pid, row in m['results'].items():
        old = previous.get(pid)
        if pid in keep and old and old.get('quality') == 'green-passed' and not old.get('stale'):
            row.update(stale=False, validation_reuse={'proof_ref': copy.deepcopy(proof['proof_ref']),
                'plan_hash': m['plan_hash'], 'valid_for_baseline': m['code_baseline'],
                'source_code_baseline': old.get('code_baseline'), 'source_test_run_id': old['test_run_id']})


def valid(m, row):
    if row.get('stale'): return False
    if row.get('code_baseline', m.get('code_baseline')) == m.get('code_baseline'): return True
    reuse, proof = row.get('validation_reuse') or {}, m.get('task_revalidation') or {}
    return bool(proof.get('mode') == 'partial' and row.get('path_id') in proof['retained_path_ids']
                and reuse.get('proof_ref') == proof['proof_ref'] and reuse.get('plan_hash') == m['plan_hash']
                and reuse.get('valid_for_baseline') == m['code_baseline'] and row.get('quality') == 'green-passed')
