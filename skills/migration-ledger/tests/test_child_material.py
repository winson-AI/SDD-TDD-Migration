"""A split whose children only say where to cut: the Ledger cuts their four-dimension analyses from the parent's and drafts
their behaviour reviews from the inventory, and the split is accepted as if they had written them."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import behavior_contract
import child_material
import dimensions
import test_dimensions


class ChildMaterialTests(unittest.TestCase):
    def test_children_that_only_say_where_to_cut_get_their_analyses_from_the_parent(self):
        d = test_dimensions.DimensionTests(methodName='runTest'); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f
        kinds = ('Logic', 'Adhesive', 'Resource')
        d.root(kinds)
        p = d.proposal(kinds)
        for child in p['children']:
            del child['dimension_analysis_ref']
        del p['dimension_partition_review_ref']
        f.split(p)
        s = f.state()
        child = s['modules']['M001']
        data, items = dimensions.load(child['dimension_analysis_ref'], 'M001')
        self.assertEqual(sorted(items), sorted('M001-M010-' + k for k in kinds))
        self.assertEqual({tuple(i['parent_item_ids']) for i in items.values()}, {('M010-' + k,) for k in kinds})
        self.assertEqual(data['parent_ref'], d.root_ref)
        self.assertTrue(s['module_groups']['M010']['decomposition_ref']['path'].endswith('.json'))
        f.global_plan()  # the cut analyses stand as allocations: global coverage accepts them

    def test_a_drafted_behaviour_review_is_one_the_contract_accepts(self):
        d = test_dimensions.DimensionTests(methodName='runTest'); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f
        evidence = f.ref('feature-evidence.md', 'the phone entry screen and its send action')
        child = {'module_id': 'M001', 'case_ids': ['C1', 'C2'], 'dependencies': ['M002'], 'functional_paths': ['Login/Phone'],
                 'scope': {'in': ['phone entry'], 'out': [], 'requirement_ids': ['R1']}}
        parent = {'module_id': 'M010', 'behavior_review': {'production_binding': 'the login route', 'evidence_refs': [evidence]}}
        features = [{'feature_id': 'F1', 'trigger': 'type a number', 'observable_result': 'the code screen opens', 'case_ids': ['C1', 'C2'],
                     'evidence_refs': [evidence]}]
        child['behavior_review'] = child_material.review(parent, child, features)
        behavior_contract.review(child, child['behavior_review'])
        value = behavior_contract.verification(child)
        self.assertEqual((child['behavior_review']['entry'], value['provider_inputs']), ('type a number', [{'module_id': 'M002'}]))


if __name__ == '__main__':
    unittest.main()
