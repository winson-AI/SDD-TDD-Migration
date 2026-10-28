"""A test written from the SPEC is frozen with the plan: it lands in the target verbatim, its unit PATH requires only
the tests it defines, and the Ledger writes its skeleton."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import spec_skeleton
import test_iterative_spec
import test_source_changes
import test_unit_reports
from contracts import Rejected, baseline, check_ref, file_ref, read_json
from execute_test import execute
from harmony_stage import build as stage_result

SOURCE = 'import kotlin.test.Test\n\nclass SearchTest {\n    @Test\n    fun query() { kotlin.test.assertEquals(2, Search.find("a")) }\n}\n'


class FrozenTestTests(unittest.TestCase):
    def setUp(self):
        self.inner = test_unit_reports.UnitReportTests(); self.inner.setUp(); self.addCleanup(self.inner.doCleanups)
        self.f = self.inner.f
        self.f.global_plan()

    def design(self, text=SOURCE, ids=('SearchTest#query',), symbols=('Search',)):
        f = self.f; plan = f.plan()
        result = test_iterative_spec.direct_plan(f, plan)
        self.src = f.ref(f'defs/SearchTest-{f.n}.kt', text)
        self.target_path = str(f.target / 'm1/SearchTest.kt')
        result['test_assets'] = [{'asset_id': 'TEST-U1', 'kind': 'test-source', 'ref': self.src, 'path_ids': ['U1'], 'target_path': self.target_path,
                                 'required_test_ids': list(ids), 'scenarios': [{'scenario_id': 'S-normal', 'test_id': ids[0]}], 'symbols': list(symbols)}]
        next(p for p in result['paths'] if p['path_id'] == 'U1')['preparation'].update(status='prepared', asset_ids=['TEST-U1'])
        plan['test_design_ref'] = f.ref(f'upstream-assets-{f.n}.json', result)
        return plan

    def freeze(self, plan):
        f = self.f
        f.call('plan', {'plan_ref': f.ref('frozen-plan.json', plan)}, role='spec-designer')
        f.approve(f.state()['modules']['M001']['plan_hash'], 'D-T'); f.call('freeze', {'decision_id': 'D-T'})

    def implementation(self, test_text):
        f = self.f; open_ = f.state()['modules']['M001']['assignments'].get('I1')
        a = open_ if open_ and not open_['closed'] else f.assign('implementer', 'I1')  # a refused submit leaves the dispatch open
        source = f.target / 'm1/code.py'; source.parent.mkdir(exist_ok=True); source.write_text('value = 2\n')
        files = [source]
        if test_text is not None:
            Path(self.target_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.target_path).write_text(test_text); files.append(Path(self.target_path))
        refs = [file_ref(p) for p in files]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001', 'assignment_id': 'I1',
                  'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'], 'code_files': refs, 'code_baseline': baseline(refs),
                  'task_trace': [{'task_id': 'T1', 'files': [str(p) for p in files]}],
                  'production_binding_evidence': f.ref('binding.txt', 'real binding reviewed'),
                  'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref('diag.log', '0 errors')}}
        f.submit(result, a)
        return a

    def test_the_frozen_test_lands_verbatim_or_the_implementation_is_refused(self):
        f = self.f; self.freeze(self.design())
        step = next(x for x in f.state()['next_steps'] if x.get('operation') == 'assign' and x.get('worker_role') == 'implementer')
        self.assertEqual(step['submission']['frozen_tests'], [{'target_path': self.target_path, 'sha256': self.src['sha256']}])
        with self.assertRaisesRegex(Rejected, 'frozen test source missing or changed'):
            self.implementation(None)
        with self.assertRaisesRegex(Rejected, 'frozen test source missing or changed'):
            self.implementation(SOURCE.replace('2', '3'))  # weakened by the implementer
        a = self.implementation(SOURCE)
        f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'testing')

    def test_the_unit_run_records_the_frozen_source_and_passes_on_it(self):
        f = self.f; self.freeze(self.design()); a = self.implementation(SOURCE); f.call('accept', {'assignment_id': 'I1'})
        self.inner.fixture.split.compile()  # the build dispatch; the unit PATH rides it
        receipt_ref = execute(f.root, 'M001', 'BUILD1', 'U1', self.inner.fixture.unit_argv(), f.target, f.base / 'unit-attempt')
        receipt = read_json(check_ref(receipt_ref))
        self.assertEqual(receipt['frozen_test_sources'], [{'path': self.target_path, 'sha256': self.src['sha256']}])
        Path(self.target_path).write_text(SOURCE + '\n')  # touched after acceptance: no run on it
        with self.assertRaisesRegex(Rejected, 'evidence hash mismatch|code changed before execution|frozen test source missing or changed'):
            execute(f.root, 'M001', 'BUILD1', 'U1', self.inner.fixture.unit_argv(), f.target, f.base / 'unit-attempt-2')
        Path(self.target_path).write_text(SOURCE)
        result = stage_result(f.root, 'M001', 'BUILD1', [receipt_ref] + self.inner.fixture.split.receipts)
        build = f.state()['modules']['M001']['assignments']['BUILD1']
        f.submit(result, build); f.call('accept', {'assignment_id': 'BUILD1'})
        self.assertEqual(f.state()['modules']['M001']['results']['U1']['quality'], 'green-passed')

    def test_a_test_source_defines_what_it_requires_and_names_what_it_calls(self):
        f = self.f
        with self.assertRaisesRegex(Rejected, 'does not define SearchTest#missing'):
            self.freeze(self.design(ids=('SearchTest#missing',)))
        with self.assertRaisesRegex(Rejected, 'declared production symbol not used'):
            self.freeze(self.design(symbols=('Nowhere',)))
        with self.assertRaisesRegex(Rejected, 'unfilled skeleton'):
            self.freeze(self.design(text=SOURCE.replace('Search.find("a")', '[[待写：call]]')))

    def test_a_frozen_test_can_fail_on_the_code_and_runs_as_a_test(self):
        with self.assertRaisesRegex(Rejected, 'asserts a constant'):
            self.freeze(self.design(text=SOURCE.replace('kotlin.test.assertEquals(2, Search.find("a"))', 'require(true); Search')))
        with self.assertRaisesRegex(Rejected, 'expression body'):
            self.freeze(self.design(text=SOURCE.replace('fun query() {', 'fun query() = kotlin.test.assertIs<Int>(Search) ; fun x() {')))
        self.freeze(self.design(text=SOURCE.replace('fun query() {', 'fun query() = runTest {').replace('}\n}', '}\n}')))
        self.assertTrue(self.f.state()['modules']['M001']['freeze_id'])

    def test_the_test_lands_beside_the_code_and_its_dependency_is_owed(self):
        f = self.f; plan = self.design()
        self.target_path = str(f.target / 'm1-test/SearchTest.kt')  # the test source set, outside the allocated write paths
        design = read_json(check_ref(plan['test_design_ref'])); design['test_assets'][0]['target_path'] = self.target_path
        plan['test_design_ref'] = f.ref('upstream-assets-beside.json', design)
        (f.target / 'build.gradle.kts').write_text('kotlin { sourceSets { commonMain { } } }\n')
        plan_ref = f.ref('frozen-plan.json', plan)
        self.assertTrue(any(row['reason'].startswith('test dependency') for row in ledger.preview(f.root, 'M001', plan_ref)['owed']))
        f.call('plan', {'plan_ref': plan_ref}, role='spec-designer')
        f.approve(f.state()['modules']['M001']['plan_hash'], 'D-T'); f.call('freeze', {'decision_id': 'D-T'})
        a = self.implementation(SOURCE)
        f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'testing')

    def test_a_failure_in_the_frozen_test_is_revised_by_a_change_request(self):
        f = self.f
        self.inner.xml = ('<testsuite tests="1" failures="1"><testcase classname="SearchTest" name="query">'
                          '<failure>wrong value</failure></testcase></testsuite>')
        self.freeze(self.design()); self.implementation(SOURCE); f.call('accept', {'assignment_id': 'I1'})
        self.inner.fixture.split.compile()
        receipt_ref = execute(f.root, 'M001', 'BUILD1', 'U1', self.inner.fixture.unit_argv(), f.target, f.base / 'unit-red')
        result = stage_result(f.root, 'M001', 'BUILD1', [receipt_ref] + self.inner.fixture.split.receipts)
        f.submit(result, f.state()['modules']['M001']['assignments']['BUILD1']); f.call('accept', {'assignment_id': 'BUILD1'})
        f.call('diagnose', {'diagnosis_ref': f.ref('diagnosis.md', 'the test asserts the old value'), 'owner': 'module-orchestrator',
                           'root_cause': {'category': 'code', 'files': [self.target_path]}}, role='diagnostician')
        self.assertEqual(f.state()['modules']['M001']['diagnosis_submission']['report']['repair_route'], 'spec')
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'change')

    def test_the_skeleton_writes_a_test_source_per_logic_item(self):
        t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        out = t.f.root / 'staging/spec-designer/frozen-skeleton'
        files = spec_skeleton.write(t.f.root, 'M001', out)['files']
        upstream = json.loads(check_ref(files['upstream-test-plan.json']).read_text())
        asset = next(a for a in upstream['test_assets'] if a['path_ids'] == ['UNIT-M001-001'])
        source = next(name for name in files if name.startswith('test-sources/') and files[name] == asset['ref'])
        self.assertEqual(asset['kind'], 'test-source')
        import design_stage
        unit = next(p for p in design_stage.path_defaults(upstream) if p['path_id'] == 'UNIT-M001-001')  # its preparation is the Ledger's
        self.assertEqual((unit['unit_report']['required_test_ids'], unit['preparation']['status'], unit['preparation']['evidence_refs'], unit['expected_assertions'][0]['expected']),
                         (asset['required_test_ids'], 'prepared', [asset['ref']], True))
        text = check_ref(files[source]).read_text()
        for tid in asset['required_test_ids']:
            self.assertIn('fun ' + tid.split('#')[1] + '(', text); self.assertIn('class ' + tid.split('#')[0], text)


if __name__ == '__main__':
    unittest.main()
