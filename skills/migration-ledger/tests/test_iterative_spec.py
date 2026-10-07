"""Direct upstream coverage to SPEC, then additive repair in the same Run."""
import copy
import json
import sys
import unittest

import design_stage
from contracts import Rejected, baseline, check_ref, file_ref
from execute_test import execute
import test_source_changes
import test_control_policy


def direct_plan(f, plan):
    mid = plan['module_id']; s = f.state(); m = s['modules'][mid]
    ref = next({k: d[k] for k in ('path', 'sha256')} for d in plan['definitions'] if d['kind'] == 'test-design')
    paths = copy.deepcopy(plan['paths'])
    for path in paths:
        path['preparation'] = {'status': 'existing', 'reason': 'Use upstream approved test executor',
                               'evidence_refs': [ref], 'asset_ids': []}
    doc = {'schema_version': 1, 'kind': 'upstream-test-plan', 'module_id': mid,
           'subject_sha256': design_stage.subject(s, m), 'case_refs': design_stage.upstream_refs(s),
           'design_ref': ref, 'paths': paths, 'test_assets': []}
    plan.pop('paths')
    plan['test_design_ref'] = f.ref(f'upstream-{mid}-{f.n}.json', doc)
    return doc


class UpstreamPlanTests(unittest.TestCase):
    def setUp(self):
        self.t = test_source_changes.SourceChangeTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def freeze(self, p):
        f = self.f; doc = direct_plan(f, p)
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M001')
        self.assertEqual(step['operation'], 'plan')
        f.call('plan', {'plan_ref': f.ref('direct-plan.json', p)}, role='spec-designer', module='M001')
        m = f.state()['modules']['M001']
        review = {'plan_hash': m['plan_hash'], 'reviewer_instance_id': 'module-orchestrator',
                  'semantic_change': False, 'authorization_change': False, 'unresolved_questions': [],
                  'reason': 'All upstream cases allocated and expected behavior preserved', 'evidence_refs': doc['case_refs']}
        f.call('plan-review', {'review_ref': f.ref('review.json', review)}, module='M001')
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M001')
        f.call('freeze', step['payload'], module='M001')
        return doc

    def test_prepared_run_freezes_directly_with_all_upstream_paths_and_no_design_worker(self):
        f = self.f; doc = self.freeze(self.t.plan('M001'))
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'frozen'); self.assertEqual(m['assignments'], {})
        self.assertEqual(m['plan']['paths'], doc['paths'])
        self.assertIn('spec-designer', m['authors'])
        self.assertEqual(f.state()['decisions'], {})
        self.t.implement_and_test('M001')
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'completed')
        self.assertEqual(set(m['results']), {p['path_id'] for p in doc['paths']})
        self.assertTrue(all(r['quality'] == 'green-passed' for r in m['results'].values()))

    def test_direct_spec_repair_reuses_upstream_cases_and_retests_actual_code_failure(self):
        f = self.f; self.freeze(self.t.plan('M001'))
        self.t.implement_and_test('M001', value=1)
        old = f.state()['modules']['M001']
        self.assertEqual(old['results']['M001-P']['quality'], 'red-bug')
        p = copy.deepcopy(old['plan']); p['paths'][0]['name'] = 'Correct scoped behavior after automation feedback'
        f.call('change', {'request_ref': f.ref('cr.md', 'Update implementation guidance from real failed path'),
                         'impact_ref': f.ref('impact.md', 'Keep source behavior and all cases')}, module='M001')
        self.freeze(p)
        self.t.implement_and_test('M001', value=2)
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'completed'); self.assertNotEqual(m['code_baseline'], old['code_baseline'])
        self.assertEqual(m['results']['M001-P']['retest_of'], old['results']['M001-P']['test_run_id'])
        self.assertEqual(m['fix_rounds_used'], 1); self.assertEqual(f.state()['run_id'], 'demo')
        self.assertFalse(any(a.get('mode') == 'design' for a in m['assignments'].values()))

    def test_missing_cases_changed_sources_and_observed_results_cannot_be_frozen(self):
        f = self.f; p = self.t.plan('M001'); doc = direct_plan(f, p)
        for change, message in [
            (lambda d: d['paths'][0].update(case_id='UNKNOWN'), 'assigned cases'),
            (lambda d: d.update(case_refs=[f.ref('fake-cases.md', 'invented')]), 'authoritative upstream'),
            (lambda d: d.update(subject_sha256='0'*64), 'allocation/context stale'),
            (lambda d: d['paths'][0]['expected_assertions'][0].update(actual=True), 'expectation only'),
        ]:
            d = copy.deepcopy(doc); change(d)
            p['test_design_ref'] = f.ref('bad-'+str(f.n)+'.json', d)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                f.call('plan', {'plan_ref': f.ref('bad-plan-'+str(f.n)+'.json', p)}, role='spec-designer', module='M001')
        self.assertIsNone(f.state()['modules']['M001']['freeze_id'])

    def test_direct_test_assets_must_belong_to_the_prepared_run_staging(self):
        f = self.f; p = self.t.plan('M001'); doc = direct_plan(f, p)
        design = f.ref('outside-design/test-plan.md', 'Test plan outside managed staging')
        doc['design_ref'] = design
        doc['test_assets'] = [{'asset_id': 'FIXTURE', 'kind': 'fixture',
                              'ref': f.ref('outside-design/fixture.json', {'value': 2}), 'path_ids': ['M001-P']}]
        doc['paths'][0]['preparation'] = {'status': 'prepared', 'reason': 'Fixture supplied',
                                         'evidence_refs': [design], 'asset_ids': ['FIXTURE']}
        p['definitions'] = [d if d['kind'] != 'test-design' else {**design, 'kind': 'test-design'} for d in p['definitions']]
        p['test_design_ref'] = f.ref('outside-assets.json', doc)
        with self.assertRaisesRegex(Rejected, 'belongs in staging'):
            f.call('plan', {'plan_ref': f.ref('outside-plan.json', p)}, role='spec-designer', module='M001')


