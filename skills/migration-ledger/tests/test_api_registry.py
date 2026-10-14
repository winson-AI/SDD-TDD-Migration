"""A call found inside a leaf's scope after its allocation is registered to that leaf; its next plan carries it and nothing
above is re-split for it."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import api_contract
import dimensions
import ledger
from contracts import Rejected
import test_ledger
import test_progressive_fidelity


class ApiRegistryTests(unittest.TestCase):
    def setUp(self):
        self.a = a = test_progressive_fidelity.ApiContractTests(); a.setUp(); self.addCleanup(a.doCleanups)
        self.f = a.f
        complete = a.d.analysis('M001'); complete.update(a.analysis())
        complete['api_review'].update(status='applicable', discovery_refs=[a.source['source_ref']])
        self.logic = next(row for row in complete['dimensions'] if row['dimension'] == 'Logic')['items'][0]
        self.logic['api_ids'] = ['QUERY']
        self.allocated = complete
        self.ref = self.f.ref('allocated-dims.json', complete)
        self.s = {'modules': {'M001': {'module_id': 'M001', 'dimension_analysis_ref': self.ref, 'revision': 1}}}
        self.extra_call = {**copy.deepcopy(a.source), 'api_id': 'EXTRA', 'url': '/extra', 'source_ref': self.f.ref('extra-source.kt', 'fun extra() = GET("/extra")'), 'source_symbol': 'extra'}
        self.extra_contract = {'api_id': 'EXTRA', 'fidelity': 'exact', 'fixture_contract_ref': None, 'target': None}

    def payload(self, **over):
        return {'module_id': 'M001', 'api_id': 'EXTRA', 'item_id': self.logic['item_id'], 'call': self.extra_call, 'contract': self.extra_contract,
                'evidence_refs': [self.f.ref('extra-evidence.md', 'the call is made from the login screen source')], **over}

    def register(self, **over):
        api_contract.register(self.s, {'payload': self.payload(**over)}, {'role': 'module-orchestrator', 'instance_id': 'mo'}, sequence=7)

    def test_a_call_is_registered_to_its_leaf_and_item_once(self):
        for over, message in (({'api_id': 'QUERY', 'call': {**self.extra_call, 'api_id': 'QUERY'}, 'contract': {**self.extra_contract, 'api_id': 'QUERY'}}, 'api_id must be new'),
                              ({'api_id': 'OTHER'}, 'carries the call and the contract'), ({'module_id': 'M009'}, 'registered leaf'),
                              ({'item_id': 'NOPE'}, 'Logic/Adhesive owner'), ({'evidence_refs': []}, 'api-register evidence'),
                              ({'contract': {**self.extra_contract, 'fidelity': 'approved-adaptation'}}, 'approved alternative')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.register(**over)
        self.assertNotIn('api_registry', self.s) if 'api_registry' not in self.s else self.assertEqual(self.s['api_registry'], {})
        self.register()
        row = self.s['api_registry']['EXTRA']
        self.assertEqual((row['owner'], row['item_id'], row['sequence'], row['call']['url']), ('M001', self.logic['item_id'], 7, '/extra'))
        self.assertEqual(api_contract.added(self.s, 'M001'), {'EXTRA'}); self.assertEqual(api_contract.added(self.s, 'M002'), set())
        with self.assertRaisesRegex(Rejected, 'api_id must be new'):
            self.register()  # once

    def refined(self, name, with_extra=True):
        refined = copy.deepcopy(self.allocated)
        inventory = {'schema_version': 1, 'module_id': 'M001', 'calls': [self.a.source] + ([self.extra_call] if with_extra else []),
                     'contracts': [self.a.contract] + ([self.extra_contract] if with_extra else []), 'exclusions': []}
        refined['api_inventory_ref'] = self.f.ref(name + '-inventory.json', inventory)
        if with_extra:
            next(row for row in refined['dimensions'] if row['dimension'] == 'Logic')['items'][0]['api_ids'] = ['QUERY', 'EXTRA']
            refined['api_review']['discovery_refs'] = [self.a.source['source_ref'], self.extra_call['source_ref']]
        return refined

    def test_the_leafs_refinement_carries_what_was_registered_and_nothing_else_new(self):
        refined = self.refined('grown')
        with self.assertRaisesRegex(Rejected, 'changes analysis.api_inventory_ref'):
            dimensions.keeps(self.allocated, refined)  # nothing registered: the inventory grew on its own
        self.register()
        dimensions.keeps(self.allocated, refined, added=api_contract.added(self.s, 'M001'))
        self.assertTrue(dimensions.refines(self.ref, self.f.ref('grown-dims.json', refined), added={'EXTRA'}))
        stranger = self.refined('stranger'); stranger_inventory = self.f.ref('stranger-inventory.json', {
            **__import__('json').loads(Path(stranger['api_inventory_ref']['path']).read_text()),
            'calls': [self.a.source, {**self.extra_call, 'api_id': 'OTHER'}], 'contracts': [self.a.contract, {**self.extra_contract, 'api_id': 'OTHER'}]})
        stranger['api_inventory_ref'] = stranger_inventory
        with self.assertRaisesRegex(Rejected, 'changes analysis.api_inventory_ref'):
            dimensions.keeps(self.allocated, stranger, added={'EXTRA'})

    def test_the_operation_is_a_global_record_for_planning_roles(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups); f.global_plan()
        before = f.state()
        payload = {'module_id': 'M001', 'api_id': 'EXTRA', 'item_id': 'X', 'call': self.extra_call, 'contract': self.extra_contract,
                   'evidence_refs': [f.ref('evidence.md', 'seen in source')]}
        with self.assertRaisesRegex(Rejected, 'needs the leaf dimension analysis'):
            f.call('api-register', payload, role='module-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'principal role denied'):
            f.call('api-register', payload, role='implementer', module=None)
        with self.assertRaisesRegex(Rejected, 'incorrect global/module scope'):
            f.call('api-register', payload, role='module-orchestrator')
        self.assertEqual(f.state()['revision'], before['revision'])


if __name__ == '__main__':
    unittest.main()
