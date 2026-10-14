"""Reused data is aligned where it is fetched and computed: an entity's sources, fetch conditions, derived fields and
invalidation are obligations the target binds and the tests prove; a target that already holds the data another way is
refactored or adapted by decision, never kept as a second computation."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import data_contract
import dimensions
from contracts import Rejected
import test_dimensions


class DataContractTests(unittest.TestCase):
    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = self.f = d.f
        self.fixture = f.ref('data-fixture.json', {'items': [{'price': 2}], 'rate': 1.5, 'total': 3})
        self.source = {'data_id': 'CART', 'source_ref': f.ref('cart-source.kt', 'class CartRepository { fun total() = items.sumOf { it.price } * rate }'),
                       'source_symbol': 'CartRepository', 'sources': ['items.price<-API-M001-001.response.price', 'rate<-table:settings.rate'],
                       'fetch_conditions': ['sort:createdAt desc', 'page:20'], 'derived_fields': ['total=sum(items.price)*rate'], 'invalidation': ['on:order-placed']}
        self.repo = f.target / 'm1/CartRepository.kt'
        self.contract = {'data_id': 'CART', 'fidelity': 'exact', 'fixture_contract_ref': self.fixture, 'existing_target': None,
                         'target': {'repository': str(self.repo) + '#CartRepository',
                                    'source_mapping': {k: 'CartRepository.' + k.split('<-')[0] for k in self.source['sources']},
                                    'fetch_mapping': {'sort:createdAt desc': 'orderBy(createdAt desc)', 'page:20': 'limit(20)'},
                                    'compute_mapping': {'total=sum(items.price)*rate': 'CartRepository.total'},
                                    'invalidation_mapping': {'on:order-placed': 'CartStore.clear'}}}
        self.items = {'D': {'dimension': 'Logic', 'data_ids': ['CART']}}

    def analysis(self, contract=None, entity=None, exclusions=()):
        return {'module_id': 'M001', 'data_inventory_ref': self.f.ref('data-inventory.json', {
            'schema_version': 1, 'module_id': 'M001', 'entities': [entity or self.source],
            'contracts': [] if exclusions else [contract or self.contract], 'exclusions': list(exclusions)})}

    def plan(self):
        return {'paths': [{'path_id': 'P1', 'kind': 'unit', 'fixture_contract_ref': self.fixture}],
                'dimension_trace': [{'item_id': 'D', 'assertions': [{'path_id': 'P1', 'assertion_id': 'A1',
                                     'data_obligations': sorted(data_contract.obligations('CART', self.source))}]}],
                'decision_envelope': {'allowed_alternatives': []}}

    def test_every_field_has_a_source_and_every_obligation_a_target_mapping(self):
        data_contract.load(self.analysis(), self.items)
        for field in data_contract.MAPPINGS:
            contract = copy.deepcopy(self.contract); contract['target'][field] = {}
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, 'omits a source obligation: ' + field):
                data_contract.load(self.analysis(contract), self.items)
        entity = copy.deepcopy(self.source); entity['sources'] = []
        with self.assertRaisesRegex(Rejected, 'names where its fields come from'):
            data_contract.load(self.analysis(entity=entity), self.items)
        entity = copy.deepcopy(self.source); entity.pop('derived_fields')
        with self.assertRaisesRegex(Rejected, 'source facet'):
            data_contract.load(self.analysis(entity=entity), self.items)
        contract = copy.deepcopy(self.contract); contract['target']['repository'] = 'relative/Repo.kt#Repo'
        with self.assertRaisesRegex(Rejected, 'absolute repository#symbol'):
            data_contract.load(self.analysis(contract), self.items)
        with self.assertRaisesRegex(Rejected, 'ownership'):
            data_contract.load(self.analysis(), {})
        with self.assertRaisesRegex(Rejected, 'data items need data_inventory_ref'):
            data_contract.load({'module_id': 'M001'}, self.items)
        data_contract.load(self.analysis(exclusions=[{'data_id': 'CART', 'reason': 'read by another leaf', 'evidence_refs': [self.fixture]}]), {})

    def test_a_target_that_already_holds_the_data_is_refactored_or_adapted_by_decision(self):
        contract = copy.deepcopy(self.contract); contract['existing_target'] = {'symbol': 'LegacyCartCache.total'}
        with self.assertRaisesRegex(Rejected, 'refactor/adapt decision with a reason'):
            data_contract.load(self.analysis(contract), self.items)
        contract['existing_target'].update(divergence='rounds the total to whole units', decision='refactor', reason='one computation: the source one')
        data_contract.load(self.analysis(contract), self.items)
        contract['existing_target']['decision'] = 'keep-both'
        with self.assertRaisesRegex(Rejected, 'refactor/adapt decision'):
            data_contract.load(self.analysis(contract), self.items)

    def test_every_obligation_is_proved_by_a_behavior_test_on_the_frozen_fixture(self):
        analysis, plan = self.analysis(), self.plan()
        data_contract.plan(analysis, self.items, plan)
        plan['dimension_trace'][0]['assertions'][0]['data_obligations'].remove('CART/derived_fields:total=sum(items.price)*rate')
        with self.assertRaisesRegex(Rejected, 'coverage incomplete: CART'):
            data_contract.plan(analysis, self.items, plan)
        plan = self.plan(); plan['paths'][0]['kind'] = 'build'
        with self.assertRaisesRegex(Rejected, 'actual behavior tests'):
            data_contract.plan(analysis, self.items, plan)
        plan = self.plan(); plan['paths'][0]['fixture_contract_ref'] = self.f.ref('other-fixture.json', {'items': []})
        with self.assertRaisesRegex(Rejected, 'frozen fixture'):
            data_contract.plan(analysis, self.items, plan)
        contract = copy.deepcopy(self.contract); contract.update(fidelity='approved-adaptation', alternative='server-side-total', reason='the target sums on the server')
        with self.assertRaisesRegex(Rejected, 'outside decision envelope'):
            data_contract.plan(self.analysis(contract), self.items, self.plan())
        plan = self.plan(); plan['decision_envelope']['allowed_alternatives'] = ['server-side-total']
        data_contract.plan(self.analysis(contract), self.items, plan)

    def full(self, contract=None, review='applicable'):
        complete = self.d.analysis('M001')
        logic = next(row for row in complete['dimensions'] if row['dimension'] == 'Logic')['items'][0]
        logic['data_ids'] = ['CART']
        complete['data_review'] = {'status': review, 'reason': 'the cart repository fetches and sums', 'evidence_refs': [self.source['source_ref']]}
        complete.update(self.analysis(contract))
        complete['module_id'] = 'M001'
        return complete, logic['item_id']

    def test_the_dimension_analysis_carries_the_inventory_and_the_freeze_settles_its_target(self):
        complete, iid = self.full()
        ref = self.f.ref('cart-dims.json', complete)
        _, items = dimensions.load(ref, 'M001')
        self.assertEqual(items[iid]['data_ids'], ['CART'])
        wrong, _ = self.full(review='not-applicable')
        with self.assertRaisesRegex(Rejected, 'applicability and inventory disagree'):
            dimensions.judge(self.f.ref('wrong-dims.json', wrong), 'M001')  # judged at registration; load reads what was accepted
        module = {'module_id': 'M001', 'dimension_analysis_ref': ref, 'write_paths': [str(self.f.target / 'm1')]}
        data_contract.freeze({}, module)
        unsettled, _ = self.full({**self.contract, 'target': None})
        with self.assertRaisesRegex(Rejected, "settles a data contract's target side"):
            data_contract.freeze({}, {**module, 'dimension_analysis_ref': self.f.ref('unsettled-dims.json', unsettled)})
        elsewhere, _ = self.full({**self.contract, 'target': {**self.contract['target'], 'repository': str(self.f.target / 'other/Repo.kt') + '#Repo'}})
        with self.assertRaisesRegex(Rejected, 'a file this module writes or the target already holds'):
            data_contract.freeze({}, {**module, 'dimension_analysis_ref': self.f.ref('elsewhere-dims.json', elsewhere)})

    def test_the_implementation_submits_the_repository_that_names_the_frozen_symbol(self):
        complete, iid = self.full()
        self.repo.parent.mkdir(parents=True, exist_ok=True); self.repo.write_text('class CartRepository(val api: Api) { fun total() = items.sumOf { it.price } * rate }')
        from contracts import file_ref
        code = file_ref(self.repo)
        result = {'code_files': [code], 'dimension_evidence': [{'item_id': iid, 'consumer_refs': [code]}]}
        _, items = dimensions.load(self.f.ref('impl-dims.json', complete), 'M001')
        data_contract.implementation(complete, items, result)
        with self.assertRaisesRegex(Rejected, 'lacks submitted production repository evidence'):
            data_contract.implementation(complete, items, {**result, 'dimension_evidence': []})
        self.repo.write_text('class CartRepo { fun total() = 0 }')
        code = file_ref(self.repo)
        with self.assertRaisesRegex(Rejected, 'does not name frozen production symbol'):
            data_contract.implementation(complete, items, {'code_files': [code], 'dimension_evidence': [{'item_id': iid, 'consumer_refs': [code]}]})


if __name__ == '__main__':
    unittest.main()
