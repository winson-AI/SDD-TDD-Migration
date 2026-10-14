"""A stage whose preflight asks nothing the Ledger cannot check by itself - every input exists and is the bytes its
reference names, the subject is current - is preflighted by the Ledger when the actor submits: no role writes a
readiness report for it, and an input that is not as referenced refuses the operation."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_context_readiness
from contracts import Rejected, check_ref, digest, read_json


class MechanicalReceiptTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_context_readiness.ContextReadinessTests(); t.setUp(); self.addCleanup(t.doCleanups)
        t.auto_context = False  # nobody writes a report

    def test_registration_global_plan_plan_and_freeze_are_preflighted_by_the_ledger(self):
        t = self.t
        t.global_plan()  # register and global-plan, with no report from the orchestrator
        step = next(x for x in t.state()['next_steps'] if x['module_id'] == 'M001')
        self.assertTrue(step['context_gate']['mechanical'])  # the step says so
        plan = t.plan(); ref = t.ref('plan.json', plan)
        t.raw('plan', {'plan_ref': ref}, role='spec-designer')
        m = t.state()['modules']['M001']
        report = read_json(check_ref(m['context_acceptances']['plan']['report_ref']))
        self.assertEqual((report['mechanical'], report['stage'], report['draft_ref'], report['producer']['role']), (True, 'planning', ref, 'spec-designer'))
        self.assertTrue(Path(m['context_acceptances']['plan']['report_ref']['path']).resolve().is_relative_to((t.root / 'artifacts' / 'preflight').resolve()))
        self.assertTrue(all(c['status'] == 'ready' and c['summary'].startswith('checked by the Ledger') for c in report['checks'].values()))
        t.approve(digest(plan), 'D1'); t.raw('freeze', {'decision_id': 'D1'})
        self.assertEqual(t.state()['modules']['M001']['phase'], 'frozen')
        self.assertTrue(read_json(check_ref(t.state()['context_acceptances']['global-plan']['report_ref']))['mechanical'])

    def test_an_input_that_is_not_as_referenced_refuses_the_operation(self):
        t = self.t
        t.global_plan()
        spec = Path(t.state()['global_spec']['path']); spec.write_text(spec.read_text() + '\n# edited after it was cited\n')
        with self.assertRaisesRegex(Rejected, 'hash mismatch|drift|not as referenced'):
            t.raw('plan', {'plan_ref': t.ref('plan.json', t.plan())}, role='spec-designer')

    def test_a_report_the_actor_writes_itself_still_rides_the_operation(self):
        t = self.t
        t.global_plan()
        plan = t.plan(); ref = t.ref('plan.json', plan)
        own = t.ref('own-report.json', t.report('planning', 'M001', 'spec-designer', ref))
        t.raw('plan', {'plan_ref': ref, 'context_ref': own}, role='spec-designer')
        self.assertEqual(t.state()['modules']['M001']['context_acceptances']['plan']['report_ref'], own)


if __name__ == '__main__':
    unittest.main()
