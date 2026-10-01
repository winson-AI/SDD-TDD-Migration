#!/usr/bin/env python3
"""Static spec-closure adapter: per-scenario review and anti-fake-wiring list as a PATH.

The Test-Runner reviews every frozen requirement against current production code and records the
evidence; this adapter only checks that record deterministically (context, requirement coverage,
cited symbols really present in target files, a passed scenario reached from another target file,
every anti-pattern decided) and turns it into the
frozen boolean assertion. It never judges code on its own and never repairs anything.
"""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

from contracts import check_ref, digest, file_ref, keyed, nonempty, read_json, require

ANTI_PATTERNS = ('preview-only-wiring', 'dead-handler', 'fixed-result', 'placeholder-icon', 'unapproved-stub', 'swallowed-error')


def cited(item, target, label, rid):
    path = Path(item.get('path', '')).resolve()
    require(path.is_file() and path.is_relative_to(target), label + ' must cite a target file: ' + rid)
    require(isinstance(item.get('symbol'), str) and item['symbol'] and item['symbol'] in path.read_text(errors='replace'),
            'cited ' + label + ' symbol not found in file: ' + rid)
    return path


def report(query, review_ref, target_root):
    require(query.get('kind') == 'static', 'static PATH required')
    expected = query.get('expected_assertions', [])
    require(len(expected) == 1 and expected[0].get('expected') is True, 'static PATH asserts one boolean closure')
    data = read_json(check_ref(review_ref))
    for key in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline'):
        require(data.get(key) == query.get(key), 'review context mismatch: ' + key)
    target = Path(target_root).resolve()
    scenarios = keyed(data.get('scenarios'), 'requirement_id')
    require(set(scenarios) == set(query.get('scenario_requirement_ids') or []),
            'review must cover exactly the frozen requirements')
    gaps = []
    for rid, row in scenarios.items():
        require(row.get('status') in ('passed', 'failed') and row.get('summary'), 'scenario status/summary required: ' + rid)
        symbols, defined_in = set(), set()
        for item in nonempty(row.get('production_symbols'), 'production symbol evidence for ' + rid):
            path = cited(item, target, 'production symbol', rid)
            symbols.add(item['symbol']); defined_in.add(path)
        if row['status'] == 'passed':
            # A symbol nobody references is dead or preview-only code: name the call/registration site.
            caller = row.get('reached_from')
            require(isinstance(caller, dict), 'passed scenario needs reached_from (caller, DI, navigation or manifest site): ' + rid)
            require(caller.get('symbol') in symbols, 'reached_from must reference a cited production symbol: ' + rid)
            require(cited(caller, target, 'reached_from', rid) not in defined_in,
                    'reached_from must be a different file from the symbol definition: ' + rid)
            if query.get('unit_tests_present'):
                # The module has unit PATHs: a passed requirement names the test that exercises its symbol.
                for item in nonempty(row.get('test_refs'), 'test_refs for ' + rid):
                    cited(item, target, 'test_refs', rid)
        for ref in nonempty(row.get('evidence_refs'), 'scenario evidence for ' + rid):
            check_ref(ref)
        if row['status'] == 'failed':
            gaps.append(rid)
    patterns = data.get('anti_patterns') or {}
    require(set(patterns) == set(ANTI_PATTERNS), 'every anti-pattern must be decided: ' + ', '.join(ANTI_PATTERNS))
    for name, row in patterns.items():
        require(row.get('status') in ('absent', 'present') and row.get('note'), 'anti-pattern status/note required: ' + name)
        for ref in nonempty(row.get('evidence_refs'), 'anti-pattern evidence for ' + name):
            check_ref(ref)
        if row['status'] == 'present':
            gaps.append(name)
    green = not gaps
    cause = None if green else {'category': 'code', 'summary': 'spec closure gaps: ' + ', '.join(sorted(gaps)),
                                'confidence': 'observed', 'owner': query['module_id'], 'next_action': 'diagnose',
                                'evidence_refs': [review_ref]}
    return {'schema_version': 1, 'producer': 'spec-closure-check', 'query_sha256': digest(query),
            **{k: query[k] for k in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline')},
            'quality': 'green-passed' if green else 'red-bug', 'root_cause': cause,
            'assertions': [{'assertion_id': expected[0]['assertion_id'], 'expected': True, 'actual': green,
                            'passed': green, 'evidence_ref': review_ref}]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('review', 'target-root', 'query-file', 'result-file'): p.add_argument('--' + key, required=True)
    args = p.parse_args()
    try:
        result = report(read_json(args.query_file), file_ref(args.review), args.target_root)
        with open(args.result_file, 'x') as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
        print(json.dumps({'quality': result['quality']}))
        return 0 if result['quality'] == 'green-passed' else 1
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
