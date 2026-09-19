"""Declared reuse sources, semantic mapping, implementation binding and version drift."""
import copy
from pathlib import Path
import unittest

import test_ledger
from contracts import Rejected, baseline, digest, file_ref, read_json
import reuse


class ReuseTests(unittest.TestCase):
    setUp = test_ledger.FlowTests.setUp
    call = test_ledger.FlowTests.call
    state = test_ledger.FlowTests.state
    ref = test_ledger.FlowTests.ref
    plan = test_ledger.FlowTests.plan
    attach_reuse = test_ledger.FlowTests.attach_reuse
    global_plan = test_ledger.FlowTests.global_plan
    approve = test_ledger.FlowTests.approve
    assign = test_ledger.FlowTests.assign
    submit = test_ledger.FlowTests.submit
    implementation = test_ledger.FlowTests.implementation
    make_test_result = test_ledger.FlowTests.make_test_result

    def selected_plan(self, external=False):
        plan = self.attach_reuse(self.plan())
        review = read_json(Path(plan['reuse_plan_ref']['path']))
        catalog = read_json(Path(review['catalog_ref']['path']))
        source = catalog['sources'][0]
        if external:
            root = self.base / 'library'; root.mkdir(exist_ok=True)
            source = {'source_id': 'LIB', 'root': str(root.resolve()), 'module_paths': [str(root.resolve())]}
            catalog['sources'].append(source)
            catalog['source_reviews'].append({**catalog['source_reviews'][0], 'source_id': 'LIB', 'scanned_paths': source['module_paths']})
        provider = Path(source['root']) / 'shared/provider.py'
        provider.parent.mkdir(exist_ok=True)
        provider.write_text('def result(): return 2\n')
        capability = {'capability_id': 'CAP1', 'source_id': source['source_id'], 'name': 'result provider',
                     'version': 'v1', 'semantics': {key: 'reviewed behavior' for key in
                         ('intent', 'inputs', 'outputs', 'preconditions', 'side_effects', 'errors', 'state_lifecycle')},
                     'api_surface': ['result()'], 'constraints': [], 'provider_refs': [file_ref(provider)]}
        catalog['capabilities'] = [capability]
        review['catalog_ref'] = self.ref('selected-catalog.json', catalog)
        review['mappings'][0].update(capability_id='CAP1', decision='reuse', integration={
            'mode': 'source-module' if external else 'existing-target', 'version': 'v1', 'locator': 'shared.provider.result',
            'configuration': 'production DI binding', 'transitive_dependencies': ['none'], 'compatibility': 'Python fixture',
            'evidence_refs': [self.ref('feasibility.md', 'Target can import provider v1; semantics reviewed')]})
        review['mappings'][0]['fidelity'] = {
            'legacy_root': str(self.legacy),
            'legacy_source_refs': [self.ref('legacy/entry.py', 'def result(): return 2\n')],
            'alignment_ref': self.ref('fidelity.md', 'Legacy entry returns 2; provider matches; replay P1/A1 after coding'),
            'scenarios': [{'scenario_id': 'FID1', 'path_id': 'P1', 'assertion_ids': ['A1'],
                           'legacy_behavior': 'entry returns 2', 'reuse_behavior': 'provider returns 2',
                           'reproduction_strategy': 'call real entry with same input; A1 expects 2'}]}
        plan['reuse_plan_ref'] = self.ref('selected-review.json', review)
        return plan, review, catalog, provider

    def save_review(self, plan, review):
        plan['reuse_plan_ref'] = self.ref('review-'+str(self.n)+'.json', review)

    def freeze(self, plan):
        self.global_plan()
        self.call('plan', {'plan_ref': self.ref('selected-plan.json', plan)}, role='spec-designer')
        self.approve(digest(plan), 'D1')
        self.call('freeze', {'decision_id': 'D1'})

    def test_target_semantics_reach_frozen_plan_and_dispatch(self):
        plan, _, _, _ = self.selected_plan()
        self.freeze(plan)
        assignment = self.assign('implementer', 'I1')
        self.assertEqual(assignment['freeze_id'], digest(plan))
        self.assertIn('reuse_plan_ref', self.state()['modules']['M001']['plan'])

    def test_missing_semantics_unreviewed_sources_and_unknown_capabilities_rejected(self):
        for variant in ('missing-semantics', 'unavailable', 'unknown-capability', 'wrong-source-set'):
            plan, review, cat, _ = self.selected_plan()
            if variant == 'missing-semantics': del cat['capabilities'][0]['semantics']['errors']
            if variant == 'unavailable': cat['source_reviews'][0]['status'] = 'unavailable'
            if variant == 'unknown-capability': review['mappings'][0]['capability_id'] = 'MISSING'
            if variant == 'wrong-source-set': cat['sources'][0]['root'] = str(self.base)
            review['catalog_ref'] = self.ref('bad-catalog.json', cat); self.save_review(plan, review)
            with self.subTest(variant=variant), self.assertRaises(Rejected):
                self.call('plan', {'plan_ref': self.ref('bad-plan.json', plan)}, role='spec-designer')

    def test_mapping_must_cover_requirements_and_point_to_existing_tasks_and_paths(self):
        for field, value in (('requirement_ids', ['OTHER']), ('task_ids', ['OTHER']), ('path_ids', ['OTHER']),
                             ('binding_plan', ''), ('verification', '')):
            plan, review, _, _ = self.selected_plan()
            review['mappings'][0][field] = value; self.save_review(plan, review)
            with self.subTest(field=field), self.assertRaises(Rejected):
                self.call('plan', {'plan_ref': self.ref('bad-plan.json', plan)}, role='spec-designer')

    def test_provider_version_drift_invalidates_only_consumers(self):
        plan, review, catalog, provider = self.selected_plan()
        unused = provider.with_name('unused.py'); unused.write_text('old unused')
        catalog['capabilities'].append({**catalog['capabilities'][0], 'capability_id': 'CAP2', 'provider_refs': [file_ref(unused)]})
        review['catalog_ref'] = self.ref('with-unused.json', catalog); self.save_review(plan, review)
        self.freeze(plan)
        unused.write_text('new unused')
        self.assertFalse(self.state()['observed_invalidations'])
        provider.write_text('def result(): return 3\n')
        self.assertEqual(self.state()['observed_invalidations'][0]['module_id'], 'M001')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.assign('implementer', 'I1')

    def test_stale_provider_blocks_freeze(self):
        plan, _, _, provider = self.selected_plan()
        self.global_plan()
        self.call('plan', {'plan_ref': self.ref('plan.json', plan)}, role='spec-designer')
        self.approve(digest(plan), 'D1')
        provider.write_text('changed')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.call('freeze', {'decision_id': 'D1'})

    def test_implementation_requires_real_binding_trace_and_matching_version(self):
        plan, _, _, _ = self.selected_plan()
        self.freeze(plan)
        with self.assertRaisesRegex(Rejected, 'trace every selected reuse'):
            self.implementation()
        code = self.target / 'm1/code.py'
        result = {'task_trace': [{'task_id': 'T1', 'files': [str(code)]}], 'reuse_trace': [{
            'mapping_id': 'MAP1', 'resolved_version': 'v1', 'files': [str(code)],
            'binding_evidence_ref': self.ref('binding.md', 'production entry -> shared.provider.result v1')}]}
        reuse.validate_implementation(plan, result)
        for mutation in ({'resolved_version': 'v2'}, {'files': [str(self.base / 'unrelated.py')]}, {'binding_evidence_ref': None}):
            changed = copy.deepcopy(result); changed['reuse_trace'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(Rejected):
                reuse.validate_implementation(plan, changed)

        assignment = self.state()['modules']['M001']['assignments']['I1']
        evidence = result['reuse_trace'][0]['binding_evidence_ref']
        result.update(schema_version=1, kind='implementation', run_id='demo', module_id='M001',
                      assignment_id='I1', actor_instance_id='implementer', freeze_id=digest(plan),
                      code_files=[file_ref(code)], code_baseline=baseline([file_ref(code)]),
                      production_binding_evidence=evidence)
        self.submit(result, assignment)
        self.call('accept', {'assignment_id': 'I1'})
        self.assertEqual(self.state()['modules']['M001']['phase'], 'testing')
        self.assertTrue(list(self.root.glob('openspec/changes/*/reuse.md')))
        assignment, result = self.make_test_result()
        self.submit(result, assignment)
        self.call('accept', {'assignment_id': assignment['assignment_id']})
        self.assertEqual(self.state()['modules']['M001']['results']['P1']['quality'], 'green-passed')

    def test_missing_fidelity_cannot_freeze_reuse_adapt_or_reference(self):
        for decision in ('reuse', 'adapt', 'reference'):
            plan, review, _, _ = self.selected_plan()
            row = review['mappings'][0]
            row['decision'] = decision
            if decision == 'reference': row['integration']['mode'] = 'reference-only'
            del row['fidelity']
            self.save_review(plan, review)
            with self.subTest(decision=decision), self.assertRaisesRegex(Rejected, 'fidelity'):
                self.call('plan', {'plan_ref': self.ref('missing-fidelity.json', plan)}, role='spec-designer')

    def test_fidelity_cannot_substitute_provider_for_legacy_baseline(self):
        for variant in ('wrong-root', 'provider-as-source', 'no-source'):
            plan, review, _, provider = self.selected_plan()
            fidelity = review['mappings'][0]['fidelity']
            if variant == 'wrong-root': fidelity['legacy_root'] = str(self.target)
            if variant == 'provider-as-source': fidelity['legacy_source_refs'] = [file_ref(provider)]
            if variant == 'no-source': fidelity['legacy_source_refs'] = []
            self.save_review(plan, review)
            with self.subTest(variant=variant), self.assertRaises(Rejected):
                self.call('plan', {'plan_ref': self.ref('bad-baseline.json', plan)}, role='spec-designer')

    def test_fidelity_requires_reproducible_frozen_path_assertions(self):
        for variant in ('missing-path', 'wrong-path', 'wrong-assertion', 'no-assertion', 'no-strategy', 'no-report'):
            plan, review, _, _ = self.selected_plan()
            fidelity = review['mappings'][0]['fidelity']
            scenario = fidelity['scenarios'][0]
            if variant == 'missing-path': fidelity['scenarios'] = []
            if variant == 'wrong-path': scenario['path_id'] = 'OTHER'
            if variant == 'wrong-assertion': scenario['assertion_ids'] = ['OTHER']
            if variant == 'no-assertion': scenario['assertion_ids'] = []
            if variant == 'no-strategy': scenario['reproduction_strategy'] = ''
            if variant == 'no-report': fidelity['alignment_ref'] = None
            self.save_review(plan, review)
            with self.subTest(variant=variant), self.assertRaises(Rejected):
                self.call('plan', {'plan_ref': self.ref('bad-fidelity.json', plan)}, role='spec-designer')

    def test_legacy_or_alignment_drift_invalidates_fidelity(self):
        plan, review, _, _ = self.selected_plan()
        self.freeze(plan)
        fidelity = review['mappings'][0]['fidelity']
        for ref in fidelity['legacy_source_refs'] + [fidelity['alignment_ref']]:
            path = Path(ref['path']); original = path.read_text()
            path.write_text(original + '\nchanged baseline')
            with self.subTest(path=str(path)), self.assertRaisesRegex(Rejected, 'hash mismatch'):
                self.assign('implementer', 'I1')
            self.assertTrue(self.state()['observed_invalidations'])
            path.write_text(original)

    def test_external_module_is_readable_but_not_automatically_target_dependency(self):
        plan, review, cat, _ = self.selected_plan(external=True)
        reuse.validate_plan(plan, self.state()['modules']['M001'], cat['sources'])
        review['mappings'][0]['integration']['mode'] = 'existing-target'; self.save_review(plan, review)
        with self.assertRaisesRegex(Rejected, 'external source is not'):
            reuse.validate_plan(plan, self.state()['modules']['M001'], cat['sources'])
        review['mappings'][0]['integration']['mode'] = 'reference-only'; self.save_review(plan, review)
        with self.assertRaisesRegex(Rejected, 'reference is guidance'):
            reuse.validate_plan(plan, self.state()['modules']['M001'], cat['sources'])
        review['mappings'][0]['decision'] = 'reference'; self.save_review(plan, review)
        reuse.validate_plan(plan, self.state()['modules']['M001'], cat['sources'])

    def test_provider_evidence_cannot_escape_user_selected_module(self):
        plan, review, cat, _ = self.selected_plan(external=True)
        cat['sources'][1]['module_paths'] = [str(self.base / 'library/other')]
        cat['source_reviews'][1]['scanned_paths'] = cat['sources'][1]['module_paths']
        review['catalog_ref'] = self.ref('narrowed.json', cat); self.save_review(plan, review)
        with self.assertRaisesRegex(Rejected, 'provider evidence outside'):
            reuse.validate_plan(plan, self.state()['modules']['M001'], cat['sources'])

    def test_empty_candidate_set_requires_documented_new_implementation_decision(self):
        plan = self.attach_reuse(self.plan())
        self.freeze(plan)
        self.implementation()  # No fake dependency trace required for a reviewed no-match.
        self.assertEqual(self.state()['modules']['M001']['phase'], 'testing')

    def test_target_provider_owned_by_other_mo_requires_dependency(self):
        plan, _, cat, provider = self.selected_plan()
        module = self.state()['modules']['M001']
        owners = {'M002': {'write_paths': [str(provider.parent)]}}
        with self.assertRaisesRegex(Rejected, 'requires registered dependency'):
            reuse.validate_plan(plan, module, cat['sources'], owners)
        module['dependencies'] = ['M002']
        reuse.validate_plan(plan, module, cat['sources'], owners)

    def test_explicit_external_source_requires_review_even_for_flat_module(self):
        previous = self.state()
        self.root = self.base / 'external-run'
        library = self.base / 'library'; library.mkdir()
        self.call('init', {**{k: previous[k] for k in ('split_testing_required', 'context_readiness_required', 'legacy_root', 'target_root', 'global_spec',
                        'new_architecture', 'case_ids', 'requirement_ids', 'global_paths')},
                  'reuse_sources': [{'source_id': 'LIB', 'root': str(library)}]}, role='host')
        self.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'write_paths': [str(self.target / 'm1')]},
                  role='global-orchestrator', module=None)
        with self.assertRaises(Rejected):
            self.call('plan', {'plan_ref': self.ref('without-reuse.json', self.plan())}, role='spec-designer')
