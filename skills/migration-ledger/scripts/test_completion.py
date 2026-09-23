"""Deterministic host-receipt interpretation, shared by staging and acceptance."""
import copy
import json

from contracts import check_ref, digest, keyed, read_json, require


def load_content(ref):
    path = check_ref(ref)  # Identity/hash failures must never become format errors.
    try:
        return read_json(path), None
    except (json.JSONDecodeError, UnicodeError) as exc:
        return None, type(exc).__name__ + ': ' + str(exc)


def interpret(receipt, planned):
    check_ref(receipt['log_ref'])
    query = read_json(check_ref(receipt['query_ref']))
    for key in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline'):
        require(query.get(key) == receipt.get(key), 'completion query context mismatch')
    require(query.get('expected_assertions') == planned['expected_assertions'], 'completion acceptance changed')
    expected = keyed(planned['expected_assertions'], 'assertion_id')
    report, error = load_content(receipt['result_ref']) if receipt.get('result_ref') else (None, 'missing result')
    evidence = [receipt['log_ref'], receipt['query_ref']]
    if receipt.get('result_ref'): evidence.append(receipt['result_ref'])
    known = isinstance(report, dict) and report.get('producer') in ('harmony-adapter', 'build-executor')
    if known and report['producer'] == 'build-executor':
        require(planned.get('kind') == 'build', 'build report cannot replace automation')
    if known and report['producer'] == 'harmony-adapter':
        for key in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline'):
            if key in report: require(report[key] == receipt.get(key), 'Harmony context mismatch')
            else: known = False
        if 'query_sha256' in report: require(report['query_sha256'] == digest(query), 'Harmony query mismatch')
        else: known = False
        observations, observation_error = load_content(report['observations_ref']) if report.get('observations_ref') else (None, 'missing observations')
        if observation_error or not isinstance(observations, list):
            known = False
            error = observation_error or 'invalid observations format'
        else:
            for item in observations:
                if not isinstance(item, dict): known = False; continue
                for ref in item.get('evidence_refs', []): check_ref(ref)
        for ref in report.get('artifacts', []): check_ref(ref)
    assertions = report.get('assertions') if known else None
    valid = (isinstance(assertions, list) and len(assertions) == len(expected)
             and all(isinstance(a, dict) and isinstance(a.get('assertion_id'), str) and a['assertion_id'] in expected for a in assertions)
             and len({a['assertion_id'] for a in assertions}) == len(expected)
             and all(type(a.get('passed')) is bool and 'actual' in a for a in assertions))
    if valid:
        for a in assertions:
            require(a.get('expected') == expected[a['assertion_id']]['expected'], 'acceptance changed')
        valid = report.get('quality') in ('green-passed', 'red-bug', 'yellow-blocked')
        if valid and report['quality'] != 'green-passed':
            cause = report.get('root_cause')
            valid = isinstance(cause, dict) and all(cause.get(k) for k in ('category', 'summary', 'confidence', 'owner', 'next_action'))
    abnormal = receipt['exit_code'] not in (0, 1, 2)
    if valid:
        row = copy.deepcopy({k: report[k] for k in ('quality', 'assertions', 'root_cause', 'flaky') if k in report})
        row.update(executed=True, host_completion_version=1)
        if report['producer'] == 'harmony-adapter' and (abnormal or receipt['exit_code'] != 0 and row['quality'] == 'green-passed'):
            previous = row.get('root_cause')
            row['quality'] = 'red-bug' if row['quality'] == 'red-bug' else 'yellow-blocked'
            row['root_cause'] = {'category': previous['category'] if previous else 'tooling', 'summary':
                (previous['summary'] + '; ' if previous else '') + f'Host exit {receipt["exit_code"]}; completion interrupted',
                'confidence': previous['confidence'] if previous else 'observed',
                'owner': previous['owner'] if previous else receipt['module_id'], 'next_action': 'diagnose',
                'evidence_refs': evidence, 'observed_root_cause': previous}
        return row

    # Incomplete results may still have flushed, host-bound observations. Recover
    # only observed assertions; completion is always Yellow, never inferred Green.
    rows = {aid: {'assertion_id': aid, 'expected': a['expected'], 'actual': None, 'passed': False}
            for aid, a in expected.items()}
    observed = False
    values = {aid: set() for aid in expected}
    observations_ref = receipt.get('partial_observations_ref')
    if observations_ref:
        observations, observation_error = load_content(observations_ref)
        evidence.append(observations_ref)
        if not observation_error and isinstance(observations, list):
            for item in observations:
                if not isinstance(item, dict): continue
                ids = item.get('assertion_ids', [])
                if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str) or ids[0] not in rows: continue
                aid = ids[0]
                media = item.get('evidence_refs', [])
                if item.get('error') or not media or type(item.get('result')) is not bool: continue
                if expected[aid].get('verification') not in ('auto', item.get('tool')): continue
                for ref in media: check_ref(ref)
                observed = True
                value = item['result']
                values[aid].add(value)
                if rows[aid]['actual'] is not False:
                    rows[aid].update(actual=value, passed=value)
                rows[aid]['evidence_ref'] = observations_ref
        else:
            error = (error or 'invalid result') + '; invalid partial observations: ' + str(observation_error)
    failed = [aid for aid, a in rows.items() if a['actual'] is False]
    mixed = [aid for aid, results in values.items() if len(results) > 1]
    return {'host_completion_version': 1, 'quality': 'yellow-blocked', 'executed': observed, 'flaky': bool(mixed),
            'assertions': list(rows.values()), 'root_cause': {'category': 'tooling',
                'summary': f'Host exit {receipt["exit_code"]}: ' + (error or 'invalid completion format') +
                           (f'; Failed frozen assertions: {failed}' if failed else '') +
                           (f'; Mixed pass/fail observations: {mixed}' if mixed else ''),
                'confidence': 'observed', 'owner': receipt['module_id'], 'next_action': 'diagnose',
                'evidence_refs': evidence}}
