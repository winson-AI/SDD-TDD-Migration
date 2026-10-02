"""JUnit execution evidence inside one host-owned, fresh runner attempt.

JUnit XML is an interchange format: non-Gradle runners may produce the same format.
The host binds reports to the command/attempt; XML alone is not a proof of provenance.
"""
from datetime import datetime
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

from contracts import Rejected, check_ref, digest, file_ref, nonempty, read_json, require
from run_storage import checked_path

BINDINGS = ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline', 'assignment_id', 'test_run_id')


def plan_check(path):
    policy = path.get('unit_report')
    require(isinstance(policy, dict) and policy.get('format') == 'junit', 'unit_report requires junit format')
    patterns = nonempty(policy.get('patterns'), 'runner-relative JUnit patterns')
    require(all(isinstance(p, str) and p and not PurePosixPath(p).is_absolute() and '..' not in PurePosixPath(p).parts
                and '\\' not in p for p in patterns), 'JUnit patterns must stay in this runner attempt')
    ids = nonempty(policy.get('required_test_ids'), 'frozen required_test_ids (classname#name)')
    require(all(isinstance(i, str) and i.count('#') == 1 and all(i.split('#')) for i in ids)
            and len(set(ids)) == len(ids), 'required_test_ids must be unique classname#name values')
    assertions = path.get('expected_assertions', [])
    require(len(assertions) == 1 and assertions[0].get('expected') is True, 'reported unit PATH asserts one boolean clean execution')


def parse(path):
    data = path.read_bytes()
    require(b'<!DOCTYPE' not in data.upper(), 'JUnit DTD is unsupported')
    root = ET.fromstring(data)
    require(root.tag in ('testsuites', 'testsuite'), 'not a JUnit report')
    rows = []
    for case in root.iter('testcase'):
        classname, name = case.get('classname'), case.get('name')
        require(classname and name, 'JUnit testcase needs classname/name')
        failed = case.find('failure') is not None or case.find('error') is not None
        skipped = case.find('skipped') is not None
        require(not (failed and skipped), 'JUnit testcase cannot be both failed and skipped')
        rows.append({'test_id': classname + '#' + name,
                     'status': 'failed' if failed else 'skipped' if skipped else 'passed'})
    # Check framework counters as well: truncated XML must not silently hide failed cases.
    for suite in root.iter():
        if suite.tag not in ('testsuite', 'testsuites'):
            continue
        cases = list(suite.iter('testcase'))
        expected = {'tests': len(cases), 'failures': sum(c.find('failure') is not None for c in cases),
                    'errors': sum(c.find('error') is not None for c in cases),
                    'skipped': sum(c.find('skipped') is not None for c in cases)}
        for key, count in expected.items():
            if key in suite.attrib:
                require(int(suite.attrib[key]) == count, 'JUnit counter mismatch: ' + key)
    return rows


def collect(query, directory, started_at, exit_code):
    plan_check(query)
    directory = Path(directory).resolve()
    started = datetime.fromisoformat(started_at).timestamp()
    refs, rows, issues = [], [], []
    files = sorted({p for pattern in query['unit_report']['patterns'] for p in directory.glob(pattern)})
    for candidate in files:
        try:
            path = checked_path(candidate, directory)
            require(path.is_file(), 'JUnit report is not a file')
            refs.append(file_ref(path))
            require(path.stat().st_mtime >= started, 'JUnit report predates this attempt: ' + str(path))
            rows.extend(parse(path))
        except (Rejected, OSError, ValueError, ET.ParseError) as exc:
            issues.append(str(exc))
    if not files:
        issues.append('no JUnit report produced in this attempt')
    ids = [r['test_id'] for r in rows]
    if len(set(ids)) != len(ids):
        issues.append('duplicate JUnit test IDs; freeze disjoint report patterns/test names')
    counts = {key: sum(r['status'] == key for r in rows) for key in ('passed', 'failed', 'skipped')}
    counts.update(total=len(rows), executed=counts['passed'] + counts['failed'])
    completed = {r['test_id'] for r in rows if r['status'] in ('passed', 'failed')}
    missing = sorted(set(query['unit_report']['required_test_ids']) - completed)
    if missing: issues.append('required tests did not execute: ' + ', '.join(missing))
    if not counts['executed']: issues.append('zero executed tests')
    if counts['skipped']: issues.append('JUnit contains skipped tests')
    abnormal = exit_code < 0 or exit_code in (124, 125, 127, 130, 143)
    quality = ('red-bug' if counts['failed'] or (exit_code != 0 and not abnormal) else
               'yellow-blocked' if issues or abnormal else 'green-passed')
    summary = {'format': 'junit', 'query_sha256': digest(query), **{k: query[k] for k in BINDINGS},
               'reports': refs, 'tests': sorted(rows, key=lambda r: r['test_id']), 'counts': counts,
               'missing_test_ids': missing, 'issues': issues}
    cause = None if quality == 'green-passed' else {
        'category': 'code' if quality == 'red-bug' else 'tooling', 'confidence': 'observed',
        'owner': query['module_id'], 'next_action': 'diagnose and rerun this frozen unit PATH',
        'summary': f'Unit exit {exit_code}; executed={counts["executed"]}, failed={counts["failed"]}, skipped={counts["skipped"]}'
                   + ('; ' + '; '.join(issues) if issues else ''),
        'evidence_refs': [file_ref(directory / 'execution.log'), *refs]}
    return {'producer': 'build-executor', 'unit_execution': summary, 'quality': quality, 'root_cause': cause,
            'assertions': [{'assertion_id': query['expected_assertions'][0]['assertion_id'], 'expected': True,
                            'actual': True if quality == 'green-passed' else False if quality == 'red-bug' else None,
                            'passed': quality == 'green-passed'}]}


def validate(receipt, planned, report):
    query_file = check_ref(receipt['query_ref'])
    query = read_json(query_file)
    require(query.get('unit_report') == planned.get('unit_report'), 'frozen unit report policy changed')
    for key in BINDINGS:
        require(query.get(key) == receipt.get(key) and query.get(key), 'unit execution context mismatch: ' + key)
    summary = report.get('unit_execution') or {}
    for ref in summary.get('reports', []):
        check_ref(ref)
    expected = collect(query, query_file.parent, receipt['started_at'], receipt['exit_code'])
    require(all(report.get(k) == v for k, v in expected.items()), 'unit report evidence/classification changed')
