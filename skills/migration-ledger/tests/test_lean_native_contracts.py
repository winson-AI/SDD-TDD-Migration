"""Native domain-tool contracts.

Fixtures follow test_ui_tree_tools.py, test_select_runtime_ui.py,
test_finalize_alignment.py, test_foundation_gate.py and test_resource_tool.py.
The source/runtime indices are produced by the bundled original collectors; no SDD
shape is substituted for native attachments, capabilities or semantic records.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, file_ref, read_json
import knowledge_gate
import lean_adapter
import ui_evidence
import ui_fidelity
from lean_tools import collect_ui_sources, select_runtime_ui, validate_ui_tree, finalize_alignment, resource_tool


class NativeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.android = self.root / 'android'
        self.target = self.root / 'target'
        self.android.mkdir(); self.target.mkdir()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
        return path

    def capture(self):
        shot = self.write('evidence/screenshot.png', b'png-fixture')
        view = self.write('evidence/view.xml', '<hierarchy><node class="android.widget.TextView" '
                          'resource-id="app:id/title" text="Settings" bounds="[0,0][100,40]" '
                          'enabled="true" /></hierarchy>')
        meta = self.write('evidence/meta.json', {'screenshot': shot.name, 'page_name': 'SettingsActivity',
                          'foreground': 'app/.SettingsActivity', 'view_signature': 'sig'})
        coverage = {'requested': 'viewport', 'achieved': 'viewport', 'capture_count': 1, 'termination': 'viewport'}
        snapshot = {'screenshot': str(shot), 'view_tree': str(view), 'meta': str(meta), 'view_signature': 'sig',
                    'device_backend': {'name': 'autotest', 'version': 'test', 'device': 'device-1'},
                    'coverage': coverage,
                    'captures': [{'index': 0, 'screenshot': str(shot), 'view_tree': str(view), 'view_signature': 'sig'}]}
        record = {'mode': 'targeted', 'phase': 'android-reference', 'platform': 'android',
                  'page_id': 'settings', 'state_id': 'base', 'observed_variant': 'base',
                  'round': None, 'status': 'COMPLETE', 'coverage': coverage, 'snapshot': snapshot}
        manifest = {'schema_version': 2, 'capture_id': 'settings-run', 'targets': [record,
                    {**copy.deepcopy(record), 'phase': 'harmony-candidate', 'platform': 'harmony', 'round': 1}]}
        return manifest, self.write('evidence/manifest.json', manifest)

    def native_ui(self):
        source = 'app/src/main/java/example/SettingsFragment.kt'
        adapter = 'app/src/main/java/example/SettingAdapter.kt'
        self.write(str(self.android / source),
                   'package example\nclass SettingsFragment {\n  fun create() = R.layout.settings\n}\n')
        self.write(str(self.android / adapter),
                   'package example\nclass SettingAdapter : RecyclerView.Adapter<RowHolder>() {\n'
                   '  fun row(parent: ViewGroup) = parent.inflate(R.layout.row_setting)\n}\n')
        main = 'app/src/main/res/layout/settings.xml'
        row = 'app/src/main/res/layout/row_setting.xml'
        self.write(str(self.android / main), '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android" '
                   'android:layout_width="match_parent" android:layout_height="match_parent">'
                   '<TextView android:id="@+id/title" android:layout_width="match_parent" '
                   'android:layout_height="wrap_content" android:text="@string/settings_title" /></LinearLayout>')
        self.write(str(self.android / row), '<TextView xmlns:android="http://schemas.android.com/apk/res/android" '
                   'android:layout_width="match_parent" android:layout_height="wrap_content" '
                   'android:text="@string/settings_title" />')
        self.write(str(self.android / 'app/src/main/res/values/strings.xml'),
                   '<resources><string name="settings_title">Settings</string></resources>')
        source_index = collect_ui_sources.collect(SimpleNamespace(android_root=str(self.android), scope='settings',
                         entry=[source + '#SettingsFragment'], source_file=[adapter], layout=[]))
        index = self.write('evidence/ui-source-index.json', source_index)
        manifest, manifest_path = self.capture()
        runtime = self.write('evidence/runtime-ui-index.json',
                             select_runtime_ui.select(manifest_path, ['settings:base:viewport']))

        def node(nid, source_path, raw):
            children = [node(nid + '.' + str(i), source_path, child)
                        for i, child in enumerate(raw['children'], 1)]
            return {'id': nid, 'name': nid, 'nodeKind': 'container' if children else 'view',
                    'viewClass': raw['tag'], 'analysisStatus': 'expanded' if children else 'leaf',
                    'source': {'path': source_path, 'selector': raw['selector'], 'origin': 'xml', 'line': None},
                    'initialVisibility': 'visible', 'layout': {'kind': 'vertical' if children else 'leaf',
                        'scrollable': False, 'rawAttrs': raw['rawAttrs'], 'resolvedAttrs': {}},
                    'presentation': {'purpose': '', 'appearance': '', 'resourceRefs': raw['resourceRefs']},
                    'bindings': [], 'events': [], 'dynamicRules': [], 'capabilities': {}, 'children': children}

        layouts = {item['path']: item['root'] for item in source_index['layouts']}
        main_root, row_root = node('settings.root', main, layouts[main]), node('settings.row', row, layouts[row])
        main_root['bindings'] = [{'target': 'title.text', 'source': 'state.title', 'sourcePath': source, 'line': 3}]
        main_root['capabilities'] = {'scroll': False}
        main_root['runtimeObservations'] = [{'pageId': 'settings', 'stateId': 'base', 'viewSignature': 'sig'}]
        tree = {'schemaVersion': 1, 'scope': 'settings', 'generatedFrom': {
                    'sourceIndex': index.name, 'sourceIndexSha256': file_ref(index)['sha256'],
                    'runtimeIndex': runtime.name, 'runtimeIndexSha256': file_ref(runtime)['sha256']},
                'screens': [{'id': 'settings', 'name': 'Settings', 'kind': 'fragment', 'root': main_root,
                    'attachments': [{'id': 'settings.row', 'kind': 'list_item',
                                     'anchorNodeId': 'settings.root', 'root': row_root}]}],
                'layoutClosure': [
                    {'path': main, 'role': 'screen', 'nodeIds': ['settings.root', 'settings.root.1'],
                     'status': 'mapped', 'reason': 'root'},
                    {'path': row, 'role': 'list_item', 'nodeIds': ['settings.row'],
                     'status': 'mapped', 'reason': 'adapter row'}],
                'criticalLayoutContracts': [], 'unresolved': []}
        tree_path = self.write('evidence/ui-tree.json', tree)
        return {'tree': tree, 'tree_path': tree_path, 'source': index, 'runtime': runtime,
                'manifest': manifest, 'manifest_path': manifest_path}

    def import_ui(self, fixture):
        return lean_adapter.ui_evidence(fixture['manifest'], file_ref(fixture['tree_path']),
                    target='settings:base:viewport', capture_ref=file_ref(fixture['manifest_path']),
                    source_index_ref=file_ref(fixture['source']),
                    runtime_index_ref=file_ref(fixture['runtime']) if fixture['runtime'] else None)

    def test_native_collect_capture_tree_import_and_v2_visual_freeze(self):
        fixture = self.native_ui()
        self.assertEqual(validate_ui_tree.validate(fixture['tree_path'], fixture['source'], fixture['runtime'])['nodes'], 3)
        evidence = self.import_ui(fixture)
        self.assertTrue(evidence['legacy_executable'])
        self.assertEqual(evidence['coverage'], 'settings:base:viewport')
        self.assertEqual(ui_evidence.node_ids(fixture['tree']), ['node:settings.root', 'node:settings.root.1', 'node:settings.row'])
        self.assertIsInstance(fixture['tree']['screens'][0]['attachments'], list)
        self.assertEqual(fixture['tree']['screens'][0]['root']['bindings'][0]['target'], 'title.text')
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
                    {'item_id': 'UI-settings', 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': evidence}}]}]}
        visual = [{'kind': 'visual', 'coverage': evidence['coverage'], 'node_ids': ['node:settings.root'],
                   'baseline_ref': evidence['baseline_refs'][0]}]
        ui_fidelity.visual_plan_gate(analysis, visual)
        with self.assertRaisesRegex(Rejected, 'nodes do not belong'):
            ui_fidelity.visual_plan_gate(analysis, [{**visual[0], 'node_ids': ['node:settings.row']}])

    def test_native_source_edit_and_xml_omission_are_rejected(self):
        fixture = self.native_ui()
        fixture['tree']['screens'][0]['root']['children'] = []
        fixture['tree']['layoutClosure'][0]['nodeIds'] = ['settings.root']
        self.write('evidence/ui-tree.json', fixture['tree'])
        with self.assertRaisesRegex(Rejected, 'omits XML selectors'):
            self.import_ui(fixture)
        fixture = self.native_ui()
        with (self.android / 'app/src/main/java/example/SettingsFragment.kt').open('a') as source:
            source.write('// changed after collection\n')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.import_ui(fixture)

    def test_native_source_only_preserves_tree_without_claiming_visual_parity(self):
        fixture = self.native_ui()
        fixture['tree']['generatedFrom'].pop('runtimeIndex')
        fixture['tree']['generatedFrom'].pop('runtimeIndexSha256')
        fixture['tree']['screens'][0]['root'].pop('runtimeObservations')
        self.write('evidence/ui-tree.json', fixture['tree'])
        fixture['runtime'] = None
        fixture['manifest']['targets'] = [{**fixture['manifest']['targets'][0],
                                          'status': 'SOURCE_ONLY', 'snapshot': None}]
        self.write('evidence/manifest.json', fixture['manifest'])
        evidence = self.import_ui(fixture)
        self.assertFalse(evidence['legacy_executable'])
        self.assertNotIn('baseline_refs', evidence)
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
                    {'item_id': 'UI-settings', 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': evidence}}]}]}
        ui_fidelity.visual_plan_gate(analysis, [])

    def test_capture_rejects_wrong_visible_variant_and_modified_runtime_file(self):
        fixture = self.native_ui()
        fixture['manifest']['targets'][0]['observed_variant'] = 'other-tab'
        self.write('evidence/manifest.json', fixture['manifest'])
        with self.assertRaisesRegex(Rejected, 'observed_variant'):
            self.import_ui(fixture)
        fixture = self.native_ui()
        self.write('evidence/screenshot.png', b'new screenshot')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            self.import_ui(fixture)

    def alignment(self):
        _, manifest = self.capture()
        hap = self.write('target/build/app.hap', b'hap')
        shot = file_ref(self.root / 'evidence/screenshot.png')
        score = self.write('target/score.json', {'reference': shot, 'candidate': shot})
        semantic = self.write('target/semantic.json', {'status': 'COMPLETE', 'issues': [], 'score_sha256': file_ref(score)['sha256']})
        proof = self.write('target/interaction-trace.json', {})
        result = {'schemaVersion': 2, 'status': 'ALIGNED', 'current_round': 1, 'max_rounds': 3,
                  'required_targets': [{'page_id': 'settings', 'state_id': 'base', 'coverage': 'viewport'}],
                  'required_interactions': [{'id': 'settings-edge-back', 'spec_ref': 'interaction:settings-edge-back',
                      'action': 'edge_back_gesture', 'from': {'page_id': 'settings', 'state_id': 'base'},
                      'expected': {'page_id': 'home', 'state_id': 'base', 'app_foreground': True}}],
                  'interaction_checks': [{'id': 'settings-edge-back', 'action': 'edge_back_gesture', 'round': 1,
                      'hap_sha256': file_ref(hap)['sha256'], 'status': 'PASSED', 'evidence': str(proof),
                      'observed': {'page_id': 'home', 'state_id': 'base', 'app_foreground': True}}],
                  'rounds': [{'round': 1, 'hap': file_ref(hap), 'capture_manifest': str(manifest),
                      'target_results': [{'page_id': 'settings', 'state_id': 'base', 'status': 'ALIGNED'}],
                      'comparisons': [{'page_id': 'settings', 'state_id': 'base', 'score': str(score),
                                       'semantic': str(semantic), 'semantic_region': 'main'}],
                      'verdict': 'ALIGNED', 'files_changed': []}], 'issues': []}
        return result

    def import_alignment(self, result):
        path = self.write('target/alignment-result.json', result)
        return lean_adapter.visual_results(result, ['settings-edge-back'],
                    target_root=self.target, result_ref=file_ref(path))

    def bind_execution(self, result, code_baseline='current-code', run_root=None, assignment=None):
        """Managed external-runner sidecar; the native fixture remains legacy-compatible."""
        import visual_evidence
        assignment = assignment or {'assignment_id': 'capture-assignment', 'fencing_token': 'capture-fence'}
        run_root = Path(run_root) if run_root is not None else self.root / '.sdd-runs/visual-test'
        coverage = result['required_targets'][0]
        coverage = ':'.join(coverage[k] for k in ('page_id', 'state_id', 'coverage'))
        first_manifest = result['rounds'][0]['capture_manifest']
        source = ui_evidence.capture_target(file_ref(first_manifest), coverage)
        frozen = {'visual_mode': 'runtime', 'coverage': coverage, 'capture_manifest_ref': file_ref(first_manifest),
                  'baseline_refs': [file_ref(c['screenshot']) for c in source['snapshot']['captures']]}
        for row in result['rounds']:
            round_code = code_baseline[row['round']] if isinstance(code_baseline, dict) else code_baseline
            round_assignment = assignment if 'assignment_id' in assignment else assignment[row['round']]
            prefix = str(run_root / 'runs/harmony/sandbox/test' / f'round-{row["round"]}')
            manifest = read_json(row['capture_manifest'])
            candidate = next(r for r in manifest['targets'] if r.get('platform') == 'harmony'
                             and r.get('round') == row.get('capture_round', row['round']))
            install_log = file_ref(self.write(prefix + '/install-commands.json', [
                {'argv': ['hdc', '-t', 'device-1', 'install', '-r', row['hap']['path']], 'exit_code': 0}]))
            install = file_ref(self.write(prefix + '/install.json', {
                'producer': 'lean-visual-worker', 'operation': 'visual-install', 'status': 'INSTALLED',
                'artifact_ref': row['hap'], 'code_baseline': round_code, 'device_id': 'device-1',
                'app_id': 'app', 'assignment_id': round_assignment['assignment_id'], 'fencing_token': round_assignment.get('fencing_token'),
                'command_log_ref': install_log}))
            observed = visual_evidence.observations(candidate, Path(row['capture_manifest']).parent)
            commands = file_ref(self.write(prefix + '/capture-commands.json', [{
                'argv': ['autotest', 'observe'], 'exit_code': 0, 'operation': 'capture',
                'artifact_ref': row['hap'], 'code_baseline': round_code, 'install_ref': install,
                'observations': observed}]))
            receipt = file_ref(self.write(prefix + '/capture-execution.json', {
                'schema_version': 1, 'producer': 'sdd-visual-capture', 'status': 'CAPTURED', 'executed': True,
                'coverage': coverage, 'capture_round': row.get('capture_round', row['round']),
                'artifact_ref': row['hap'], 'code_baseline': round_code, 'assignment_id': round_assignment['assignment_id'],
                'fencing_token': round_assignment.get('fencing_token'), 'device_id': 'device-1', 'app_id': 'app',
                'install_ref': install, 'observations': observed, 'command_log_ref': commands}))
            candidate['snapshot']['capture_execution_ref'] = receipt
            row['capture_manifest'] = str(self.write(prefix + '/manifest.json', manifest))
        return str(run_root), frozen

    def test_native_alignment_preserves_current_hap_and_declared_gesture(self):
        result = self.alignment()
        finalize_alignment.validate(self.target, result)
        row = self.import_alignment(result)['settings:base:viewport']
        self.assertEqual(row['quality'], 'green-passed')
        self.assertEqual(row['hap_ref'], result['rounds'][0]['hap'])
        self.assertTrue(row['interaction_checks'][0]['evidence_ref']['sha256'])
        result['interaction_checks'][0]['hap_sha256'] = 'a' * 64
        with self.assertRaisesRegex(Rejected, 'HAP|hap'):
            self.import_alignment(result)

    def test_failed_native_interaction_stays_red(self):
        result = self.alignment()
        result['status'] = 'NEEDS_IMPLEMENTATION_FIX'
        result['interaction_checks'][0].update(status='FAILED', observed={
            'page_id': 'desktop', 'state_id': 'unknown', 'app_foreground': False})
        result['issues'] = [{'category': 'platform-interaction-not-consumed', 'message': 'Edge back exited the app',
                             'evidence': result['interaction_checks'][0]['evidence'], 'owner': 'lean'}]
        self.assertEqual(self.import_alignment(result)['settings:base:viewport']['quality'], 'red-bug')

    def test_native_foundation_version_and_explicit_not_required_results(self):
        # Exact document fields emitted by the upstream foundation_gate.resolve, including
        # native `version` (not the former SDD-only `resolved_version`).
        result = {'schema_version': 1, 'target_root': str(self.target),
                  'target_matrix': {'harmony': True, 'required_target': 'ohosArm64'}, 'status': 'passed',
                  'requirements': [{'query': 'io.ktor:ktor-client-core', 'coordinate': 'io.ktor:ktor-client-core',
                      'version': '3.3.3-0.3.0', 'gav': 'io.ktor:ktor-client-core:3.3.3-0.3.0',
                      'target_support': {'ohosArm64': True}, 'status': 'available', 'cookbook': 'cookbook/ktor-client.md'}]}
        ref = file_ref(self.write('foundation.json', result))
        self.assertEqual(knowledge_gate.validate_resolution(ref)['requirements'][0]['version'], '3.3.3-0.3.0')
        for harmony, status in ((True, 'not_required_no_new_dependencies'), (False, 'not_required_non_harmony_target')):
            result.update(requirements=[], status=status, target_matrix={'harmony': harmony})
            knowledge_gate.validate_resolution(file_ref(self.write('foundation.json', result)))
        result['status'] = 'passed'
        with self.assertRaisesRegex(Rejected, 'explicit not-required'):
            knowledge_gate.validate_resolution(file_ref(self.write('foundation.json', result)))

    def test_native_vector_and_resource_result_keep_exact_strategy(self):
        source = self.write('android/app/src/main/res/drawable/ic_tv.xml',
            '<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" '
            'android:height="24dp" android:viewportWidth="24" android:viewportHeight="24" '
            'android:tint="@color/icon_tint" android:tintMode="src_in">'
            '<path android:fillColor="#FFFFFFFF" android:pathData="M1,2 L3,4" /></vector>')
        destination = 'composeApp/src/commonMain/composeResources/drawable/ic_tv.xml'
        prepared = resource_tool.prepare_vector(SimpleNamespace(android_root=str(self.android), target_root=str(self.target),
                    source=str(source), destination=destination, source_id='@drawable/ic_tv', target_ref='Res.drawable.ic_tv',
                    consumer=['HomeScreen.HomeTabRow'], consumer_tint=None, resolve_ref=['@color/icon_tint=#FF112233']))
        self.assertFalse((self.target / destination).exists())  # Imported pure helper does not write target code.
        self.assertIn('pathData="M1,2 L3,4"', prepared['content'])
        self.assertEqual(prepared['mapping']['consumerTint'], '#FF112233')
        self.write('target/' + destination, prepared['content'])
        result = {'schemaVersion': 1, 'status': 'READY_FOR_LEAN', 'changeId': 'settings', 'approvedSpecHash': 'a' * 64,
                  'resourceMappings': [prepared['mapping']], 'manualItems': [], 'filesChanged': [destination]}
        path = self.write('target/resource-result.json', result)
        mapped = lean_adapter.resource_summary(file_ref(path), target_root=self.target,
                                               legacy_root=self.android, approved_spec_hash='a' * 64)
        self.assertEqual(mapped['resource_mappings'][0]['strategy'], 'exact_vector_xml')
        result['resourceMappings'][0]['strategy'] = 'byte_copy'
        with self.assertRaisesRegex(Rejected, 'unchanged ordinary raster file'):
            lean_adapter.resource_summary(file_ref(self.write('target/resource-result.json', result)),
                        target_root=self.target, legacy_root=self.android, approved_spec_hash='a' * 64)


if __name__ == '__main__':
    unittest.main()
