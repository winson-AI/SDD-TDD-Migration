"""What a screen's files and parameters become in the target follows from its UI evidence and the project's conventions:
the copy plan and the parameter sheet are derived, never authored, and the copies and the generated parameter file are
the frozen plan's bytes. So the Ledger derives the two when a plan is submitted without them, and `advance` copies the
files and writes the parameter file in the coder's name when a coder is dispatched; the coder names them in its code."""
import json
from pathlib import Path

from contracts import Rejected, check_ref, file_ref, read_json
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
            if derived['rows']:
                rows['Resource']['copy_plan_ref'] = save(root, folder / 'copy-plan.json', derived); bound = True
        if rules.get('parameters') and 'UI' in rows and not rows['UI'].get('parameter_sheet_ref'):
            sheet = ui_parameters.derive(analysis, rules['parameters'])
            if sheet.get('parameters'):
                rows['UI']['parameter_sheet_ref'] = save(root, folder / 'parameter-sheet.json', sheet); bound = True
    except (Rejected, OSError, ValueError, KeyError, TypeError):
        return plan  # evidence the derivation cannot read: the planner's tools say why
    if not bound:
        return plan
    derived_ref = save(root, folder / ('analysis-%s.json' % ref['sha256'][:12]), analysis)
    plan['dimension_analysis_ref'] = derived_ref
    for task in plan.get('tasks') or []:
        if (task.get('dimension_analysis') or {}).get('parent_ref') == ref:
            task['dimension_analysis']['parent_ref'] = derived_ref
    return plan


def save(root, path, value):
    path = run_storage.checked_path(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    run_storage.atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode())
    return file_ref(path)


def owner(m, assignment):
    """The task of a coder's dispatch whose write scope holds every copy and generated file, or None."""
    import parameter_file
    import resource_copy
    import ui_parameters
    ref = (m.get('plan') or {}).get('dimension_analysis_ref')
    if not ref:
        return None
    analysis = read_json(check_ref(ref))
    targets = [Path(row['target_path']) for row in resource_copy.rows(analysis)]
    document = ui_parameters.load(analysis)
    if document and document.get('convention'):
        targets += [Path(p) for p in parameter_file.render(document, parameter_file.declarations(analysis))[0]]
    if not targets:
        return None
    tasks = {t['task_id']: t for t in m['plan']['tasks']}
    for tid in assignment['execution_contract']['task_ids']:
        scope = [Path(p).resolve() for p in (tasks[tid].get('scope') or {}).get('write_paths', [])]
        if scope and all(any(target.resolve().is_relative_to(root) for root in scope) for target in targets):
            return tid
    return None


def sync(root, s, module_id, assignment_id):
    """Copy the frozen plan's files and write its parameter file in the coder's name, as resource-sync does; None when
    there is nothing to copy or no single task of the dispatch owns where it goes (the coder then runs the tool)."""
    import lean_worker
    m = s['modules'][module_id]
    a = m['assignments'][assignment_id]
    try:
        task = owner(m, a)
    except (Rejected, OSError, ValueError, KeyError, TypeError):
        return None
    if not task:
        return None
    request = {'request_id': 'advance-resource-sync-%s' % assignment_id, 'operation': 'resource-sync', 'module_id': module_id,
               'assignment_id': assignment_id, 'fencing_token': a['fencing_token'], 'args': {'task_id': task}}
    return lean_worker.run(root, request, {'role': a['role'], 'instance_id': a['instance_id']})
