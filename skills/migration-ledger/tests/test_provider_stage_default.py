"""A dependent plans against its provider's accepted code; asking for the provider's verification is the exception and says why."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import behavior_contract
import ledger
from contracts import Rejected
import test_ledger
import test_waves
from test_behavior_contract import review


class ProviderStageDefaultTests(unittest.TestCase):
    def test_a_missing_stage_means_implemented_and_verified_needs_a_reason(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        module = {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M001'], 'scope': {'in': ['x'], 'out': [], 'requirement_ids': ['R1']}}
        module['behavior_review'] = review(f, module)
        row = module['behavior_review']['verification']['provider_inputs'][0]
        row.pop('required_stage'); row.pop('reason')
        behavior_contract.verification(module)  # implemented by default
        row['required_stage'] = 'verified'
        with self.assertRaisesRegex(Rejected, 'verified states its reason'):
            behavior_contract.verification(module)
        row['reason'] = 'the slice is verified end to end against the completed provider'
        behavior_contract.verification(module)

    def test_the_cursor_reads_a_missing_stage_as_implemented(self):
        tasks = {'plan': {'tasks': [{'task_id': 'T1'}]}, 'code_baseline': 'c1', 'accepted_task_ids': ['T1']}
        needs = {'behavior_review': {'verification': {'provider_inputs': [{'module_id': 'M001'}]}}}
        s = {'modules': {'M001': test_waves.leaf('M001', **tasks), 'M002': test_waves.leaf('M002', 'M001', **needs)}, 'module_groups': {}}
        row, = ledger.providers(s, s['modules']['M002'])
        self.assertEqual((row['required_stage'], row['ready']), ('implemented', True))
        s['modules']['M002']['behavior_review']['verification']['provider_inputs'][0]['required_stage'] = 'verified'
        self.assertFalse(ledger.providers(s, s['modules']['M002'])[0]['ready'])  # asked for: the provider is not completed


if __name__ == '__main__':
    unittest.main()
