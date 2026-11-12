"""Optional, MO-reviewed independence proof for a same-Run SPEC repair.

Execution receipts keep their original baseline. Only unchanged, already Green
paths can be carried forward; build/unit/static gates always run on new code.
"""
import copy
import json
import re
from pathlib import Path
from contracts import Rejected, baseline, check_ref, file_ref, keyed, read_json, require


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
    from control_policy import content  # rewritten files with the same bytes are the same PATH
    if wanted & changed_paths or any(content(old_paths.get(pid)) != content(paths[pid]) for pid in wanted): return {**full, 'reason': 'shared-or-changed-path'}
    def assets(plan):
        ref = plan.get('test_design_ref')
        rows = read_json(check_ref(ref)).get('test_assets', []) if ref else plan.get('test_assets', [])
        return {pid: [a for a in rows if pid in a.get('path_ids', [])] for pid in wanted}
    if content(assets(old)) != content(assets(new)): return {**full, 'reason': 'changed-test-assets'}
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
    def kept(old, new):  # every line of the old block is still there, in order: the revision only adds to it
        lines = iter((new or '').splitlines())
        return all(any(line == other for other in lines) for line in old.splitlines())
    if old_defs != new_defs:
        a, b = requirements(old), requirements(new)
        reqs = {rid for tid in retained for rid in after[tid]['requirement_ids']}
        same = (lambda x, y: kept(x, y)) if proof.get('written_by') == 'ledger' else (lambda x, y: x == y)  # the Ledger proves additions only
        if any(rid not in a or len(a[rid]) != len(b.get(rid) or []) or not all(same(x, y) for x, y in zip(a[rid], b.get(rid) or []))
               for rid in reqs): return {**full, 'reason': 'shared-spec-impact'}
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


def plan_inputs(plan):
    from control_policy import content
    generated = {'definitions', 'paths', 'reuse_plan_ref', 'test_design_ref', 'test_asset_contract_version'}
    reuse = plan.get('reuse_plan_ref')
    return content({k: v for k, v in plan.items() if k not in generated}), content(read_json(check_ref(reuse)) if reuse else {})


def test_design(plan):
    ref = plan.get('test_design_ref')
    doc = read_json(check_ref(ref)) if ref else {}
    doc.pop('subject_sha256', None)
    return doc


def documentation_delta(m):
    """A revision that keeps every frozen input and only adds standalone trace IDs."""
    from control_policy import additions, content

    change = m.get('change_request') or {}
    if not change.get('documentation_only'):
        return False
    old, new = change['previous_plan']['plan'], m['plan']
    try:
        if additions(m) != [] or plan_inputs(old) != plan_inputs(new) or content(test_design(old)) != content(test_design(new)):
            return False
        if old.get('test_asset_contract_version') != new.get('test_asset_contract_version'):
            return False
        ids = {row['item_id'] for row in old['dimension_trace']}
        before, after = keyed(old['definitions'], 'kind'), keyed(new['definitions'], 'kind')
        if set(before) != set(after):
            return False
        for kind in before:
            a, b = (check_ref(d).read_text() for d in (before[kind], after[kind]))
            if a == b:
                continue
            if kind not in ('spec', 'design', 'tasks'):
                return False
            meaningful = lambda text: [line for line in text.splitlines() if set(line.split()) - ids]
            if meaningful(a) != meaningful(b):
                return False
        return True
    except (Rejected, OSError, ValueError, TypeError, KeyError):
        return False


def added_test_assets(m):
    """Identify pending PATHs completed solely by adding execution-side test assets."""
    from control_policy import content
    from design_stage import definition_kind
    import prepared_tests

    change = m.get('change_request')
    if not change:
        return set()
    old, new = change['previous_plan']['plan'], m['plan']
    try:
        pending = set(prepared_tests.pending_paths(old['paths']))
        if not pending or plan_inputs(old) != plan_inputs(new):
            return set()
        before, after = [keyed(p['paths'], 'path_id') for p in (old, new)]
        without_preparation = lambda rows: content({pid: {k: v for k, v in p.items() if k != 'preparation'}
                                                    for pid, p in rows.items()})
        if without_preparation(before) != without_preparation(after):
            return set()
        changed = {pid for pid in before if content(before[pid].get('preparation')) != content(after[pid].get('preparation'))}
        if not changed or not changed <= pending or changed.intersection(prepared_tests.pending_paths(new['paths'])):
            return set()
        old_design, new_design = test_design(old), test_design(new)
        design_metadata = lambda doc: content({k: v for k, v in doc.items() if k not in ('paths', 'test_assets')})
        if not old_design or not new_design or design_metadata(old_design) != design_metadata(new_design):
            return set()
        previous, current_assets = [{asset['asset_id']: asset for asset in prepared_tests.assets(doc)}
                                    for doc in (old_design, new_design)]
        if any(content(asset) != content(current_assets.get(aid)) for aid, asset in previous.items()):
            return set()
        added = [asset for aid, asset in current_assets.items() if aid not in previous]
        if any(asset['kind'] == 'test-source' for asset in added) or {pid for asset in added for pid in asset['path_ids']} != changed:
            return set()
        definitions = lambda plan: {(d['kind'], d['sha256']) for d in plan['definitions']}
        projected = {(definition_kind(asset['kind']), asset['ref']['sha256']) for asset in added}
        if definitions(new) != definitions(old) | projected:
            return set()
        return changed
    except (Rejected, OSError, ValueError, TypeError, KeyError):
        return set()


