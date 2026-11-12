"""What a screen's files and parameters become in the target follows from its UI evidence and the project's conventions:
the copy plan and the parameter sheet are derived, never authored, and the copies and the generated parameter file are
the frozen plan's bytes. So the Ledger derives the two when a plan is submitted without them, and `advance` copies the
files and writes the parameter file in the coder's name when a coder is dispatched; the coder names them in its code."""
import fcntl
import hashlib
from pathlib import Path

from contracts import Drifted, Rejected, check_ref, file_ref, read_json, require
import project_context
import run_storage


def bind(s, m, plan, root):
    """The plan with the copy plan and the parameter sheet its analysis does not name yet, derived under the project's
    conventions and bound to a copy of that analysis; the plan unchanged when nothing follows or it already names them."""
    import resource_copy
    import ui_parameters
    rules, ref = s.get('target_resources') or {}, plan.get('dimension_analysis_ref') if isinstance(plan, dict) else None
    if not ref or root is None or not (rules.get('copy') or rules.get('parameters')):
        return plan
    try:
        analysis = read_json(check_ref(ref))
    except (Rejected, OSError, ValueError):
        return plan  # the gates report an analysis that cannot be read
    rows = {row.get('dimension'): row for row in analysis.get('dimensions', []) if row.get('status') == 'applicable'}
    folder = Path(root) / 'reports' / 'resources' / m['module_id']
    bound = False
    try:
        if rules.get('copy') and 'Resource' in rows and not rows['Resource'].get('copy_plan_ref'):
            derived, _ = resource_copy.derive(analysis, rules['copy'])
            if derived['renditions']:
                rows['Resource']['copy_plan_ref'] = save(root, folder, derived, '.copy-plan.json')
                bound = True
        if rules.get('parameters') and 'UI' in rows and not rows['UI'].get('parameter_sheet_ref'):
            sheet = ui_parameters.derive(analysis, rules['parameters'])
            if sheet.get('parameters'):
                rows['UI']['parameter_sheet_ref'] = save(root, folder, sheet, '.parameter-sheet.json')
                bound = True
    except (Rejected, OSError, ValueError, KeyError, TypeError):
        return plan  # evidence the derivation cannot read: the planner's tools say why
    if not bound:
        return plan
    derived_ref = save(root, folder, analysis, '.analysis.json')
    plan['dimension_analysis_ref'] = derived_ref
    for task in plan.get('tasks') or []:
        if (task.get('dimension_analysis') or {}).get('parent_ref') == ref:
            task['dimension_analysis']['parent_ref'] = derived_ref
    return plan


def save(root, folder, value, suffix):
    folder = run_storage.checked_path(folder, root)
    return project_context.archive(folder, project_context.encoded(value), suffix)


def generated_files(analysis):
    import parameter_file
    import ui_parameters
    document = ui_parameters.load(analysis)
    return (parameter_file.render(document, parameter_file.declarations(analysis))
            if document and document.get('convention') else ({}, []))


def unique_outputs(paths):
    resolved = [Path(path).resolve() for path in paths]
    require(len(set(resolved)) == len(resolved), 'copied resources and generated parameters need distinct target paths')


def output_hashes(plan):
    """The expected bytes of derived outputs after the whole implementation has been accepted."""
    import resource_copy
    ref = plan.get('dimension_analysis_ref')
    if not ref:
        return {}
    analysis = read_json(check_ref(ref))
    rows = resource_copy.rows(analysis)
    generated, _ = generated_files(analysis)
    unique_outputs([row['target_path'] for row in rows] + list(generated))
    hashes = {row['target_path']: row['source_ref']['sha256'] for row in rows}
    hashes.update({path: hashlib.sha256(text.encode('utf-8')).hexdigest() for path, text in generated.items()})
    return hashes


