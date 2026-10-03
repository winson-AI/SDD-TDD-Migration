"""A visual PATH proven by image checks: capture evidence, the measurement, the adapter report and the formal Green."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, file_ref, read_json
import lean_visual_adapter
import lean_visual_worker
import reference_render
import test_validation
import ui_fidelity
import visual_evidence
from test_image_parity import glyph

RUN = 'image-run'
ASSIGNMENT = {'assignment_id': 'T1', 'fencing_token': 'fence-1'}


class ImageProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.run_root = self.base / '.sdd-runs' / RUN
        self.code = 'code-1'
        data = io.BytesIO()
        glyph('back', 72).save(data, format='WEBP', lossless=True)
        asset = self.write('legacy/app/src/main/res/drawable-xxhdpi/ic_back.webp', data.getvalue())
        self.index = {'androidRoot': str(self.base / 'legacy'), 'resources': [
            {'ref': '@drawable/ic_back', 'kind': 'drawable', 'qualifier': 'xxhdpi', 'path': asset.relative_to(self.base / 'legacy').as_posix(),
             'sha256': file_ref(asset)['sha256']}]}
        references = self.base / 'references'
        references.mkdir()
        reference_render.render(self.index, '@drawable/ic_back', 'xxhdpi', references)
        self.check = {'id': 'back-arrow', 'node_id': 'node:home.back', 'source_resource': '@drawable/ic_back', 'qualifier': 'xxhdpi',
                      'reference': {'render_ref': file_ref(references / 'reference.json')},
                      'target': {'selector': {'resource-id': 'back'}}}
        self.hap = file_ref(self.write('build/app.hap', b'package'))
        self.path = {'path_id': 'V1', 'kind': 'visual', 'case_id': 'C1', 'name': 'icons', 'coverage': 'home:base:viewport',
                     'node_ids': ['node:home.back'], 'image_check_ids': ['back-arrow'],
                     'expected_assertions': [{'assertion_id': 'VISUAL', 'expected': True}]}
        self.module = {'module_id': 'M001', 'code_baseline': self.code, 'build_artifacts': [self.hap],
                       'plan': {'paths': [self.path], 'dimension_analysis_ref': self.analysis([self.check])}}
        self.task = {'role': 'test-runner', 'assignment_id': 'T1', 'fencing_token': 'fence-1', 'test_scope': 'visual'}
        self.attempts = 0

    def write(self, name, value):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(value if isinstance(value, str) else json.dumps(value))
        return path

    def analysis(self, checks, name='analysis.json'):
        return file_ref(self.write(name, {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'UI-1', 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': {'coverage': 'home:base:viewport'},
                                                  'image_checks': checks}}]}]}))

    def screen(self, icon, name, resource_id='back'):
        canvas = Image.new('RGB', (360, 640), (250, 250, 250))
        if icon is not None:
            canvas.paste(icon, (60, 80), icon)
        shot = self.base / 'evidence' / name / 'screenshot-0.jpeg'
        shot.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(shot, quality=85)
        size = icon.width if icon is not None else 72
        view = self.write(f'evidence/{name}/view-0.xml',
                          '<hierarchy><node class="Text" resource-id="title" text="Settings" bounds="[10,10][200,50]"/>'
                          '<node class="Image" resource-id="%s" bounds="[54,74][%d,%d]"/></hierarchy>' % (resource_id, 66 + size, 86 + size))
        return shot, view

    def capture(self, icon, name='first', code=None, assignment=None, round_id=1):
        """One executed candidate capture of the target screen, with the managed receipts a real capture leaves."""
        code, assignment = code or self.code, assignment or ASSIGNMENT
        shot, view = self.screen(icon, name)
        meta = self.write(f'evidence/{name}/meta.json', {'screenshot': shot.name})
        coverage = {'requested': 'viewport', 'achieved': 'viewport', 'capture_count': 1, 'termination': 'viewport'}
        capture = {'index': 0, 'screenshot': str(shot), 'view_tree': str(view), 'view_signature': 'sig'}
        record = {'mode': 'targeted', 'phase': 'harmony-candidate', 'platform': 'harmony', 'page_id': 'home', 'state_id': 'base',
                  'observed_variant': 'base', 'round': round_id, 'status': 'COMPLETE', 'coverage': coverage,
                  'snapshot': {**capture, 'meta': str(meta), 'device_backend': {'name': 'hdc', 'version': '1', 'device': 'device-1'},
                               'coverage': coverage, 'captures': [capture]}}
        manifest_path = self.base / 'evidence' / name / 'manifest.json'
        prefix = f'.sdd-runs/{RUN}/runs/harmony/sandbox/test/{name}'
        observed = visual_evidence.observations(record, manifest_path.parent)
        install_log = file_ref(self.write(prefix + '/install-commands.json', [
            {'argv': ['hdc', '-t', 'device-1', 'install', '-r', self.hap['path']], 'exit_code': 0}]))
        install = file_ref(self.write(prefix + '/install.json', {
            'producer': 'lean-visual-worker', 'operation': 'visual-install', 'status': 'INSTALLED', 'artifact_ref': self.hap,
            'code_baseline': code, 'device_id': 'device-1', 'app_id': 'app', 'assignment_id': assignment['assignment_id'],
            'fencing_token': assignment['fencing_token'], 'command_log_ref': install_log}))
        commands = file_ref(self.write(prefix + '/capture-commands.json', [{
            'argv': ['autotest', 'observe'], 'exit_code': 0, 'operation': 'capture', 'artifact_ref': self.hap,
            'code_baseline': code, 'install_ref': install, 'observations': observed}]))
        record['snapshot']['capture_execution_ref'] = file_ref(self.write(prefix + '/capture-execution.json', {
            'schema_version': 1, 'producer': 'sdd-visual-capture', 'status': 'CAPTURED', 'executed': True,
            'coverage': 'home:base:viewport', 'capture_round': round_id, 'artifact_ref': self.hap, 'code_baseline': code,
            'assignment_id': assignment['assignment_id'], 'fencing_token': assignment['fencing_token'], 'device_id': 'device-1',
            'app_id': 'app', 'install_ref': install, 'observations': observed, 'command_log_ref': commands}))
        return file_ref(self.write(f'evidence/{name}/manifest.json', {'schema_version': 2, 'targets': [record]}))

    def measure(self, manifest, task=None):
        self.attempts += 1
        out = self.run_root / 'runs/harmony/sandbox/tester' / f'parity-{self.attempts}'
        out.mkdir(parents=True)
        result = lean_visual_worker.parity({'path_id': 'V1', 'manifest_ref': manifest, 'round': 1}, out, self.module,
                                           task or self.task, RUN)
        return result, out

    def query(self):
        return {**self.path, 'run_id': RUN, 'module_id': 'M001', 'freeze_id': 'F1', 'code_baseline': self.code,
                'frozen_image_checks': [copy.deepcopy(self.check)], 'run_root': str(self.run_root), 'execution_assignment': ASSIGNMENT}

    def adapt(self, result):
        return lean_visual_adapter.report(self.query(), None, self.base, [], result['report_ref'])

    def accept(self, report, path=None, assignment=None):
        test_validation.visual_result(self.module, path or self.path, report, report, run_root=str(self.run_root),
                                      assignment=assignment or ASSIGNMENT)

    def good(self):
        result, out = self.measure(self.capture(glyph('back', 60, color=(40, 40, 40, 255)), name='good'))
        return result, out, self.adapt(result)

    # ------------------------------------------------------------------ the three outcomes

    def test_a_matching_icon_is_measured_adapted_and_accepted_as_a_green(self):
        result, out, report = self.good()
        self.assertEqual(result['quality_candidate'], 'green-passed')
        self.assertEqual((report['quality'], report['visual_alignment']['mode']), ('green-passed', 'reference-assets'))
        self.assertEqual(report['visual_alignment']['image_parity']['checks'], [{'id': 'back-arrow', 'status': 'MATCH'}])
        self.assertEqual(report['visual_alignment']['hap_ref'], self.hap)
        self.accept(report)
        self.assertTrue((out / 'crops/back-arrow.png').is_file())

    def test_a_wrong_icon_is_red_and_the_cause_names_the_check_and_its_numbers(self):
        result, _ = self.measure(self.capture(glyph('star', 60, color=(40, 40, 40, 255)), name='wrong'))
        self.assertEqual(result['quality_candidate'], 'red-bug')
        report = self.adapt(result)
        self.assertEqual((report['quality'], report['root_cause']['category'], report['root_cause']['owner']), ('red-bug', 'visual-alignment', 'fixer'))
        self.assertIn('back-arrow: MISMATCH (shape_iou=', report['root_cause']['summary'])
        self.assertEqual([a['passed'] for a in report['assertions']], [False])
        self.accept(report)  # only a Green is validated as one; a Red is accepted as the finding it is

    def test_an_icon_the_capture_cannot_show_is_yellow_never_a_pass(self):
        manifest = self.capture(glyph('back', 60), name='gone')
        view = Path(read_json(Path(manifest['path']))['targets'][0]['snapshot']['view_tree'])
        view.write_text(view.read_text().replace('resource-id="back"', 'resource-id="other"'))
        # the view tree changed after its observation was recorded, so the capture evidence is rewritten with it
        manifest = self.capture(None, name='gone2')
        result, _ = self.measure(manifest)
        report = self.adapt(result)
        self.assertEqual((result['quality_candidate'], report['quality'], report['root_cause']['category']),
                         ('yellow-blocked', 'yellow-blocked', 'capture-environment'))

    # ------------------------------------------------------------------ the Ledger does not take the report on trust

    def tamper(self, change, message):
        result, out, report = self.good()
        path = out / 'image-parity.json'
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))
        forged = copy.deepcopy(report)
        forged['visual_alignment']['image_parity']['report_ref'] = file_ref(path)
        with self.assertRaisesRegex(Rejected, message):
            self.accept(forged)

    def test_a_forged_measurement_verdict_or_node_is_recomputed_and_rejected(self):
        self.tamper(lambda d: d['checks'][0]['metrics'].update(shape_iou=0.99), 'differs from its recomputation')
        self.tamper(lambda d: d['checks'][0].update(status='MISMATCH'), 'differs from its recomputation')
        self.tamper(lambda d: d['checks'][0]['node'].update(bounds=[0, 0, 80, 80]), 'differs from its recomputation')

    def test_a_report_for_other_references_selectors_or_tolerance_is_rejected(self):
        other = self.write('references/other.png', b'not the frozen reference')
        self.tamper(lambda d: d['checks'][0].update(reference_ref=file_ref(other)), 'differs from the frozen check')
        self.tamper(lambda d: d['checks'][0].update(selector={'resource-id': 'elsewhere'}), 'differs from the frozen check')
        self.tamper(lambda d: d['checks'][0].update(node_id='node:home.other'), 'differs from the frozen check')
        self.tamper(lambda d: d['checks'].append(copy.deepcopy(d['checks'][0])), 'exactly the frozen image checks')
        self.tamper(lambda d: d['checks'].clear(), 'exactly the frozen image checks')

    def test_a_report_from_another_assignment_baseline_or_path_is_rejected(self):
        self.tamper(lambda d: d.update(assignment_id='T9'), 'assignment_id differs')
        self.tamper(lambda d: d.update(code_baseline='code-0'), 'code_baseline differs')
        self.tamper(lambda d: d.update(path_id='V2'), 'path_id differs')
        self.tamper(lambda d: d.update(producer='someone-else'), 'managed image-parity report required')

    def test_the_crop_must_be_the_node_region_of_the_captured_screenshot(self):
        def swap(data):
            other = self.base / 'swap.png'
            glyph('star', 72).convert('RGB').save(other)
            data['checks'][0]['crop_ref'] = file_ref(other)
        self.tamper(swap, 'crop is not the node region')

    def test_the_measurement_must_come_from_a_capture_of_this_assignment_and_build(self):
        manifest = self.capture(glyph('back', 60, color=(40, 40, 40, 255)), name='earlier', assignment={'assignment_id': 'T0', 'fencing_token': 'fence-0'})
        result, _ = self.measure(manifest)
        with self.assertRaisesRegex(Rejected, 'current test/audit assignment'):
            self.accept(self.adapt(result))
        stale = self.capture(glyph('back', 60, color=(40, 40, 40, 255)), name='stale', code='code-0')
        result, _ = self.measure(stale)
        with self.assertRaisesRegex(Rejected, 'baseline'):
            self.accept(self.adapt(result))

    def test_a_green_for_this_path_must_use_the_hap_of_the_accepted_build(self):
        _, _, report = self.good()
        elsewhere = copy.deepcopy(self.module)
        elsewhere['build_artifacts'] = [file_ref(self.write('build/other.hap', b'another package'))]
        with self.assertRaisesRegex(Rejected, 'accepted current build'):
            test_validation.visual_result(elsewhere, self.path, report, report, run_root=str(self.run_root), assignment=ASSIGNMENT)

    def test_a_proof_that_drops_or_rewrites_the_image_evidence_is_not_the_captured_report(self):
        _, _, report = self.good()
        forged = copy.deepcopy(report)
        forged['visual_alignment'].pop('image_parity')
        with self.assertRaisesRegex(Rejected, 'must carry its image-parity proof'):
            self.accept(forged)
        forged = copy.deepcopy(report)
        forged['visual_alignment']['mode'] = 'baseline'
        with self.assertRaisesRegex(Rejected, 'proven by its image checks'):
            self.accept(forged)
        with self.assertRaisesRegex(Rejected, 'must match the captured report'):
            test_validation.visual_result(self.module, self.path, forged, report, run_root=str(self.run_root), assignment=ASSIGNMENT)

    def test_every_frozen_check_must_match_for_the_path_to_be_green(self):
        second = {**self.check, 'id': 'second', 'node_id': 'node:home.back', 'target': {'selector': {'resource-id': 'absent'}}}
        self.module['plan']['dimension_analysis_ref'] = self.analysis([self.check, second])
        self.path['image_check_ids'] = ['back-arrow', 'second']
        result, _ = self.measure(self.capture(glyph('back', 60, color=(40, 40, 40, 255)), name='two'))
        report = lean_visual_adapter.report({**self.query(), 'frozen_image_checks': [self.check, second]}, None, self.base, [], result['report_ref'])
        self.assertEqual(report['quality'], 'yellow-blocked')
        self.assertIn('second: INCOMPARABLE', report['root_cause']['summary'])
        self.assertNotIn('back-arrow', report['root_cause']['summary'])

    # ------------------------------------------------------------------ texts and nodes are checked from the same capture

    def with_checks(self, *extra):
        checks = [self.check, *extra]
        self.module['plan']['dimension_analysis_ref'] = self.analysis(checks)
        self.path.update(image_check_ids=[c['id'] for c in checks], node_ids=sorted({c['node_id'] for c in checks}))
        result, _ = self.measure(self.capture(glyph('back', 60, color=(40, 40, 40, 255)), name='kinds-%d' % self.attempts))
        query = {**self.query(), 'frozen_image_checks': checks}
        return result, lean_visual_adapter.report(query, None, self.base, [], result['report_ref'])

    def test_a_text_and_a_node_check_ride_the_same_capture_and_are_recomputed_like_a_picture(self):
        title = {'id': 'title-text', 'kind': 'text', 'node_id': 'node:home.title', 'source_resource': '@string/title', 'qualifier': 'default',
                 'expect': {'text': 'Settings'}, 'target': {'selector': {'resource-id': 'title'}}}
        there = {'id': 'title-node', 'kind': 'node', 'node_id': 'node:home.title', 'target': {'selector': {'class': 'Text'}}}
        result, report = self.with_checks(title, there)
        self.assertEqual(report['quality'], 'green-passed')
        self.assertEqual([c['status'] for c in report['visual_alignment']['image_parity']['checks']], ['MATCH'] * 3)
        self.accept(report)
        rows = {row['id']: row for row in read_json(Path(result['report_ref']['path']))['checks']}
        self.assertEqual(rows['title-text']['metrics'], {'text': 'Settings'})
        self.assertNotIn('reference_ref', rows['title-text'])  # a text has no rendered reference and no crop
        forged = Path(result['report_ref']['path'])
        data = json.loads(forged.read_text()); data['checks'][1]['metrics']['text'] = 'Preferences'; forged.write_text(json.dumps(data))
        tampered = copy.deepcopy(report); tampered['visual_alignment']['image_parity']['report_ref'] = file_ref(forged)
        with self.assertRaisesRegex(Rejected, 'differs from its recomputation'):
            self.accept(tampered)

    def test_another_text_or_a_missing_node_is_red_with_what_was_seen(self):
        wrong = {'id': 'title-text', 'kind': 'text', 'node_id': 'node:home.title', 'source_resource': '@string/title', 'qualifier': 'default',
                 'expect': {'text': 'Preferences'}, 'target': {'selector': {'resource-id': 'title'}}}
        _, report = self.with_checks(wrong)
        self.assertEqual((report['quality'], report['root_cause']['owner']), ('red-bug', 'fixer'))
        self.assertIn('title-text: MISMATCH (text=Settings)', report['root_cause']['summary'])
        gone = {'id': 'banner-node', 'kind': 'node', 'node_id': 'node:home.banner', 'target': {'selector': {'resource-id': 'banner'}}}
        _, report = self.with_checks(gone)
        self.assertEqual(report['quality'], 'red-bug')
        self.assertIn('banner-node: MISMATCH (matches=0)', report['root_cause']['summary'])

    # ------------------------------------------------------------------ where the checks come from

    def test_the_path_carries_only_checks_the_frozen_analysis_declares(self):
        self.assertEqual(ui_fidelity.frozen_image_checks(self.module, self.path), [self.check])
        self.assertEqual(ui_fidelity.frozen_image_checks(self.module, {**self.path, 'kind': 'automation'}), [])
        with self.assertRaisesRegex(Rejected, 'undeclared image checks: ghost'):
            ui_fidelity.frozen_image_checks(self.module, {**self.path, 'image_check_ids': ['ghost']})
        audit = {'path_dimension_analysis_refs': {'V1': self.analysis([self.check], 'audit-analysis.json')}, 'plan': {}}
        self.assertEqual(ui_fidelity.frozen_image_checks(audit, self.path), [self.check])

    def test_measuring_needs_the_frozen_checks_and_one_executed_candidate_capture(self):
        manifest = self.capture(glyph('back', 60), name='single')
        out = self.run_root / 'runs/harmony/sandbox/tester/odd'
        out.mkdir(parents=True)
        for args, message in (({'path_id': 'V1', 'manifest_ref': manifest, 'round': 2}, 'one completed candidate capture'),
                              ({'path_id': 'V1', 'manifest_ref': manifest, 'round': 0}, 'positive explicit capture round')):
            with self.subTest(args=args), self.assertRaisesRegex(Rejected, message):
                lean_visual_worker.parity(args, out, self.module, self.task, RUN)
        plain = copy.deepcopy(self.module)
        plain['plan']['paths'][0].pop('image_check_ids')
        with self.assertRaisesRegex(Rejected, 'carries image checks'):
            lean_visual_worker.parity({'path_id': 'V1', 'manifest_ref': manifest, 'round': 1}, out, plain, self.task, RUN)


if __name__ == '__main__':
    unittest.main()