def prior_green_receipt(m, path_id):
    row = m['results'].get(path_id) or {}
    if row.get('quality') != 'green-passed' or not row.get('executed') or row.get('stale'):
        return None
    receipt = read_json(check_ref(row['execution_receipt']))
    change = m['change_request']
    if receipt['code_baseline'] != m['code_baseline'] or receipt['test_run_id'] != row['test_run_id'] or receipt['path_id'] != path_id:
        return None
    if receipt['freeze_id'] != change['from_freeze_id']:
        reuse, previous = row.get('validation_reuse', {}), change.get('previous_revalidation') or {}
        if (reuse.get('plan_hash') != change['previous_plan']['plan_hash'] or reuse.get('source_test_run_id') != row['test_run_id']
                or reuse.get('valid_for_baseline') != m['code_baseline'] or not previous.get('proof_ref')
                or reuse.get('proof_ref') != previous['proof_ref']):
            return None
        check_ref(previous['proof_ref'])
    for key in ('result_ref', 'query_ref', 'log_ref'):
        check_ref(receipt[key])
    return receipt


def command_receipts(s, m, root, paths):
    from runner_storage import revalidation_inputs, revalidation_snapshot
    from functools import cache

    snapshot = cache(lambda: revalidation_snapshot(s, root))
    import unit_reports

    if not m.get('build_baseline') or m['build_baseline'] != m['code_baseline']:
        return []
    try:
        if baseline(m['code_files']) != m['code_baseline'] or any(file_ref(ref['path']) != ref for ref in m['build_artifacts']):
            return []
        retained = []
        for path in paths:
            pid = path['path_id']
            receipt = prior_green_receipt(m, pid)
            command = path['command']
            fingerprint = (receipt or {}).get('revalidation_inputs_sha256')
            if not fingerprint or fingerprint != revalidation_inputs(s, root, command['cwd'], command['argv'], snapshot=snapshot):
                continue
            if path.get('unit_report'):
                unit_reports.validate(receipt, path, read_json(check_ref(receipt['result_ref'])))
            retained.append(pid)
        return retained
    except (Rejected, OSError, ValueError, TypeError, KeyError):
        return []  # Unavailable or drifted evidence falls back to the ordinary verification gates.


def current_build_paths(s, m, root, candidates):
    """Recheck the same freeze, accepted bytes, frozen command and host inputs for each reusable build."""
    from runner_storage import revalidation_inputs, revalidation_snapshot
    from functools import cache

    snapshot = cache(lambda: revalidation_snapshot(s, root))

    if root is None or not candidates:
        return set()
    retained = set()
    for path in m['plan']['paths']:
        pid = path['path_id']
        if pid not in candidates:
            continue
        row = m['results'].get(pid) or {}
        if row.get('stale') or row.get('quality') != 'green-passed' or row.get('code_baseline') != m['code_baseline']:
            continue
        try:
            receipt = read_json(check_ref(row['execution_receipt']))
            command = path['command']
            expected = {'producer': 'host-executor', 'run_id': s['run_id'], 'module_id': m['module_id'],
                        'path_id': pid, 'test_run_id': row['test_run_id'], 'freeze_id': m['freeze_id'],
                        'code_baseline': m['code_baseline'], 'requested_argv': command['argv'],
                        'cwd': str(Path(command['cwd']).resolve())}
            fingerprint = receipt.get('revalidation_inputs_sha256')
            if not fingerprint or any(receipt.get(k) != v for k, v in expected.items()):
                continue
            if fingerprint != revalidation_inputs(s, root, command['cwd'], command['argv'], snapshot=snapshot):
                continue
            result = read_json(check_ref(receipt['result_ref']))
            require(result.get('build_artifacts', []) == row.get('build_artifacts', []), 'accepted build artifacts changed')
            for ref in [receipt['query_ref'], receipt['log_ref'], *row.get('build_artifacts', [])]:
                check_ref(ref)
            retained.add(pid)
        except (Rejected, OSError, ValueError, KeyError, TypeError):
            continue
    return retained


def reusable_build(s, m, root):
    """Keep build/unit receipts across a refreeze that only adds trace IDs."""
    if not documentation_delta(m):
        return []
    paths = [p for p in m['plan']['paths'] if p.get('kind') in ('build', 'unit')]
    retained = command_receipts(s, m, root, paths)
    return retained if len(retained) == len(paths) else []


def retain_after_test_assets(s, m, root):
    changed = added_test_assets(m)
    if not changed or not m.get('accepted_task_ids') or not m.get('code_baseline'):
        return None, []
    try:
        if baseline(m['code_files']) != m['code_baseline']:
            return None, []
    except (Rejected, OSError):
        return None, []
    change = m['change_request']
    paths = m['plan']['paths']
    unaffected = [p for p in paths if p['path_id'] not in changed]
    builds = {p['path_id'] for p in paths if p.get('kind') == 'build'}
    commands = command_receipts(s, m, root, [p for p in unaffected if p.get('kind') in ('build', 'unit')])
    same_inputs = bool(builds) and builds <= set(commands)
    keep, static = [], []
    if same_inputs:
        for path in unaffected:
            if path.get('kind') in ('build', 'unit'):
                continue
            pid = path['path_id']
            try:
                if prior_green_receipt(m, pid):
                    (static if path.get('kind') == 'static' else keep).append(pid)
            except (Rejected, OSError, ValueError, KeyError, TypeError):
                continue
    return {'mode': 'partial', 'reason': 'test-assets-only', 'proof_ref': m['plan_ref'],
            'plan_hash': m['plan_hash'], 'from_freeze_id': change['from_freeze_id'],
            'retained_task_ids': list(m['accepted_task_ids']), 'retained_path_ids': keep,
            'protected_refs': list(m['code_files'])}, (commands + static if same_inputs else [])


def carry(m, previous, retained_build=()):
    """Mark validity separately from the original receipt and execution baseline."""
    proof = m.get('task_revalidation') or {}
    keep = set(proof.get('retained_path_ids', [])) | set(retained_build)
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
