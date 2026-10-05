"""Managed domain-tool entry boundaries plus a real execute_test -> visual-adapter receipt."""
import copy
from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, baseline, check_ref, file_ref, read_json, validate_result
import execute_test
import lean_worker
import ledger
import project_context
import test_completion
import test_project_context
import test_dimensions
import test_lean_native_contracts as native_fixtures


class LeanWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.prepared = self.f.prepare()
        self.f.start(self.f.init_payload(self.prepared))
        self.state, self.events = ledger.read_events(self.f.run)
        self.sequence = 0
        self.actor = {'role': 'implementer', 'instance_id': 'worker-1'}
        self.scope = self.f.target / 'resources'
        self.task = {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'worker-1',
                     'fencing_token': 'token-1', 'freeze_id': 'freeze-1', 'closed': False,
                     'execution_contract': {'task_ids': ['T1'], 'path_ids': []}}
        # Only execution assignments are isolated; prepare, immutable snapshot checking,
        # collector/converter, path guards and staged receipts use their real implementations.
        self.module = {'module_id': 'M001', 'phase': 'implementing', 'freeze_id': 'freeze-1',
                       'write_paths': [str(self.scope)], 'plan': {'definitions': [], 'paths': []},
                       'assignments': {'I1': self.task}}
        self.state['modules'] = {'M001': self.module}
        self.source = self.write(self.f.legacy / 'app/src/main/res/drawable/icon.xml',
            '<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" '
            'android:height="24dp" android:viewportWidth="24" android:viewportHeight="24">'
            '<path android:fillColor="#FFFFFFFF" android:pathData="M0,0 L1,1" /></vector>')
        self.resource_item = {'item_id': 'R1', 'source_resource': '@drawable/icon',
            'source_resource_ref': file_ref(self.source), 'resource_kind': 'vector', 'resource_strategy': 'exact_vector_xml',
            'target_resource': str(self.scope / 'icon.xml') + '#Res.drawable.icon', 'consumer': 'Home.Icon'}
        self.module['plan'].update(tasks=[{'task_id': 'T1', 'scope': {'write_paths': [str(self.scope)]}}],
                                   dimension_trace=[{'item_id': 'R1', 'task_ids': ['T1']}])

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def request(self, operation='resource-convert', **args):
        self.sequence += 1
        return {'request_id': 'request-' + str(self.sequence), 'operation': operation,
                'module_id': 'M001', 'assignment_id': 'I1', 'fencing_token': 'token-1', 'args': args}

    def resource_request(self, **overrides):
        args = {'source': str(self.source.relative_to(self.f.legacy)), 'destination': 'resources/icon.xml',
                'task_id': 'T1', 'resource_item_id': 'R1',
                'source_id': '@drawable/icon', 'target_ref': 'Res.drawable.icon', 'consumer': ['Home.Icon']}
        args.update(overrides)
        return self.request(**args)

    def run_worker(self, request, actor=None):
        # Resource fixture supplies only the execution boundary; normal plan checks have their
        # own Ledger integration tests. The frozen resource document is checked by the real worker.
        if request['operation'] == 'resource-convert':
            import json
            resource = self.write(self.f.run / 'resource-plan.json', json.dumps({'dimensions': [
                {'dimension': 'Resource', 'items': [self.resource_item]}]}))
            self.module['plan']['dimension_analysis_ref'] = file_ref(resource)
        with patch.object(lean_worker.ledger, 'read_events', return_value=(self.state, self.events)), \
                (patch.object(lean_worker, 'verify_plan', return_value=None) if request['operation'] == 'resource-convert' else nullcontext()):
            return lean_worker.run(self.f.run, request, actor or self.actor)

    def layout(self, root=None):
        return self.write((root or self.f.legacy) / 'app/src/main/res/layout/settings.xml',
            '<TextView xmlns:android="http://schemas.android.com/apk/res/android" '
            'android:layout_width="match_parent" android:layout_height="wrap_content" android:text="Settings" />')

    def analyze_request(self):
        return self.request('analyze-ui', scope='settings', layouts=['settings'])

    def test_managed_path_and_role_capability_are_required(self):
        with self.assertRaisesRegex(Rejected, 'managed .sdd-runs'):
            lean_worker.run(self.f.base / 'unmanaged', self.resource_request(), self.actor)
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.run_worker(self.analyze_request())

    def test_resource_cannot_write_outside_module_scope(self):
        with self.assertRaisesRegex(Rejected, 'outside assigned write scope'):
            self.run_worker(self.resource_request(destination='other/icon.xml'))
        self.assertFalse((self.f.target / 'other/icon.xml').exists())
        with self.assertRaises(Rejected):
            self.run_worker(self.resource_request(destination='../escape.xml'))
        self.assertFalse((self.f.base / 'escape.xml').exists())

    def test_resource_execution_requires_active_owned_fenced_assignment(self):
        request = self.resource_request(); request['assignment_id'] = 'missing'
        with self.assertRaisesRegex(Rejected, 'active assignment'):
            self.run_worker(request)
        self.task['closed'] = True
        with self.assertRaisesRegex(Rejected, 'active assignment'):
            self.run_worker(self.resource_request())
        self.task['closed'] = False
        self.task['instance_id'] = 'another-worker'
        with self.assertRaisesRegex(Rejected, 'owner mismatch'):
            self.run_worker(self.resource_request())
        self.task['instance_id'] = self.actor['instance_id']
        request = self.resource_request(); request['fencing_token'] = 'old-token'
        with self.assertRaisesRegex(Rejected, 'stale fencing token'):
            self.run_worker(request)
        self.assertFalse((self.scope / 'icon.xml').exists())

    def test_resource_consumers_must_be_nonempty_string_list(self):
        for consumers in ([], '', 'Home.Icon', [None], [''], ['   ']):
            with self.subTest(consumers=consumers), self.assertRaisesRegex(Rejected, 'consumer'):
                self.run_worker(self.resource_request(consumer=consumers))
            self.assertFalse((self.scope / 'icon.xml').exists())

    def test_resource_conversion_writes_only_authorized_target_and_staged_evidence(self):
        output = self.run_worker(self.resource_request())
        result = read_json(check_ref(output['result_ref']))
        receipt = read_json(check_ref(output['receipt_ref']))
        self.assertEqual(result['mapping']['consumers'], ['Home.Icon'])
        self.assertEqual(result['mapping']['strategy'], 'exact_vector_xml')
        self.assertEqual(check_ref(result['target_ref']), self.scope / 'icon.xml')
        self.assertEqual(receipt['status'], 'produced')
        self.assertTrue(check_ref(output['receipt_ref']).is_relative_to(self.f.run / 'staging/worker-1'))
        self.assertEqual(len(ledger.read_events(self.f.run)[1]), len(self.events))

    def test_source_only_analyze_runs_real_collector_and_preserves_previous_attempt(self):
        self.layout()
        actor = {'role': 'spec-designer', 'instance_id': 'spec-1'}
        request = self.analyze_request()
        output = self.run_worker(request, actor)
        result = read_json(check_ref(output['result_ref']))
        index = read_json(check_ref(result['source_index_ref']))
        self.assertEqual(index['androidRoot'], str(self.f.legacy))
        self.assertEqual([row['name'] for row in index['layouts']], ['settings'])
        self.assertEqual(index['unresolved'], [])
        self.assertNotIn('runtime_index_ref', result)
        receipt_bytes = check_ref(output['receipt_ref']).read_bytes()
        with self.assertRaisesRegex(Rejected, 'new attempt; preserve prior evidence'):
            self.run_worker(request, actor)
        self.assertEqual(check_ref(output['receipt_ref']).read_bytes(), receipt_bytes)
        self.assertFalse((self.scope / 'icon.xml').exists())

    def test_analyze_ui_takes_manifests_and_project_image_loaders(self):
        self.layout()
        self.write(self.f.legacy / 'app/src/main/AndroidManifest.xml',
                   '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:icon="@drawable/icon"/></manifest>')
        self.write(self.f.legacy / 'app/src/main/java/demo/Feed.kt', 'class Feed { fun show(item: Item) { avatar.setPhoto(item.photoUrl) } }\n')
        output = self.run_worker(self.request('analyze-ui', scope='feed', entry=['Feed.kt'], layouts=['settings'],
                                              manifests=['app/src/main/AndroidManifest.xml'], image_sinks=['setPhoto']),
                                 {'role': 'spec-designer', 'instance_id': 'spec-1'})
        index = read_json(check_ref(read_json(check_ref(output['result_ref']))['source_index_ref']))
        self.assertEqual([(d['kind'], d['resourceRefs']) for d in index['xmlResources']],
                         [('manifest', ['@drawable/icon'])])
        self.assertEqual([(r['loader']['library'], r['source']['value']) for r in index['imageSources']], [('custom', 'item.photoUrl')])

    def test_a_spec_designer_renders_the_reference_of_an_indexed_asset(self):
        import io
        from PIL import Image
        data = io.BytesIO()
        Image.new('RGBA', (72, 72), (0, 0, 0, 255)).save(data, format='PNG')
        asset = self.f.legacy / 'app/src/main/res/drawable-xxhdpi/ic_logo.png'
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(data.getvalue())
        self.write(self.f.legacy / 'app/src/main/res/layout/settings.xml',
                   '<ImageView xmlns:android="http://schemas.android.com/apk/res/android" android:src="@drawable/ic_logo"/>')
        spec = {'role': 'spec-designer', 'instance_id': 'spec-1'}
        analyzed = self.run_worker(self.analyze_request(), spec)
        index_ref = read_json(check_ref(analyzed['result_ref']))['source_index_ref']
        output = self.run_worker(self.request('render-reference', source_index_ref=index_ref, source_resource='@drawable/ic_logo',
                                              qualifier='xxhdpi'), spec)
        result = read_json(check_ref(output['result_ref']))
        document = read_json(check_ref(result['reference_ref']))
        self.assertEqual((document['producer'], document['mode'], (document['width'], document['height'])), ('sdd-reference-render', 'color', (72, 72)))
        self.assertEqual(result['png_ref'], document['png_ref'])
        self.assertEqual(check_ref(result['png_ref']).parent.parent.parent.name, 'staging')
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.run_worker(self.request('render-reference', source_index_ref=index_ref, source_resource='@drawable/ic_logo'), self.actor)
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.run_worker(self.request('image-parity', path_id='V1'), spec)

    def test_current_ledger_context_takes_precedence_over_initial_snapshot(self):
        newer_legacy = self.f.base / 'newer-legacy'; newer_legacy.mkdir()
        self.layout(newer_legacy)  # The initial legacy folder has no settings layout.
        snapshot = copy.deepcopy(project_context.verify_snapshot(self.state['project_context_ref']))
        snapshot['effective_config']['legacy_root'] = str(newer_legacy)
        # Use the same immutable revision writer as source_changes, keeping the initial
        # snapshot intact. read_events supplies the already accepted revision in this test.
        encoded = project_context.encoded(snapshot)
        project_context.archive(self.f.run / 'context/files', encoded, '.snapshot')
        current_ref = project_context.archive(self.f.run / 'context/revisions', encoded, '.json')
        self.state['project_context_ref'] = current_ref
        output = self.run_worker(self.analyze_request(), {'role': 'spec-designer', 'instance_id': 'spec-1'})
        result = read_json(check_ref(output['result_ref']))
        index = read_json(check_ref(result['source_index_ref']))
        self.assertEqual(index['androidRoot'], str(newer_legacy))
        self.assertEqual(index['unresolved'], [])
        self.assertEqual(read_json(self.f.run / 'context/snapshot.json')['effective_config']['legacy_root'], str(self.f.legacy))

    def test_compare_only_scores_real_pngs_without_acceptance_or_ledger_changes(self):
        from PIL import Image
        images = [self.f.base / name for name in ('reference.png', 'candidate.png')]
        for path in images:
            Image.new('RGB', (64, 32), '#346789').save(path)
        code = file_ref(self.write(self.f.target / 'Main.kt', 'fun main() = Unit\n'))
        selection = file_ref(self.write(self.f.base / 'build-selection.md', 'Accepted fixture command'))
        current = baseline([code])
        self.actor['role'] = 'test-runner'
        self.task.update(role='test-runner', test_scope='visual')
        self.module.update(phase='testing', code_files=[code], code_baseline=current, build_baseline=current,
            plan={'definitions': [], 'paths': [{'path_id': 'PB', 'kind': 'build',
                  'command': {'selection_ref': selection}}, {'path_id': 'PA', 'kind': 'automation'}]},
            results={p: {'quality': 'green-passed', 'code_baseline': current} for p in ('PB', 'PA')})
        before = copy.deepcopy(self.state)
        journal = (self.f.run / 'ledger/events.jsonl').read_bytes()
        output = self.run_worker(self.request('compare-only', reference_ref=file_ref(images[0]),
                                              candidate_ref=file_ref(images[1])))
        result = read_json(check_ref(output['result_ref']))
        score = read_json(check_ref(result['score_ref']))
        self.assertEqual(result['status'], 'scored')
        self.assertEqual(result['acceptance'], 'score-is-evidence-not-a-visual-verdict')
        self.assertNotIn('quality', result)
        self.assertEqual(score['status'], 'COMPLETE')
        self.assertEqual(score['metrics']['final_baseline_score'], 100.0)
        attempt = check_ref(output['receipt_ref']).parent
        self.assertTrue(attempt.is_relative_to(self.f.run / 'runs/harmony/sandbox/worker-1'))
        for path in score['artifacts'].values():
            self.assertTrue(Path(path).is_file())
            self.assertTrue(Path(path).is_relative_to(attempt))
        self.assertEqual(read_json(attempt / 'cleanup.json')['status'], 'removed')
        self.assertFalse((attempt / 'temp').exists())
        self.assertEqual(self.state, before)
        self.assertEqual((self.f.run / 'ledger/events.jsonl').read_bytes(), journal)

    def test_execute_visual_adapter_produces_acceptable_formal_receipt(self):
        native = native_fixtures.NativeContractTests()
        native.root, native.android, native.target = self.f.base, self.f.legacy, self.f.target
        ui = native.import_ui(native.native_ui())
        alignment = native.alignment()
        code = self.write(self.f.target / 'Main.kt', 'fun main() = Unit\n')
        code_files = [file_ref(code)]
        code_baseline = baseline(code_files)
        _, frozen_visual = native.bind_execution(alignment, code_baseline, run_root=self.f.run,
                                                assignment={'assignment_id': 'V1'})
        frozen_visual = {**ui, **frozen_visual}
        alignment_path = native.write('target/alignment-result.json', alignment)
        selection = file_ref(self.write(self.f.base / 'build-selection.md', 'Accepted fixture build command'))
        dimensions = test_dimensions.DimensionTests()
        dimensions.f = SimpleNamespace(target=self.f.target, ref=lambda name, value: file_ref(native.write(name, value)))
        analysis = dimensions.analysis('M001', kinds=('UI', 'Resource'))
        next(row for row in analysis['dimensions'] if row['dimension'] == 'Resource')['items'][0].update(
            source_resource='@string/settings_title', resource_kind='string', resource_strategy='value_xml_exact',
            source_resource_ref=file_ref(self.f.legacy / 'app/src/main/res/values/strings.xml'))
        analysis['dimensions'][0]['items'][0]['semantic_model'] = {
            'kind': 'ui-component-spec', 'model_ref': file_ref(native.write('ui-model.json', {'root': {'type': 'Column'}})),
            'source': {'origin': 'authored'}, 'implementation_location': {'target_path': str(code)},
            'ui_evidence': frozen_visual,
            'interactions': copy.deepcopy(alignment['required_interactions'])}
        dimension_ref = file_ref(native.write('frozen-ui.json', analysis))
        visual = {'path_id': 'PV', 'kind': 'visual', 'coverage': 'settings:base:viewport',
                  'node_ids': ['node:settings.root'], 'interaction_id': 'settings-edge-back',
                  'baseline_ref': file_ref(self.f.base / 'evidence/screenshot.png'),
                  'expected_assertions': [{'assertion_id': 'VISUAL', 'expected': True}]}
        task = {'assignment_id': 'V1', 'run_id': 'r1', 'module_id': 'M001', 'role': 'test-runner',
                'instance_id': 'runner-1', 'closed': False, 'test_scope': 'visual',
                'freeze_id': 'freeze-1', 'code_baseline': code_baseline}
        module = {'module_id': 'M001', 'freeze_id': 'freeze-1',
                  'phase': 'testing', 'stale': False, 'assignments': {'V1': task},
                  'code_files': code_files, 'code_baseline': code_baseline, 'build_baseline': code_baseline,
                  'build_artifacts': [alignment['rounds'][0]['hap']],
                  'plan': {'module_id': 'M001', 'dimension_analysis_ref': dimension_ref,
                           'definitions': [], 'tasks': [], 'paths': [{'path_id': 'PB', 'kind': 'build',
                            'command': {'selection_ref': selection}},
                            {'path_id': 'PA', 'kind': 'automation'}, visual]},
                  'results': {p: {'quality': 'green-passed', 'code_baseline': code_baseline} for p in ('PB', 'PA')}}
        from contracts import digest
        module['plan_hash'] = digest(module['plan'])
        module['plan_ref'] = file_ref(native.write('visual-execution-plan.json', module['plan']))
        task['execution_contract'] = {'plan_hash': module['plan_hash'], 'plan_ref': module['plan_ref'],
            'task_ids': [], 'path_ids': ['PV']}
        state = {**self.state, 'context_readiness_required': False, 'modules': {'M001': module}}
        adapter = Path(lean_worker.__file__).with_name('lean_visual_adapter.py')
        argv = [sys.executable, '-B', str(adapter), '--alignment', str(alignment_path),
                '--target-root', str(self.f.target), '--interaction', 'settings-edge-back']
        with patch.object(execute_test, 'status', return_value=state):
            receipt_ref = execute_test.execute(self.f.run, 'M001', 'V1', 'PV', argv, str(self.f.target),
                                               self.f.run / 'runs/harmony/automation/native-visual')
        receipt = read_json(check_ref(receipt_ref))
        self.assertEqual(receipt['exit_code'], 0)
        self.assertEqual(receipt['producer'], 'host-executor')
        captured = read_json(check_ref(receipt['result_ref']))
        self.assertEqual(captured['producer'], 'lean-visual-adapter')
        self.assertEqual(read_json(check_ref(receipt['query_ref']))['frozen_interaction'], alignment['required_interactions'][0])
        record = {**test_completion.interpret(receipt, visual), 'path_id': 'PV',
                  'test_run_id': receipt['test_run_id'], 'execution_receipt': receipt_ref}
        result = {'schema_version': 1, 'kind': 'tests', 'run_id': 'r1', 'module_id': 'M001',
                  'assignment_id': 'V1', 'actor_instance_id': 'runner-1', 'freeze_id': 'freeze-1',
                  'code_baseline': code_baseline, 'paths': [record]}
        self.assertEqual(validate_result(result, module, task, run_root=self.f.run), 'tests')
        # The approved ID cannot be retained while replacing its action and outcome.
        changed = copy.deepcopy(alignment)
        changed['required_interactions'][0].update(action='tap_exit_button', expected={'app_foreground': False})
        changed['interaction_checks'][0].update(action='tap_exit_button', observed={'app_foreground': False})
        native.write('target/alignment-result.json', changed)
        with patch.object(execute_test, 'status', return_value=state):
            wrong_action_ref = execute_test.execute(self.f.run, 'M001', 'V1', 'PV', argv, str(self.f.target),
                                                   self.f.run / 'runs/harmony/automation/wrong-action')
        wrong_action = read_json(check_ref(wrong_action_ref))
        self.assertEqual(wrong_action['exit_code'], 2)
        self.assertIsNone(wrong_action['result_ref'])
        self.assertIn('requirement differs from frozen', check_ref(wrong_action['log_ref']).read_text())
        native.write('target/alignment-result.json', alignment)
        # A valid but unrelated baseline must not be relabelled as the native reference.
        visual['baseline_ref'] = file_ref(self.write(self.f.base / 'other-baseline.png', 'other image'))
        with patch.object(execute_test, 'status', return_value=state):
            rejected_ref = execute_test.execute(self.f.run, 'M001', 'V1', 'PV', argv, str(self.f.target),
                                                self.f.run / 'runs/harmony/automation/wrong-baseline')
        rejected = read_json(check_ref(rejected_ref))
        self.assertEqual(rejected['exit_code'], 2)
        self.assertIsNone(rejected['result_ref'])
        self.assertIn('frozen baseline screenshot', check_ref(rejected['log_ref']).read_text())
        self.assertNotEqual(test_completion.interpret(rejected, visual)['quality'], 'green-passed')
        visual['baseline_ref'] = file_ref(self.f.base / 'evidence/screenshot.png')
        module['build_artifacts'] = []
        with self.assertRaisesRegex(Rejected, 'accepted current build'):
            validate_result(result, module, task, run_root=self.f.run)


if __name__ == '__main__':
    unittest.main()
