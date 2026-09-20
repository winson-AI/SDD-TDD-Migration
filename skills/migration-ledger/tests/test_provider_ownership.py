"""Explicit capability ownership is independent of broad write locks."""
import copy
import unittest
from pathlib import Path

import test_reuse
import reuse
from contracts import Rejected, file_ref


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.f = test_reuse.ReuseTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def candidate(self, owner=None, external=False):
        f = self.f
        plan, review, catalog, provider = f.selected_plan(external)
        catalog['schema_version'] = 2
        catalog['capabilities'][0].update(provider_owner_module_id=owner,
            ownership_evidence_ref=f.ref('ownership.md', 'Reviewed actual producer versus existing baseline'))
        review['catalog_ref'] = f.ref('owned-catalog.json', catalog)
        f.save_review(plan, review)
        return plan, review, catalog, provider

    def test_baseline_under_overlapping_sibling_write_scopes_has_no_false_dependency(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': [],
                           'write_paths': [str(f.target)]}, role='global-orchestrator', module=None)
        plan, _, _, _ = self.candidate()
        f.freeze(plan)
        self.assertEqual(f.state()['modules']['M001']['dependencies'], [])
        f.assign('implementer', 'I')

    def test_explicit_owner_requires_only_that_leaf_and_its_write_scope(self):
        plan, _, catalog, _ = self.candidate('M002')
        f = self.f
        module = copy.deepcopy(f.state()['modules']['M001'])
        modules = {**f.state()['modules'], 'M002': {'write_paths': [str(f.target)], 'dependencies': []},
                   'M003': {'write_paths': [str(f.target)], 'dependencies': []}}
        with self.assertRaisesRegex(Rejected, 'registered dependency'):
            reuse.validate_plan(plan, module, catalog['sources'], modules, str(f.legacy))
        module['dependencies'] = ['M002']; modules['M001'] = module
        reuse.validate_plan(plan, module, catalog['sources'], modules, str(f.legacy))
        modules['M002']['write_paths'] = [str(f.target/'other')]
        with self.assertRaisesRegex(Rejected, 'owner write scope'):
            reuse.validate_plan(plan, module, catalog['sources'], modules, str(f.legacy))

    def test_missing_parent_external_owner_and_dependency_cycles_rejected(self):
        f = self.f
        for variant in ('missing', 'parent', 'external', 'cycle', 'omitted'):
            plan, review, cat, _ = self.candidate('M002', external=variant == 'external')
            modules = copy.deepcopy(f.state()['modules'])
            if variant != 'missing': modules['M002'] = {'write_paths': [str(f.target)], 'dependencies': []}
            if variant == 'parent': modules['M002']['decomposition_required'] = True
            if variant == 'cycle':
                modules['M001']['dependencies'] = ['M002']; modules['M002']['dependencies'] = ['M001']
            if variant == 'omitted': del cat['capabilities'][0]['provider_owner_module_id']
            review['catalog_ref'] = f.ref('bad-owner.json', cat); f.save_review(plan, review)
            with self.subTest(variant=variant), self.assertRaises(Rejected):
                reuse.validate_plan(plan, modules['M001'], cat['sources'], modules, str(f.legacy))

    def test_null_owner_keeps_both_provider_and_ownership_evidence_live(self):
        plan, _, cat, provider = self.candidate()
        self.f.freeze(plan)
        evidence = Path(cat['capabilities'][0]['ownership_evidence_ref']['path'])
        original = evidence.read_text(); evidence.write_text('changed owner claim')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): reuse.verify(plan)
        evidence.write_text(original); provider.write_text('changed implementation')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): reuse.verify(plan)

    def test_self_owner_avoids_self_dependency_but_adapt_still_rejects_drift(self):
        f = self.f
        plan, review, cat, provider = self.candidate('M001')
        # Own provider must actually lie in the owner's write authorization.
        relocated = f.target/'m1/provider.py'; relocated.parent.mkdir(exist_ok=True)
        relocated.write_bytes(provider.read_bytes())
        cat['capabilities'][0]['provider_refs'] = [file_ref(relocated)]
        review['catalog_ref'] = f.ref('self-owner.json', cat)
        review['mappings'][0]['decision'] = 'adapt'; f.save_review(plan, review)
        f.freeze(plan)
        relocated.write_text('new provider')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): f.assign('implementer', 'I')

    def test_v1_keeps_old_dependency_check(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'write_paths': [str(f.target)]},
               role='global-orchestrator', module=None)
        plan, _, _, _ = f.selected_plan()
        with self.assertRaisesRegex(Rejected, 'registered dependency'):
            f.freeze(plan)

    def test_conflicting_owner_is_rejected_using_accepted_ledger_ownership(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'write_paths': [str(f.target)]},
               role='global-orchestrator', module=None)
        plan, review, cat, _ = self.candidate()
        f.freeze(plan)
        s = f.state()
        self.assertEqual(s['modules']['M001']['provider_owners'][0]['owner'], None)
        cat['capabilities'][0]['provider_owner_module_id'] = 'M002'
        review['module_id'] = 'M002'; plan['module_id'] = 'M002'
        review['catalog_ref'] = f.ref('conflicting-catalog.json', cat)
        plan['reuse_plan_ref'] = f.ref('conflicting-review.json', review)
        with self.assertRaisesRegex(Rejected, 'conflicting active capability owners'):
            reuse.validate_plan(plan, s['modules']['M002'], cat['sources'], s['modules'], str(f.legacy))
