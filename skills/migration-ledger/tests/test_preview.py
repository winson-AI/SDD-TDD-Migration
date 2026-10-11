"""A plan is judged all at once and read-only before it is submitted: the refusal it would get, the gaps it would owe,
every freeze gate it does not pass yet and whether a person has to decide - one list for the author before submitting
and for the reviewer before reviewing, from one command instead of a rehearsal script each."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_dimensions
import test_ledger
from contracts import check_ref, digest, read_json


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()
        self.count = 0

    def preview(self, plan=None):
        self.count += 1
        return ledger.preview(self.f.root, 'M001', self.f.ref('preview-%d.json' % self.count, plan) if plan else None)

    def test_a_plan_that_would_be_accepted_and_frozen_reports_nothing_and_changes_nothing(self):
        before = self.f.state()
        plan = self.f.plan()
        out = self.preview(plan)
        self.assertEqual((out['refused'], out['owed'], out['gates'], out['human']), (None, [], [], None))
        self.assertEqual(out['plan_hash'], digest(plan))
        after = self.f.state()
        self.assertEqual((after['last_sequence'], after['modules']['M001']['plan']), (before['last_sequence'], None))  # judged on a copy
        self.assertFalse((self.f.root / 'reports/rejected-operation.json').exists())

    def test_a_plan_the_ledger_would_refuse_names_the_refusal_and_its_reading_hint(self):
        plan = self.f.plan()
        plan['paths'][0]['case_id'] = 'C9'  # a case the module does not hold
        out = self.preview(plan)
        self.assertTrue(out['refused']['reason'])
        self.assertIn('read_hint', out['refused'])
        self.assertEqual(out['gates'], [])  # nothing further is judged on a plan that is not accepted
        self.assertIsNone(self.f.state()['modules']['M001']['plan'])

    def test_the_current_plan_is_judged_against_every_freeze_gate(self):
        f = self.f
        f.call('plan', {'plan_ref': f.ref('plan.json', f.plan())}, role='spec-designer')
        self.assertEqual(self.preview()['gates'], [])
        f.call('issue', {'issue_id': 'STOP', 'kind': 'defect', 'summary': 'as planned the password is shown in clear text',
                         'applies_to': ['M001'], 'blocks': True}, role='module-orchestrator', module=None)
        out = self.preview()
        self.assertEqual([(row['gate'], row['read_hint']['section']) for row in out['gates']], [('issues', '操作矩阵')])
        self.assertRegex(out['gates'][0]['reason'], 'blocking issue open for this module: STOP')
        self.assertEqual(out['plan_hash'], f.state()['modules']['M001']['plan_hash'])

    def test_the_command_line_prints_the_same_report(self):
        plan = self.f.ref('cli-plan.json', self.f.plan())
        script = Path(__file__).resolve().parents[1] / 'scripts/ledger.py'
        done = subprocess.run([sys.executable, str(script), 'preview', '--root', str(self.f.root), '--module', 'M001', '--plan', plan['path']],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual((out['module_id'], out['refused'], out['gates']), ('M001', None, []))


class PreviewOwedTests(unittest.TestCase):
    def test_a_run_without_a_journal_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(ValueError) as caught:
            ledger.preview(empty, 'M001')
        self.assertEqual(str(caught.exception), 'run not initialised: no journal under ' + str(Path(empty).resolve()))  # the run, not the module, is what is missing

    def test_what_a_plan_owes_and_every_gate_it_fails_are_reported_together(self):
        d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f
        d.root(('Logic', 'Resource')); f.split(d.proposal(('Logic', 'Resource')))
        analysis = read_json(check_ref(f.state()['modules']['M001']['dimension_analysis_ref']))
        resource = analysis['dimensions'][3]['items']
        detail = {**copy.deepcopy(resource[0]), 'item_id': resource[0]['item_id'] + '.badge', 'detail_of': resource[0]['item_id'],
                  'source_resource': 'legacy/badge.svg', 'target_resource': str(f.target / 'm1/badge.svg')}
        resource.append(detail)
        plan = d.leaf_plan(); plan['dimension_analysis_ref'] = f.ref('M001-detailed.json', analysis)
        f.call('issue', {'issue_id': 'STOP', 'kind': 'defect', 'summary': 'as planned the password is shown in clear text',
                         'applies_to': ['M001'], 'blocks': True}, role='module-orchestrator', module=None)
        before = f.state()['last_sequence']
        out = ledger.preview(f.root, 'M001', f.ref('untraced.json', plan))
        self.assertIsNone(out['refused'])
        self.assertIn('SPEC dimension trace must cover every allocated item: ' + detail['item_id'], [row['reason'] for row in out['owed']])
        self.assertTrue(all(row['reason'].startswith(('SPEC dimension trace', 'OpenSpec ')) for row in out['owed']), out['owed'])
        self.assertEqual([row['gate'] for row in out['gates']], ['issues'])  # the gap and the gate, in one report
        self.assertEqual(f.state()['last_sequence'], before)
        self.assertIsNone(f.state()['modules']['M001']['plan'])
        self.assertEqual([iid for iid in f.state()['issues'] if iid.startswith('OWED-')], [])  # a preview records nothing


if __name__ == '__main__':
    unittest.main()
