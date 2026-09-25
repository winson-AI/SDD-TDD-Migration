"""Two-tier model routing: advice, no-downgrade enforcement, config, and persisted usage."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import model_routing as mr
import test_ledger
from contracts import Rejected


class ModelRoutingUnitTests(unittest.TestCase):
    def test_advise_tiers(self):
        self.assertEqual(mr.advise('test-runner'), 'low_cost')                 # execute
        self.assertEqual(mr.advise('module-orchestrator', operation='accept'), 'low_cost')  # mechanical
        self.assertEqual(mr.advise('implementer'), 'strong')                   # per decision: implementer=strong
        self.assertEqual(mr.advise('fixer'), 'strong')
        self.assertEqual(mr.advise('global-orchestrator'), 'strong')
        for role in ('spec-designer', 'diagnostician', 'auditor'):
            self.assertEqual(mr.advise(role), 'strong')
        self.assertEqual(mr.advise('spec-designer', operation='plan'), 'strong')

    def test_escalation_forces_strong(self):
        self.assertEqual(mr.advise('test-runner', escalate=True), 'strong')

    def test_enforce_no_downgrade(self):
        mr.enforce('test-runner', tier='low_cost')            # ok
        mr.enforce('diagnostician', tier='strong')            # ok
        with self.assertRaisesRegex(Rejected, 'low-cost'):
            mr.enforce('diagnostician', tier='low_cost')
        with self.assertRaisesRegex(Rejected, 'low-cost'):
            mr.enforce(operation='freeze', tier='low_cost')

    def test_record_presence_triggered(self):
        self.assertIsNone(mr.record({}, role='test-runner'))
        self.assertEqual(mr.record({'model': 'cheap'}, role='test-runner'),
                         {'model': 'cheap', 'model_tier': 'low_cost'})
        self.assertEqual(mr.record({'model': 'x', 'model_tier': 'strong'}, role='auditor')['model_tier'], 'strong')
        with self.assertRaises(Rejected):
            mr.record({'model': 'cheap', 'model_tier': 'low_cost'}, role='auditor')

    def test_validate_config(self):
        good = {'strong': {'model': 'big'}, 'low_cost': {'model': 'small'}, 'default_tier': 'strong'}
        mr.validate_config(good)
        with self.assertRaises(Rejected):
            mr.validate_config({'strong': {}, 'low_cost': {'model': 's'}})
        with self.assertRaises(Rejected):
            mr.validate_config({**good, 'default_tier': 'cheap'})
        with self.assertRaisesRegex(Rejected, 'downgrade'):
            mr.validate_config({**good, 'overrides': {'auditor': 'low_cost'}})


class ModelRoutingLedgerTests(unittest.TestCase):
    def fixture(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def test_cursor_carries_model_tier(self):
        f = self.fixture()
        steps = [s for s in f.state()['next_steps'] if s.get('role')]
        self.assertTrue(steps and all('model_tier' in s for s in steps))
        self.assertIn(f.state()['global_next_step'].get('model_tier'), (None, 'low_cost', 'strong'))

    def test_session_records_model_and_enforces_tier(self):
        f = self.fixture()
        with self.assertRaisesRegex(Rejected, 'low-cost'):
            f.call('session', {'role': 'diagnostician', 'session_id': 'd1', 'model': 'cheap', 'model_tier': 'low_cost'})
        f.call('session', {'role': 'test-runner', 'session_id': 't1', 'model': 'cheap', 'model_tier': 'low_cost'})
        usage = f.state()['model_usage']
        self.assertTrue(any(r['role'] == 'test-runner' and r['model'] == 'cheap' and r['model_tier'] == 'low_cost' for r in usage))
        # Persisted immutably and reprojected.
        projected = (Path(f.root) / 'ledger/model-usage.json')
        self.assertTrue(projected.is_file())


if __name__ == '__main__':
    unittest.main()
