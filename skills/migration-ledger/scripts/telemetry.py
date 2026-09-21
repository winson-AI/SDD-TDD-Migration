"""Optional scoped telemetry contract; absence never introduces a global gate."""
from contracts import check_ref, keyed, nonempty, require


def validate(plan):
    data = plan.get('telemetry')
    if data is None:
        return  # Legacy/unannotated plan, not a declaration that telemetry is absent.
    require(isinstance(data, dict), 'telemetry contract must be an object')
    require(data.get('status') in ('applicable', 'not-applicable'), 'telemetry applicability unresolved')
    require(isinstance(data.get('reason'), str) and data['reason'].strip(), 'telemetry applicability reason required')
    for ref in nonempty(data.get('evidence_refs'), 'telemetry scope evidence'):
        check_ref(ref)
    rows = data.get('events')
    require(isinstance(rows, list), 'telemetry events must be a list')
    tasks = {t['task_id']: t for t in plan['tasks']}
    paths = {p['path_id']: p for p in plan['paths']}
    task_reviews = keyed(data.get('tasks'), 'task_id')
    require(set(task_reviews) == set(tasks), 'telemetry review must cover scoped tasks')
    if data['status'] == 'not-applicable':
        require(not rows, 'N/A telemetry cannot declare events')
    else:
        nonempty(rows, 'applicable telemetry events')
    events = keyed(rows, 'event_id') if rows else {}
    for event in events.values():
        for field in ('legacy_event', 'target_event', 'trigger', 'non_triggers', 'payload_contract',
                      'delivery_semantics', 'production_binding'):
            require(isinstance(event.get(field), str) and event[field].strip(), 'telemetry event missing ' + field)
        require(event.get('verification_level') in ('emitted', 'sdk-dispatched', 'server-received'),
                'telemetry verification level required')
        tids = nonempty(event.get('task_ids'), 'telemetry event tasks')
        require(len(set(tids)) == len(tids) and set(tids) <= set(tasks), 'unknown/duplicate telemetry task')
        for ref in nonempty(event.get('evidence_refs'), 'telemetry event evidence'):
            check_ref(ref)
        checks = keyed(event.get('tests'), 'path_id')
        for pid, test in checks.items():
            path = paths.get(pid)
            require(path and path.get('kind') != 'build', 'telemetry requires a business path, not build')
            aids = nonempty(test.get('assertion_ids'), 'telemetry assertions')
            require(set(aids) <= {a['assertion_id'] for a in path['expected_assertions']}, 'unknown telemetry assertion')
            require(any(pid in tasks[tid]['path_ids'] for tid in tids), 'telemetry path not traced by event tasks')
        require(all(set(checks).intersection(tasks[tid]['path_ids']) for tid in tids), 'telemetry task lacks event verification trace')
    for tid, row in task_reviews.items():
        require(row.get('status') in ('applicable', 'not-applicable') and row.get('reason'), 'telemetry task applicability required')
        ids = row.get('event_ids')
        require(isinstance(ids, list) and len(ids) == len(set(ids)), 'telemetry task event list required')
        expected = {eid for eid, e in events.items() if tid in e['task_ids']}
        require(set(ids) == expected, 'telemetry task/event mapping mismatch')
        require((row['status'] == 'applicable') == bool(expected), 'N/A task must have no telemetry work')


def verify(plan):
    data = plan.get('telemetry')
    if data is not None:
        for ref in data.get('evidence_refs', []):
            check_ref(ref)
        for event in data.get('events', []):
            for ref in event.get('evidence_refs', []):
                check_ref(ref)