class IterativeRepairTests(unittest.TestCase):
    def setUp(self):
        self.t = test_control_policy.ControlPolicyTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def test_failed_automation_replans_additive_fidelity_then_updates_existing_code(self):
        t = self.t; f = self.f; t.freeze(); f.implementation()
        a, result = f.make_test_result(quality='red-bug'); f.submit(result, a)
        f.call('accept', {'assignment_id': a['assignment_id']})
        old = f.state()['modules']['M001']; p = copy.deepcopy(old['plan'])
        p['paths'].append({**copy.deepcopy(p['paths'][0]), 'path_id': 'P-FIDELITY'})
        p['tasks'][0]['path_ids'].append('P-FIDELITY')
        f.call('change', {'request_ref': f.ref('cr.md', 'Automation found an omitted fidelity task/path'),
                         'impact_ref': f.ref('impact.md', 'Retain original acceptance; update existing module')})
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'plan')
        f.call('plan', {'plan_ref': f.ref('repaired-plan.json', p)}, role='spec-designer')
        f.call('plan-review', {'review_ref': t.review()})
        f.call('freeze', f.state()['next_steps'][0]['payload'])
        m = f.state()['modules']['M001']
        self.assertEqual(f.state()['run_id'], 'demo')
        self.assertEqual(m['code_files'], old['code_files'])
        self.assertEqual(m['code_baseline'], old['code_baseline'])
        self.assertTrue(m['results']['P1']['stale']); self.assertEqual(m['fix_rounds_used'], 1)
        self.assertEqual(m['accepted_task_ids'], [])
        history = m['change_request_history'][-1]
        self.assertFalse(history['executable']); self.assertEqual(history['previous_plan']['plan_hash'], old['plan_hash'])
        f.assign('implementer', 'UPDATE')
        contract = f.state()['modules']['M001']['assignments']['UPDATE']['execution_contract']
        self.assertEqual(contract['accepted_code_files'], old['code_files'])
        self.assertEqual(set(contract['path_ids']), {'P1', 'P-FIDELITY'})
        a = f.state()['modules']['M001']['assignments']['UPDATE']
        code = f.target / 'm1/code.py'; code.write_text('value = 2\nfidelity = True\n')
        refs = [file_ref(code)]
        update = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
                  'assignment_id': 'UPDATE', 'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'],
                  'code_files': refs, 'code_baseline': baseline(refs), 'task_trace': [{'task_id': 'T1', 'files': [str(code)]}],
                  'production_binding_evidence': f.ref('updated-binding.md', 'Existing query implementation updated'),
                  'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref('update.log', '0 errors')}}
        f.submit(update, a); f.call('accept', {'assignment_id': 'UPDATE'})
        a = f.assign('test-runner', 'RETEST'); rows = []
        adapter = f.base / 'retest.py'
        adapter.write_text('import argparse,json,runpy\np=argparse.ArgumentParser();p.add_argument("--query-file");'
            'p.add_argument("--result-file");a=p.parse_args();'
            f'v=runpy.run_path({str(code)!r})["value"];'
            'json.dump({"assertions":[{"assertion_id":"A1","expected":2,"actual":v,"passed":v==2}]},open(a.result_file,"w"))')
        for pid in ('P1', 'P-FIDELITY'):
            ref = execute(f.root, 'M001', 'RETEST', pid, [sys.executable, str(adapter)], str(f.target), f.base / ('retest-'+pid))
            receipt = json.loads(check_ref(ref).read_text())
            assertions = json.loads(check_ref(receipt['result_ref']).read_text())['assertions']
            rows.append({'path_id': pid, 'quality': 'green-passed', 'executed': True, 'execution_receipt': ref,
                         'test_run_id': receipt['test_run_id'], 'assertions': assertions,
                         'retest_of': old['results'].get(pid, {}).get('test_run_id')})
        f.submit({'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'M001',
                  'assignment_id': 'RETEST', 'actor_instance_id': 'test-runner', 'freeze_id': a['freeze_id'],
                  'code_baseline': a['code_baseline'], 'paths': rows}, a)
        f.call('accept', {'assignment_id': 'RETEST'})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')

    def test_repair_cannot_remove_failed_path_or_weaken_expected_assertion(self):
        t = self.t; f = self.f; t.freeze(); f.implementation()
        f.call('change', {'request_ref': f.ref('cr.md', 'Repair'), 'impact_ref': f.ref('impact.md', 'Review')})
        p = copy.deepcopy(f.state()['modules']['M001']['plan'])
        p['paths'][0]['expected_assertions'][0]['expected'] = 'weakened'
        f.call('plan', {'plan_ref': f.ref('weakened-plan.json', p)}, role='spec-designer')
        with self.assertRaisesRegex(Rejected, 'acceptance changed'):
            f.call('plan-review', {'review_ref': t.review()})

    def test_repair_cannot_drop_original_path_when_case_still_has_other_coverage(self):
        t = self.t; f = self.f; p = f.plan()
        p['paths'].append({**copy.deepcopy(p['paths'][0]), 'path_id': 'P2'})
        p['tasks'][0]['path_ids'].append('P2'); t.freeze(p); f.implementation()
        f.call('change', {'request_ref': f.ref('cr.md', 'Repair'), 'impact_ref': f.ref('impact.md', 'Review')})
        p = copy.deepcopy(f.state()['modules']['M001']['plan'])
        p['paths'] = [r for r in p['paths'] if r['path_id'] != 'P1']; p['tasks'][0]['path_ids'] = ['P2']
        f.call('plan', {'plan_ref': f.ref('removed-path.json', p)}, role='spec-designer')
        with self.assertRaisesRegex(Rejected, 'acceptance changed'):
            f.call('plan-review', {'review_ref': t.review()})

    def test_additional_assertion_for_original_expectation_can_be_reviewed_by_mo(self):
        t = self.t; f = self.f; t.freeze(); f.implementation()
        f.call('change', {'request_ref': f.ref('cr.md', 'Add fidelity check from original source'),
                         'impact_ref': f.ref('impact.md', 'Preserve all old assertions')})
        p = copy.deepcopy(f.state()['modules']['M001']['plan'])
        p['paths'][0]['expected_assertions'].append({'assertion_id': 'A2', 'expected': True})
        f.call('plan', {'plan_ref': f.ref('additional-assertion.json', p)}, role='spec-designer')
        f.call('plan-review', {'review_ref': t.review()})
        f.call('freeze', f.state()['next_steps'][0]['payload'])
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')
        self.assertEqual(f.state()['decisions'], {})


if __name__ == '__main__': unittest.main()
