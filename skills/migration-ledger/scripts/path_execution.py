"""Validate mobile step receipts against the frozen query and observation timing."""
from contracts import digest, read_json


def inspect(query, trace, observations, check):
    issues = []
    if not isinstance(query.get('steps'), list) or not query['steps']:
        return ['missing frozen steps']
    if any(type(a.get('after_step')) is not int or not 1 <= a['after_step'] <= len(query['steps'])
           for a in query['expected_assertions']):
        return ['frozen assertion checkpoints missing; replan within this Run']
    if not isinstance(trace, dict) or trace.get('query_sha256') != digest(query):
        return ['step trace belongs to a different query']
    rows = trace.get('steps', [])
    if not isinstance(rows, list) or len(rows) != len(query['steps']):
        return ['step trace does not cover the frozen path']
    for number, (step, row) in enumerate(zip(query['steps'], rows), 1):
        if not isinstance(row, dict) or row.get('step_number') != number or row.get('step_sha256') != digest(step):
            issues.append(f'step {number}: frozen identity mismatch'); continue
        status = row.get('status')
        if status not in ('executed', 'already-satisfied'):
            issues.append(f'step {number}: {status or "missing status"}')
        if status == 'already-satisfied' and not (isinstance(step, dict) and step.get('allow_already_satisfied') is True):
            issues.append(f'step {number}: skipping the action was not frozen')
        if status in ('executed', 'already-satisfied'):
            for name in ('before_ref', 'after_ref', 'action_ref'):
                if not row.get(name): issues.append(f'step {number}: missing {name}')
                else: check(row[name])
            if not row.get('started_at') or not row.get('finished_at'):
                issues.append(f'step {number}: missing timestamps')
            if status == 'executed' and not row.get('actions'):
                issues.append(f'step {number}: no successful device action')
            if row.get('action_ref'):
                receipt = read_json(check(row['action_ref']))
                if not isinstance(receipt, dict) or not isinstance(receipt.get('events'), list):
                    issues.append(f'step {number}: invalid action receipt'); continue
                events = receipt.get('events', [])
                if any(not isinstance(e, dict) or not isinstance(e.get('data'), dict) for e in events):
                    issues.append(f'step {number}: invalid native events'); continue
                completed = {e.get('step_number') for e in events if e.get('event_type') == 'glm_step_end' and e.get('data', {}).get('success') is True}
                actions = [e['data']['action'] for e in events if e.get('event_type') == 'glm_action' and isinstance(e['data'].get('action'), dict)
                           and e.get('step_number') in completed and e['data']['action'].get('_metadata') != 'finish']
                if actions != row.get('actions', []): issues.append(f'step {number}: device action receipt mismatch')
    expected = {a['assertion_id']: a for a in query['expected_assertions']}
    observed = set()
    for event in observations:
        if event.get('error'): continue
        ids = event.get('assertion_ids', [])
        if len(ids) != 1 or ids[0] not in expected: continue
        if type(event.get('result')) is bool and event.get('evidence_refs'):
            observed.add(ids[0])
        number = expected[ids[0]]['after_step']
        if event.get('after_step') != number or event.get('step_sha256') != digest(query['steps'][number - 1]):
            issues.append(f'{ids[0]}: observation outside the frozen checkpoint')
        recorded = event.get('recorded_at', '')
        if any(not isinstance(r, dict) for r in rows): continue
        following = rows[number].get('started_at') if number < len(rows) else None
        if not isinstance(recorded, str) or not recorded or recorded < rows[number - 1].get('finished_at', '') or (following and recorded > following):
            issues.append(f'{ids[0]}: observation timing mismatch')
    if set(expected) - observed: issues.append('missing checkpoint observations: ' + ', '.join(sorted(set(expected) - observed)))
    return issues
