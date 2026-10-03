"""The host submits every mechanical step of a module with one call; each still passes its own guards."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_ledger
from contracts import Rejected


class AdvanceTests(unittest.TestCase):
    MO = {'role': 'module-orchestrator', 'instance_id': 'mo-M001'}

    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()

    def test_dispatches_the_next_worker_and_hands_back_its_card(self):
        f = self.f
        out = ledger.advance(f.root, self.MO, 'M001')
        [step] = out['applied']
        self.assertEqual((step['operation'], step['role'], step['instance_id']), ('assign', 'implementer', 'implementer-M001'))
        a = f.state()['modules']['M001']['assignments'][step['assignment_id']]
        self.assertFalse(a['closed'])
        self.assertEqual((out['next_step']['operation'], out['next_step']['role']), ('await-result', 'implementer'))
        self.assertTrue(Path(out['card']).is_file())  # the card of the worker just dispatched
        self.assertEqual(ledger.advance(f.root, self.MO, 'M001')['applied'], [])  # nothing mechanical is left

    def test_the_host_may_name_the_instance_it_dispatches(self):
        out = ledger.advance(self.f.root, self.MO, 'M001', {'implementer': 'coder-7'})
        self.assertEqual(out['applied'][0]['instance_id'], 'coder-7')

    def test_accepts_a_green_result_and_stops_where_judgement_is_needed(self):
        f = self.f; f.implementation()
        a, result = f.make_test_result()
        f.submit(result, a)
        out = ledger.advance(f.root, self.MO, 'M001')
        self.assertEqual([x['operation'] for x in out['applied']], ['accept'])
        self.assertEqual(out['next_step']['operation'], 'complete')  # the DoD is still the orchestrator's decision
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')

    def test_only_the_module_orchestrator_may_advance(self):
        with self.assertRaisesRegex(Rejected, 'role denied'):
            ledger.advance(self.f.root, {'role': 'implementer', 'instance_id': 'coder'}, 'M001')
        with self.assertRaisesRegex(Rejected, 'unknown module'):
            ledger.advance(self.f.root, self.MO, 'M999')


if __name__ == '__main__':
    unittest.main()
