"""Static spec-closure review runs between build and automation as an independent PATH."""
import copy
import json
from pathlib import Path
import sys
import unittest

import test_split_testing
import test_validation as tv
from contracts import Rejected, read_json
from execute_test import execute
from harmony_stage import build as stage_result
import spec_closure

ADAPTER = str(Path(spec_closure.__file__).resolve())


def spec_closure_green(receipt, path):
    from test_completion import interpret
    return interpret(read_json(Path(receipt['path'])), path)['quality'] == 'green-passed'


class SpecClosureTests(unittest.TestCase):
    def setUp(self):
        self.split = test_split_testing.SplitTestingTests()
        self.split.setUp(); self.addCleanup(self.split.doCleanups)
        self.f = f = self.split.f
        old_plan = f.plan
        def plan():
            p = old_plan()
            p['paths'].append({'path_id': 'S1', 'kind': 'static', 'name': 'spec closure', 'case_id': 'C1',
                               'requirement_id': 'R1', 'required': True, 'scenario_requirement_ids': ['R1'],
                               'expected_assertions': [{'assertion_id': 'SPEC-CLOSURE', 'expected': True}]})
            p['tasks'][0]['path_ids'].append('S1')
            return p
        f.plan = plan
        self.review_path = f.base / 'static-review.json'
        old_report = f.report
        def report(stage, *args, **kwargs):
            r = old_report(stage, *args, **kwargs)
            if stage == 'testing':  # the review goes ahead of the automation a model runs: one preflight approves both
                run = {k: r['execution'][k] for k in ('argv', 'cwd')}
                r['execution']['commands'] = {'P1': run, 'S1': {'argv': self.static_argv(), 'cwd': str(f.target)}}
            return r
        f.report = report

    def static_argv(self):
        return [sys.executable, ADAPTER, '--review', str(self.review_path), '--target-root', str(self.f.target)]

    def review(self, **over):
        f = self.f; m = f.state()['modules']['M001']
        code = f.target / 'm1/code.py'
        entry = f.target / 'm1/entry.py'; entry.write_text('from code import value\nprint(value)\n')
        evidence = f.ref('review-notes.md', 'Read production entry and every caller of value')
        data = {'schema_version': 1, 'run_id': f.state()['run_id'], 'module_id': 'M001', 'path_id': 'S1',
                'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'],
                'scenarios': [{'requirement_id': 'R1', 'status': 'passed', 'summary': 'value reaches production entry',
                               'production_symbols': [{'path': str(code), 'symbol': 'value'}],
                               'reached_from': {'path': str(entry), 'symbol': 'value'}, 'evidence_refs': [evidence]}],
                'anti_patterns': {name: {'status': 'absent', 'note': 'checked callers and data source', 'evidence_refs': [evidence]}
                                  for name in spec_closure.ANTI_PATTERNS}}
        for key, value in over.items():
            data[key] = value
        return data

    def run_static(self, data, aid='STATIC1'):
        """The review first; the functional path after it in the same dispatch only when the review is Green."""
        f = self.f
        self.review_path.write_text(json.dumps(data))
        assignment = f.state()['modules']['M001']['assignments'][aid]
        self.assertEqual((assignment['test_scope'], assignment['closed']), ('automation', False))
        receipts = [execute(f.root, 'M001', aid, 'S1', self.static_argv(), str(f.target), f.base / (aid + '-static'))]
        if spec_closure_green(receipts[0], next(p for p in f.state()['modules']['M001']['plan']['paths'] if p['path_id'] == 'S1')):
            (f.base / 'adapter.py').write_text('import argparse,json\np=argparse.ArgumentParser();p.add_argument("--query-file");p.add_argument("--result-file");a=p.parse_args()\n'
                                              'json.dump({"assertions":[{"assertion_id":"A1","expected":2,"actual":2,"passed":True}]},open(a.result_file,"w"))\n')
            receipts.append(execute(f.root, 'M001', aid, 'P1', [sys.executable, str(f.base / 'adapter.py')], str(f.target), f.base / (aid + '-automation')))
        result = stage_result(f.root, 'M001', aid, receipts)
        f.submit(result, assignment); f.call('accept', {'assignment_id': aid})
        return result['paths'][0]

    def built(self):
        self.split.prepare(); self.split.compile()  # the build passed and was accepted: the review goes ahead of the automation
        a = self.f.assign('test-runner', 'STATIC1')
        self.assertEqual((a['test_scope'], a['execution_contract']['path_ids']), ('automation', ['S1', 'P1']))

    def test_static_review_sits_between_build_and_automation(self):
        f = self.f; self.built()
        row = self.run_static(self.review())  # one Test-Runner turn: the review, then the automation it allowed
        self.assertEqual(row['quality'], 'green-passed')
        self.assertEqual({pid: r['quality'] for pid, r in f.state()['modules']['M001']['results'].items()},
                         {'B1': 'green-passed', 'S1': 'green-passed', 'P1': 'green-passed'})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')

    def test_fake_wiring_or_failed_scenario_is_red_and_enters_repair(self):
        f = self.f; self.built()
        data = self.review()
        data['anti_patterns']['fixed-result'].update(status='present', note='repository returns a constant list')
        row = self.run_static(data)
        self.assertEqual(row['quality'], 'red-bug')
        self.assertIn('fixed-result', row['root_cause']['summary'])
        self.assertNotIn('P1', f.state()['modules']['M001']['results'])  # the review stopped the dispatch before the automation
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'diagnose')

    def test_swallowed_error_is_a_decided_anti_pattern(self):
        f = self.f; self.built()
        self.assertIn('swallowed-error', spec_closure.ANTI_PATTERNS)
        data = self.review()
        data['anti_patterns']['swallowed-error'].update(status='present', note='malformed response decoded to an empty list')
        row = self.run_static(data)
        self.assertEqual(row['quality'], 'red-bug')
        self.assertIn('swallowed-error', row['root_cause']['summary'])

    def test_review_must_cover_frozen_requirements_with_real_symbols(self):
        f = self.f; self.built()
        query = {'kind': 'static', 'scenario_requirement_ids': ['R1'],
                 'expected_assertions': [{'assertion_id': 'SPEC-CLOSURE', 'expected': True}],
                 **{k: self.review()[k] for k in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline')}}
        cases = {'requirement': self.review(scenarios=[]),
                 'symbol': self.review(scenarios=[{**self.review()['scenarios'][0],
                                                   'production_symbols': [{'path': str(f.target / 'm1/code.py'), 'symbol': 'missingName'}]}]),
                 'outside': self.review(scenarios=[{**self.review()['scenarios'][0],
                                                    'production_symbols': [{'path': str(f.legacy), 'symbol': 'value'}]}]),
                 'anti-pattern': self.review(anti_patterns={}),
                 'no-caller': self.review(scenarios=[{k: v for k, v in self.review()['scenarios'][0].items() if k != 'reached_from'}]),
                 'self-caller': self.review(scenarios=[{**self.review()['scenarios'][0],
                                                        'reached_from': {'path': str(f.target / 'm1/code.py'), 'symbol': 'value'}}]),
                 'caller-misses-symbol': self.review(scenarios=[{**self.review()['scenarios'][0],
                                                                 'reached_from': {'path': str(f.target / 'm1/entry.py'), 'symbol': 'other'}}])}
        for name, data in cases.items():
            ref = f.ref(name + '-review.json', data)
            with self.subTest(name=name), self.assertRaises(Rejected):
                spec_closure.report(query, ref, str(f.target))

    def test_automation_waits_for_static_review(self):
        f = self.f
        self.split.prepare(); self.split.compile()
        with self.assertRaisesRegex(Rejected, 'the static closure goes ahead of the functional PATHs'):
            f.call('assign', {'assignment_id': 'BARE', 'role': 'test-runner', 'instance_id': 'test-runner', 'test_scope': 'automation',
                              'task_ids': ['T1'], 'path_ids': ['P1']})
        self.assertEqual(f.assign('test-runner', 'STATIC1')['execution_contract']['path_ids'], ['S1', 'P1'])
        ref = f.record(f.report('testing'))
        with self.assertRaisesRegex(Rejected, 'worker still active|build -> unit -> static -> automation -> visual'):
            f.raw('assign', {'assignment_id': 'EARLY', 'role': 'test-runner', 'instance_id': 'test-runner',
                             'test_scope': 'automation', 'context_ref': ref})

    def test_plan_rules_for_static_paths(self):
        f = self.f
        plan = f.plan()
        tv.plan_check(plan, str(f.target), static_required=True)
        broken = copy.deepcopy(plan); broken['paths'][-1]['scenario_requirement_ids'] = []
        with self.assertRaisesRegex(Rejected, 'scenario_requirement_ids'):
            tv.plan_check(broken, str(f.target))
        missing = copy.deepcopy(plan); missing['paths'] = [p for p in missing['paths'] if p['kind'] != 'static']
        with self.assertRaisesRegex(Rejected, 'spec_closure_required'):
            tv.plan_check(missing, str(f.target), static_required=True)
        tv.plan_check(missing, str(f.target))


if __name__ == '__main__':
    unittest.main()
