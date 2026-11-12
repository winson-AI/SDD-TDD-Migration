"""What a screen's files and parameters become in the target follows from its UI evidence and the project's conventions:
the copy plan and the parameter sheet are derived, never authored, and the copies and the generated parameter file are
the frozen plan's bytes. So the Ledger derives the two when a plan is submitted without them, and `advance` copies the
files and writes the parameter file in the coder's name when a coder is dispatched; the coder names them in its code."""
import hashlib
from pathlib import Path

from contracts import Rejected, check_ref, read_json, require
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


def sync(root, s, module_id, assignment_id):
    """Synchronize all derived outputs owned by this coder's current assignment."""
    import lean_worker
    import resource_copy
    m = s['modules'][module_id]
    a = m['assignments'][assignment_id]
    try:
        ref = m['plan'].get('dimension_analysis_ref')
        if not ref:
            return None
        analysis = read_json(check_ref(ref))
        targets = [row['target_path'] for row in resource_copy.rows(analysis)] + list(generated_files(analysis)[0])
        if not owned_outputs(m, a, targets):
            return None
    except (Rejected, OSError, ValueError, KeyError, TypeError):
        return None
    request = {'request_id': 'advance-resource-sync-%s' % assignment_id, 'operation': 'resource-sync', 'module_id': module_id,
               'assignment_id': assignment_id, 'fencing_token': a['fencing_token'], 'args': {}}
    return lean_worker.run(root, request, {'role': a['role'], 'instance_id': a['instance_id']})
