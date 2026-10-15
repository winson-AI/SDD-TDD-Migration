"""A task's red evidence: two self-check notes of one frozen unit PATH, failing before the task's code and passing
after it. Recorded, counted in the report, and owed to nobody: a task without it is accepted all the same."""
from collections import Counter

from contracts import check_ref, read_json, require


def check(module, task, row):
    """The `red_evidence` of a task_trace row, or None when the row carries none: 'observed' once both notes stand."""
    evidence = row.get('red_evidence')
    if evidence is None:
        return None
    require(isinstance(evidence, dict), 'red_evidence names before_ref and after_ref')
    before, after = (read_json(check_ref(evidence.get(key))) for key in ('before_ref', 'after_ref'))
    for note in (before, after):
        require(note.get('producer') == 'author-selfcheck' and note.get('path_id'), 'red evidence is a self-check note of a frozen unit PATH')
        require(note.get('module_id') == module['module_id'] and note.get('freeze_id') == module['freeze_id'], 'red evidence belongs to another freeze')
    require(before['path_id'] == after['path_id'] and before['path_id'] in task.get('path_ids', []), 'red evidence names a unit PATH of this task')
    require(before.get('argv') == after.get('argv') and before.get('cwd') == after.get('cwd'), 'red evidence runs one command twice')
    require(before.get('finished_at', '') <= after.get('started_at', ''), 'the failing run precedes the passing run')
    required = before.get('required') or {}
    require(required and any(state != 'passed' for state in required.values()), 'the first run must fail or miss a required test')
    require(after.get('exit_code') == 0 and after.get('required') and all(state == 'passed' for state in after['required'].values()),
            'the second run must pass every required test')
    return 'observed'


def status(module, task, row):
    units = {p['path_id'] for p in module['plan']['paths'] if p.get('kind') == 'unit'}
    if not units.intersection(task.get('path_ids', [])):
        return 'not-applicable'
    return check(module, task, row) or 'not-observed'


def counts(module):
    tally = Counter(module.get('task_red', {}).values())
    return {'observed': tally['observed'], 'not_observed': tally['not-observed'], 'not_applicable': tally['not-applicable']}