def owned_outputs(m, assignment, paths, task_id=None):
    """Bind each selected output to a TASK in this assignment and to its write scope."""
    contract = assignment['execution_contract']
    selected = contract['task_ids']
    if task_id is not None:
        require(any(task['task_id'] == task_id for task in m['plan']['tasks']), 'resource-sync requires a frozen task_id')
        require(task_id in selected, 'resource task outside the assigned TASKs')
        selected = [task_id]
    task_scopes = {task['task_id']: (task.get('scope') or {}).get('write_paths', m['write_paths'])
                   for task in m['plan']['tasks'] if task['task_id'] in selected}
    scopes = [m['write_paths'], contract.get('write_paths', m['write_paths'])]
    def inside(path, roots):
        return any(path.is_relative_to(Path(root).resolve()) for root in roots)
    return {name: owners[0] for name in paths
            if all(inside(Path(name).resolve(), scope) for scope in scopes)
            and (owners := [tid for tid, roots in task_scopes.items() if inside(Path(name).resolve(), roots)])}


def needs_sync(m, a):
    import resource_copy
    ref = (m.get('plan') or {}).get('dimension_analysis_ref')
    if not ref:
        return False
    analysis = read_json(check_ref(ref))
    copy_ref = resource_copy.plan_ref(analysis)
    if not copy_ref and not any(row.get('parameter_sheet_ref') for row in analysis['dimensions']):
        return False
    targets = [row['target_path'] for row in resource_copy.rows(analysis)] + list(generated_files(analysis)[0])
    return bool(owned_outputs(m, a, targets))


def attempts(root, a):
    from lean_worker import identifier
    instance = identifier(a['instance_id'])
    aid = identifier(a['assignment_id'])
    parent = run_storage.checked_path(Path(root) / 'staging' / instance, Path(root) / 'staging')
    prefix = f'advance-resource-sync-{aid}'
    paths = [parent / prefix]
    paths.extend(sorted((p for p in parent.glob(prefix + '-retry-*') if p.name.rsplit('-', 1)[-1].isdigit()),
                        key=lambda path: int(path.name.rsplit('-', 1)[-1])))
    return parent, prefix, [path for path in paths if path.is_dir()]


def ready_receipt(root, m, a, *, verify_outputs=False):
    _, _, previous = attempts(root, a)
    if not previous:
        return None
    receipt_path = previous[-1] / 'receipt.json'
    if not receipt_path.is_file():
        return None
    receipt = read_json(receipt_path)
    if receipt.get('status') != 'produced':
        return None
    request = read_json(check_ref(receipt['request_ref']))
    require(all(request.get(k) == v for k, v in {
        'operation': 'resource-sync', 'module_id': m['module_id'], 'assignment_id': a['assignment_id'],
        'fencing_token': a['fencing_token'], 'args': {}}.items()), 'resource-sync receipt does not belong to the active assignment')
    result = read_json(check_ref(receipt['result_ref']))
    require(result.get('status') == 'SYNCED', 'resource-sync result is incomplete')
    if verify_outputs:
        for ref in [*(row['target_ref'] for row in result['rows']), *result['parameter_files']]:
            check_ref(ref)
    return {'receipt_ref': file_ref(receipt_path), 'result_ref': receipt['result_ref']}


def sync(root, s, module_id, assignment_id):
    """Perform one fenced sync attempt. A completed attempt can be resumed without rewriting its files."""
    import lean_worker
    m = s['modules'][module_id]
    a = m['assignments'][assignment_id]
    require(not a.get('closed') and a['role'] in ('implementer', 'fixer')
            and a.get('freeze_id') == m.get('freeze_id'), 'resource sync needs an active coding assignment')
    if not needs_sync(m, a):
        return None
    parent, prefix, _ = attempts(root, a)
    parent.mkdir(parents=True, exist_ok=True)
    with (parent / (prefix + '.lock')).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Rejected('resource sync is already running for this assignment') from None
        try:
            prior = ready_receipt(root, m, a, verify_outputs=True)
        except Drifted:
            prior = None
        if prior:
            return prior
        _, _, previous = attempts(root, a)
        rid = prefix if not previous else prefix + f'-retry-{len(previous)}'
        request = {'request_id': rid, 'operation': 'resource-sync', 'module_id': module_id,
                   'assignment_id': assignment_id, 'fencing_token': a['fencing_token'], 'args': {}}
        result = lean_worker.run(root, request, {'role': a['role'], 'instance_id': a['instance_id']})
        return {key: result[key] for key in ('receipt_ref', 'result_ref')}
