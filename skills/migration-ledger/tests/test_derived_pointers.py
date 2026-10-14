"""What the Ledger can derive it fills; where a Logic or Adhesive item lands is owed before freeze, not refused."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dimensions
import minimal_plan
from contracts import Rejected, carrying
import test_dimensions


class DerivedPointerTests(unittest.TestCase):
    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)

    def analysis(self, *dropped, dimension=None):
        analysis = self.d.analysis('M010', kinds=('Logic', 'Resource'))
        for row in analysis['dimensions']:
            for item in row['items'] if dimension in (None, row['dimension']) else []:
                for field in dropped:
                    item.pop(field, None)
        return analysis

    def test_a_logic_binding_is_owed_and_a_resource_binding_is_required(self):
        with carrying() as gaps:
            dimensions.settled(self.analysis('target_binding', dimension='Logic'))
        self.assertEqual(len(gaps), 1); self.assertIn('M010-Logic: the plan settles target_binding before freeze', gaps[0])
        with carrying(), self.assertRaisesRegex(Rejected, 'M010-Resource: the plan settles consumer before freeze'):
            dimensions.settled(self.analysis('consumer'))
        with self.assertRaisesRegex(Rejected, 'M010-Logic: the plan settles target_binding'):
            dimensions.settled(self.analysis('target_binding', dimension='Logic'))  # outside a judgement nothing carries it

    def test_the_one_fixture_a_plan_brings_is_its_verification_fixture(self):
        f = self.d.f
        ref = f.ref('open-allocation.json', self.analysis('target_binding', dimension='Logic'))
        boundary = {'acceptance_owner': 'M010', 'independent_observation': 'its own result', 'fixture_contract_ref': None, 'case_ids': ['C1']}
        module = {'module_id': 'M010', 'dimension_analysis_ref': ref, 'case_ids': ['C1'], 'behavior_review': {'verification': boundary}}
        fixture = f.ref('defs/provider-fixture.json', {'account': 'fixed'})
        plan = lambda defs: {'source_closure': {'verification': {}}, 'tasks': [],
                             'paths': [{'path_id': 'P1', 'kind': 'automation', 'fixture_contract_ref': None}, {'path_id': 'B1', 'kind': 'build'}],
                             'definitions': defs}
        out = minimal_plan.complete({}, module, plan([{**fixture, 'kind': 'test-fixture'}, {**f.ref('defs/spec.md', 's'), 'kind': 'spec'}]))
        self.assertEqual(out['source_closure']['verification']['fixture_contract_ref'], fixture)
        self.assertEqual([p.get('fixture_contract_ref') for p in out['paths']], [fixture, None])  # behavior paths only
        two = minimal_plan.complete({}, module, plan([{**fixture, 'kind': 'test-fixture'}, {**f.ref('defs/other-fixture.json', {}), 'kind': 'test-fixture'}]))
        self.assertIsNone(two['source_closure']['verification']['fixture_contract_ref'])  # two: the leaf says which


if __name__ == '__main__':
    unittest.main()
