"""Fault regressions for the approved Lean/SDD evidence and write-scope boundaries."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, baseline, digest, file_ref, read_json
import knowledge_gate
import lean_adapter
import lean_knowledge
import ledger
import migration_report
import resource_fidelity
import test_validation
import test_ledger
import test_lean_native_contracts
import test_lean_worker
import test_ui_frozen_contracts


class EvidenceBoundaryTests(unittest.TestCase):
    def fixture(self, cls):
        f = cls(); f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def strict_flow(self):
        f = self.fixture(test_ledger.FlowTests)
        f.root = f.base / 'strict-run'
        f.call('init', {'dependency_resolution_required': True,
            'dimension_slicing_required': False, 'split_testing_required': False, 'context_readiness_required': False,
            'target_root': str(f.target), 'legacy_root': str(f.legacy), 'case_ids': ['C1'], 'requirement_ids': ['R1'],
            'global_spec': f.ref('global-spec.md', 'R1 spec'), 'new_architecture': f.ref('architecture.md', 'arch'),
            'global_paths': []}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [],
            'write_paths': [str(f.target / 'm1')]}, role='global-orchestrator', module=None)
        f.global_plan()
        return f

    def submit_plan(self, f, plan):
        f.call('plan', {'plan_ref': f.ref('strict-plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'strict-approval')

    def test_missing_or_forged_resolution_never_routes_ready_freeze(self):
        for forged in (None, [], {'schema_version': 1, 'requirements': [
                {'query': 'nonexistent:library', 'resolved_version': '99.99.99'}]}):
            with self.subTest(forged=forged):
                f = self.strict_flow(); plan = f.plan()
                if forged is not None: plan['dependency_resolution_ref'] = f.ref('forged.json', forged)
                self.submit_plan(f, plan)
                step = f.state()['next_steps'][0]
                self.assertNotEqual((step['operation'], step['ready']), ('freeze', True))
                with self.assertRaises(Rejected): f.call('freeze', {'decision_id': 'strict-approval'})
                self.assertFalse(f.state()['decisions']['strict-approval']['consumed'])

    def test_catalog_recomputed_without_trusting_producer_and_stale_ref_stops_dispatch(self):
        f = self.strict_flow(); (f.target / 'harmonyApp').mkdir()
        resolution = lean_knowledge.run('foundation-resolve', {'requirements': ['Ktor client Curl']},
                                        {'target_root': str(f.target)}, f.root)
        resolution.pop('producer')  # Structure/catalog are validated independent of this label.
        ref = f.ref('resolution.json', resolution)
        plan = f.plan(); plan['dependency_resolution_ref'] = ref
        self.submit_plan(f, plan)
        self.assertTrue(f.state()['next_steps'][0]['ready'])
        f.call('freeze', {'decision_id': 'strict-approval'})
        resolution['requirements'][0]['version'] = '99.99.99'
        f.ref('resolution.json', resolution)
        step = f.state()['next_steps'][0]
        self.assertNotEqual((step['operation'], step['ready']), ('assign', True))
        with self.assertRaises(Rejected): f.assign('implementer', 'I1')
        with self.assertRaisesRegex(Rejected, 'differs from its Foundation catalog'):
            knowledge_gate.validate_resolution(file_ref(ref['path']), strict=True)

    def test_change_review_is_consumed_and_cannot_authorize_another_plan(self):
        f = self.fixture(test_ledger.FlowTests); f.prepare()
        before = f.state()['modules']['M001']['freeze_id']
        plan = f.plan(); plan['tasks'][0]['description'] = 'reviewed B'
        review = f.ref('impact.json', {'from_freeze_id': before, 'to_plan_hash': digest(plan), 'summary': 'same envelope'})
        f.call('change', {'request_ref': f.ref('cr.md', 'refine tasks'), 'impact_ref': review})
        f.call('plan', {'plan_ref': f.ref('plan-b.json', plan)}, role='spec-designer')
        f.call('freeze', {'change_class': 'within-envelope', 'impact_ref': review})
        self.assertNotIn('change_request', f.state()['modules']['M001'])
        self.assertEqual(len(f.state()['modules']['M001']['change_request_history']), 1)
        f.call('invalidate', {'reason': 'new scope evidence'})
        plan['tasks'][0]['description'] = 'unreviewed C'
        f.call('plan', {'plan_ref': f.ref('plan-c.json', plan)}, role='spec-designer')
        self.assertFalse(f.state()['next_steps'][0]['ready'])
        with self.assertRaises(Rejected): f.call('freeze', {'change_class': 'within-envelope', 'impact_ref': review})

    def test_current_cr_cannot_freeze_different_plan_or_survive_invalidation(self):
        f = self.fixture(test_ledger.FlowTests); f.prepare()
        original = f.state()['modules']['M001']
        malformed = f.ref('bad-impact.json', [])
        original['change_request'] = {'from_freeze_id': original['freeze_id'], 'impact_ref': malformed}
        with self.assertRaisesRegex(Rejected, 'structured object'):
            ledger.within_envelope(original, malformed)
        plan = f.plan(); plan['tasks'][0]['description'] = 'B'
        review = f.ref('impact.json', {'from_freeze_id': f.state()['modules']['M001']['freeze_id'], 'to_plan_hash': digest(plan)})
        f.call('change', {'request_ref': f.ref('cr.md', 'B only'), 'impact_ref': review})
        plan['tasks'][0]['description'] = 'C'
        f.call('plan', {'plan_ref': f.ref('c.json', plan)}, role='spec-designer')
        self.assertFalse(f.state()['next_steps'][0]['ready'])
        with self.assertRaisesRegex(Rejected, 'to_plan_hash'):
            f.call('freeze', {'change_class': 'within-envelope', 'impact_ref': review})
        f.call('invalidate', {'reason': 'replan'})
        module = f.state()['modules']['M001']
        self.assertNotIn('change_request', module)
        self.assertEqual(module['planning_history'][-1]['change_request']['impact_ref'], review)

    def test_visual_score_must_use_selected_capture_and_semantic_must_bind_score(self):
        f = self.fixture(test_ui_frozen_contracts.FrozenUiContracts)
        alignment, _, _, query = f.alignment_query()
        other = file_ref(f.n.write('unrelated.png', b'unrelated pixels'))
        score = Path(alignment['rounds'][0]['comparisons'][0]['score'])
        semantic = Path(alignment['rounds'][0]['comparisons'][0]['semantic'])
        original = score.read_bytes()
        score.write_text(json.dumps({'reference': other, 'candidate': other}))
        with self.assertRaisesRegex(Rejected, 'differs from selected capture'): f.report(alignment, query)
        score.write_bytes(original)
        semantic.write_text(json.dumps({'status': 'COMPLETE', 'score_sha256': 'a' * 64}))
        with self.assertRaisesRegex(Rejected, 'semantic score hash'): f.report(alignment, query)
        shot = file_ref(f.n.root / 'evidence/screenshot.png')
        semantic.write_text(json.dumps({'status': 'COMPLETE', 'reference': shot, 'candidate': shot}))
        self.assertEqual(f.report(alignment, query)['quality'], 'green-passed')

    def test_auditor_cannot_borrow_sibling_hap_for_selected_path(self):
        f = self.fixture(test_ui_frozen_contracts.FrozenUiContracts)
        alignment, module, path, query = f.alignment_query()
        report = f.report(alignment, query)
        code = file_ref(f.n.write('target/Main.kt', 'code'))
        sibling = copy.deepcopy(module)
        module.update(code_files=[code], freeze_id='freeze1', results={path['path_id']: {'quality': 'yellow-blocked'}}, build_artifacts=[])
        sibling.update(code_files=[file_ref(f.n.write('target/Other.kt', 'other'))], freeze_id='freeze2',
                       results={}, plan={'paths': []})
        scope = ledger.audit_scope({'modules': {'M001': module, 'M002': sibling}, 'global_paths': []})
        report['visual_alignment']['code_baseline'] = scope['code_baseline']
        with self.assertRaisesRegex(Rejected, 'accepted current build'):
            test_validation.visual_result(scope, path, report, report)
        self.assertEqual(scope['path_build_artifacts'][path['path_id']], [])

    def test_carried_alignment_requires_current_regression_images(self):
        f = self.fixture(test_lean_native_contracts.NativeContractTests)
        alignment = f.alignment(); first = alignment['rounds'][0]
        manifest = read_json(first['capture_manifest'])
        candidate = copy.deepcopy(manifest['targets'][1]); candidate['round'] = 2
        new_shot = file_ref(f.write('evidence/round2.png', b'current pixels'))
        candidate['snapshot']['captures'][0]['screenshot'] = new_shot['path']
        candidate['snapshot']['screenshot'] = new_shot['path']
        manifest['targets'].append(candidate)
        f.write('evidence/manifest.json', manifest)
        previous = file_ref(f.root / 'evidence/screenshot.png')
        regression = f.write('target/regression.json', {'reference': previous, 'candidate': previous})
        alignment['rounds'].append({**first, 'round': 2, 'comparisons': [], 'target_results': [
            {'page_id': 'settings', 'state_id': 'base', 'status': 'ALIGNED_CARRIED', 'carried_from_round': 1,
             'regression_score': str(regression)}]})
        with self.assertRaisesRegex(Rejected, 'candidate differs'):
            lean_adapter.comparison_evidence(alignment, f.target, 'settings:base:viewport')
        f.write('target/regression.json', {'reference': previous, 'candidate': new_shot})
        proof = lean_adapter.comparison_evidence(alignment, f.target, 'settings:base:viewport')
        self.assertEqual([p['kind'] for p in proof], ['comparison', 'carried-regression'])

    def test_formal_visual_gate_rederives_comparisons_from_original(self):
        f = self.fixture(test_ui_frozen_contracts.FrozenUiContracts)
        alignment, module, path, query = f.alignment_query()
        report = f.report(alignment, query)
        report['visual_alignment']['comparison_evidence'][0]['candidate_capture_index'] = 9
        with self.assertRaisesRegex(Rejected, 'differs from original evidence'):
            test_validation.visual_result(module, path, report, report)

    def test_global_visual_uses_only_its_explicit_current_integration_build(self):
        f = self.fixture(test_ui_frozen_contracts.FrozenUiContracts)
        alignment, module, path, query = f.alignment_query()
        code = file_ref(f.n.write('target/Main.kt', 'code'))
        module.update(code_files=[code], code_baseline=baseline([code]), freeze_id='f1', stale=False)
        module['plan']['paths'] = [{'path_id': 'BUILD1', 'kind': 'build'}]
        module['results'] = {'BUILD1': {'quality': 'green-passed', 'code_baseline': module['code_baseline'],
                                      'build_artifacts': module['build_artifacts']}}
        global_path = {**path, 'path_id': 'GLOBAL-VISUAL', 'frozen_interaction': query['frozen_interaction'],
                       'visual_evidence': query['frozen_visual_evidence'],
                       'build_binding': {'module_id': 'M001', 'path_id': 'BUILD1'}}
        state = {'modules': {'M001': module}, 'global_paths': [global_path]}
        scope = ledger.audit_scope(state)
        f.n.bind_execution(alignment, scope['code_baseline'])
        report = f.report(alignment, {**query, **global_path, 'code_baseline': scope['code_baseline']})
        test_validation.visual_result(scope, global_path, report, report, run_root=f.visual_run_root,
                                      assignment=f.visual_assignment)
        module['results']['BUILD1']['code_baseline'] = 'older-code'
        with self.assertRaisesRegex(Rejected, 'accepted current build'):
            test_validation.visual_result(ledger.audit_scope(state), global_path, report, report, run_root=f.visual_run_root)


class ResourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.f = test_lean_worker.LeanWorkerTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def test_task_scope_and_frozen_resource_owner_checked_before_write(self):
        f = self.f
        f.module['plan']['tasks'][0]['scope']['write_paths'] = [str(f.scope / 'other')]
        with self.assertRaisesRegex(Rejected, 'task write scope'): f.run_worker(f.resource_request())
        self.assertFalse((f.scope / 'icon.xml').exists())
        f.module['plan']['tasks'][0]['scope']['write_paths'] = [str(f.scope)]
        for args in ({'task_id': 'T2'}, {'resource_item_id': 'R2'}, {'source_id': '@drawable/other'}, {'target_ref': 'Res.other'}):
            with self.subTest(args=args), self.assertRaises(Rejected): f.run_worker(f.resource_request(**args))
            self.assertFalse((f.scope / 'icon.xml').exists())

    def test_factual_kind_unit_ninepatch_and_qualifier_cannot_be_self_reported(self):
        f = self.f
        src = f.write(f.f.legacy / 'res/values-night/strings.xml', '<resources><string name="title">Hello</string></resources>')
        item = {'source_resource': '@string/title', 'source_resource_ref': file_ref(src), 'resource_kind': 'bitmap',
                'resource_strategy': 'byte_copy', 'qualifier': 'night'}
        with self.assertRaisesRegex(Rejected, 'actual source'): resource_fidelity.validate_facts(item)
        item.update(resource_kind='string', resource_strategy='value_xml_exact', qualifier='base')
        with self.assertRaisesRegex(Rejected, 'qualifier'): resource_fidelity.validate_facts(item)
        src = f.write(f.f.legacy / 'res/values/dimens.xml', '<resources><dimen name="pad">12sp</dimen></resources>')
        item.update(source_resource='@dimen/pad', source_resource_ref=file_ref(src), resource_kind='dimen',
                    resource_strategy='design_token_exact', source_unit='dp')
        with self.assertRaisesRegex(Rejected, 'source_unit'): resource_fidelity.validate_facts(item)
        src = f.write(f.f.legacy / 'res/drawable/icon.9.png', 'nine-patch bytes')
        item.update(source_resource='@drawable/icon', source_resource_ref=file_ref(src), resource_kind='bitmap', resource_strategy='byte_copy')
        with self.assertRaisesRegex(Rejected, 'nine_patch'): resource_fidelity.validate_facts(item)

    def test_explicit_missing_source_remains_blocked_and_bad_xml_is_actionable(self):
        result = resource_fidelity.validate_facts({'resource_strategy': 'blocked', 'resource_kind': 'shape',
            'blocked_reason': 'framework source unavailable; requires source review'})
        self.assertEqual(result['status'], 'source-unavailable')
        src = self.f.write(self.f.f.legacy / 'res/drawable/icon.xml', '<broken')
        with self.assertRaisesRegex(Rejected, 'invalid resource XML'):
            resource_fidelity.validate_facts({'source_resource_ref': file_ref(src), 'source_resource': '@drawable/icon',
                                              'resource_kind': 'vector', 'resource_strategy': 'exact_vector_xml'})

    def test_resource_scan_is_read_only_and_discovers_values_and_binary_variants(self):
        f = self.f
        f.write(f.f.legacy / 'res/values/arrays.xml', '<resources><string-array name="names"><item>A</item></string-array></resources>')
        f.write(f.f.legacy / 'res/font/body.ttf', 'font bytes')
        f.write(f.f.legacy / 'res/drawable-night/icon.png', 'night pixels')
        result = f.run_worker(f.request('resource-scan', extra_refs=['@array/names', '@font/body', '@drawable/icon']),
                              {'role': 'spec-designer', 'instance_id': 'spec-1'})
        rows = read_json(result['result_ref']['path'])['resources']
        self.assertTrue(all(r['source_refs'] for r in rows))
        self.assertEqual(len(next(r for r in rows if r['sourceId'] == '@drawable/icon')['source_refs']), 2)
        self.assertFalse(f.scope.exists())

    def test_bounded_byte_copy_and_value_xml_preserve_content_and_reject_overwrite(self):
        f = self.f
        for kind, strategy, source, source_id, target in (
            ('bitmap', 'byte_copy', f.write(f.f.legacy / 'res/drawable/photo.png', 'pixels'), '@drawable/photo', 'photo.png'),
            ('string', 'value_xml_exact', f.write(f.f.legacy / 'res/values/strings.xml',
                '<resources><string name="title">Hello %1$s</string><string name="unrelated">Other</string></resources>'),
             '@string/title', 'values/strings.xml')):
            destination = f.scope / target
            f.resource_item.update(source_resource=source_id, source_resource_ref=file_ref(source), resource_kind=kind,
                                   resource_strategy=strategy, target_resource=str(destination) + '#Res.value')
            request = lambda: f.resource_request(source=str(source.relative_to(f.f.legacy)),
                destination=str(destination.relative_to(f.f.target)), source_id=source_id, target_ref='Res.value')
            f.run_worker(request())
            if strategy == 'byte_copy': self.assertEqual(destination.read_bytes(), source.read_bytes())
            else:
                self.assertIn('Hello %1$s', destination.read_text()); self.assertNotIn('unrelated', destination.read_text())
            f.run_worker(request())  # Identical resource reuse is safe.
            destination.write_text('<resources><string name="title">different</string></resources>' if kind == 'string' else 'different')
            before = destination.read_bytes()
            with self.assertRaises(Rejected): f.run_worker(request())
            self.assertEqual(destination.read_bytes(), before)

    def test_import_byte_copy_is_equal_and_base_night_are_distinct(self):
        f = self.f; mappings = []
        for qualifier in ('', '-night'):
            source = f.write(f.f.legacy / ('res/drawable' + qualifier + '/image.png'), 'same pixels')
            target = f.write(f.f.target / ('resources/drawable' + qualifier + '/image.png'), 'same pixels')
            mappings.append({'sourceId': '@drawable/image', 'sourcePath': str(source.relative_to(f.f.legacy)),
                'targetPath': str(target.relative_to(f.f.target)), 'targetRef': 'Res.drawable.image',
                'consumers': ['Screen'], 'strategy': 'byte_copy'})
        result = {'schemaVersion': 1, 'status': 'READY_FOR_LEAN', 'changeId': 'slice', 'approvedSpecHash': 'a' * 64,
                  'resourceMappings': mappings, 'manualItems': [], 'filesChanged': []}
        ref = file_ref(f.write(f.f.run / 'resource-import.json', json.dumps(result)))
        imported = lean_adapter.resource_summary(ref, target_root=f.f.target, legacy_root=f.f.legacy, approved_spec_hash='a' * 64)
        self.assertEqual(len(imported['resource_mappings']), 2)
        target.write_text('different bytes')
        with self.assertRaisesRegex(Rejected, 'bytes differ'):
            lean_adapter.resource_summary(ref, target_root=f.f.target, legacy_root=f.f.legacy, approved_spec_hash='a' * 64)

    def test_worker_checks_configuration_before_writing_and_uses_frozen_route(self):
        f = self.f
        source = f.write(f.f.legacy / 'res/values-night/strings.xml', '<resources><string name="title">Night</string></resources>')
        destination = f.scope / 'values/strings.xml'
        f.resource_item.update(source_resource='@string/title', source_resource_ref=file_ref(source), resource_kind='string',
            resource_strategy='value_xml_exact', qualifier='night', target_resource=str(destination) + '#Res.string.title')
        request = lambda: f.resource_request(source=str(source.relative_to(f.f.legacy)), source_id='@string/title',
            destination=str(destination.relative_to(f.f.target)), target_ref='Res.string.title')
        with self.assertRaisesRegex(Rejected, 'configuration_mapping'):
            f.run_worker(request())
        self.assertFalse(destination.exists())
        mapping = {'source_qualifier': 'night', 'target_qualifier': 'base',
            'scope': {'configurations': ['night'], 'reason': 'This frozen feature only renders in night configuration'},
            'evidence_refs': [file_ref(f.write(f.f.run / 'night-scope.md', 'Reviewed source/night-only feature scope'))]}
        f.resource_item['configuration_mapping'] = mapping
        produced = f.run_worker(request())
        result = read_json(produced['result_ref']['path'])
        self.assertEqual(result['mapping']['configurationMapping'], mapping)
        self.assertIn('Night', destination.read_text())

    def test_native_unknown_kind_keeps_blocked_result_and_reviewed_manual_proof(self):
        f = self.f
        source = f.write(f.f.legacy / 'res/drawable/motion.xml', '<animated-vector/>')
        target = f.write(f.f.target / 'src/Motion.kt', 'Reviewed exact animator implementation')
        mapping = {'sourceId': '@drawable/motion', 'sourcePath': str(source.relative_to(f.f.legacy)),
            'targetPath': str(target.relative_to(f.f.target)), 'targetRef': 'Motion', 'consumers': ['Screen'],
            'strategy': 'blocked', 'blockedReason': 'Requires animator implementation'}
        result = {'schemaVersion': 1, 'status': 'BLOCKED', 'changeId': 'slice', 'approvedSpecHash': 'a' * 64,
                  'resourceMappings': [mapping], 'manualItems': [], 'filesChanged': []}
        def summary():
            ref = file_ref(f.write(f.f.run / 'unknown-resource.json', json.dumps(result)))
            return lean_adapter.resource_summary(ref, target_root=f.f.target, legacy_root=f.f.legacy, approved_spec_hash='a' * 64)
        self.assertEqual(summary()['status'], 'BLOCKED')
        mapping['strategy'] = 'manual_exact'; result['status'] = 'READY_FOR_LEAN'
        with self.assertRaises(Rejected): summary()
        mapping['adaptationEvidenceRef'] = file_ref(f.write(f.f.run / 'animation-review.md', 'Source animator semantics inspected against target'))
        self.assertIn(mapping['adaptationEvidenceRef'], summary()['linked_refs'])


class FidelityDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def test_completed_green_keeps_source_only_and_fixture_limitations_visible(self):
        f = self.f; f.test_green_flow_and_independent_global_audit()
        state = f.state()
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'UI1', 'semantic_model': {'ui_evidence': {'visual_mode': 'source-only', 'coverage': 'p:s:viewport'}}}]},
            {'dimension': 'Logic', 'status': 'applicable', 'items': [
                {'item_id': 'L1', 'target_strategy': 'capture-fixture', 'case_ids': ['C1']}]}]}
        state['modules']['M001']['plan']['dimension_analysis_ref'] = f.ref('disclosure.json', analysis)
        report = migration_report.build(f.root, state, state['last_sequence'])
        self.assertEqual(report['report_stage'], 'completed')
        self.assertEqual(report['cases'][0]['quality'], 'green-passed')
        self.assertEqual(report['visual_coverage'][0]['status'], 'not-verified')
        self.assertEqual({v['kind'] for v in report['fidelity_limitations']}, {'visual-coverage', 'capture-fixture'})
        markdown = migration_report.render(report)
        self.assertIn('source-only', markdown); self.assertIn('provider', markdown)

    def test_runtime_coverage_uses_current_executed_path_and_archived_resolver(self):
        f = self.f
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'UI1', 'semantic_model': {'ui_evidence': {'visual_mode': 'runtime', 'coverage': 'p:s:viewport'}}}]}]}
        ref = f.ref('analysis.json', analysis)
        archived = f.ref('retained.json', analysis); Path(ref['path']).unlink()
        state = {'modules': {'M001': {'plan': {'dimension_analysis_ref': ref}}}}
        row = {'module_id': 'M001', 'path_id': 'PV', 'kind': 'visual', 'coverage': 'p:s:viewport',
               'quality': 'green-passed', 'executed': True, 'stale': False, 'evidence_refs': []}
        resolver = lambda r: Path(archived['path'])
        self.assertEqual(migration_report.fidelity(state, [row], resolver)[0][0]['status'], 'verified')
        row['stale'] = True
        self.assertEqual(migration_report.fidelity(state, [row], resolver)[0][0]['status'], 'not-verified')
        self.assertEqual(migration_report.fidelity(state, [], lambda r: Path(r['path']))[0][0]['status'], 'unknown')
