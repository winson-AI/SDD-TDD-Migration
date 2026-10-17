"""The run states how the legacy application runs; executability is that fact; a running legacy screen left uncaptured says why."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import automation_report
import ledger
import migration_report
import project_context as pc
import ui_fidelity
import test_project_context
from contracts import Rejected, check_ref, file_ref

EMULATOR = {'kind': 'android-emulator', 'app_id': 'com.example.legacy', 'device': {'serial': 'emulator-5554', 'avd': 'Pixel_6'}}


class StatementTests(unittest.TestCase):
    def test_a_project_states_how_the_legacy_runs_or_why_it_cannot(self):
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp).resolve() / 'legacy.apk'; apk.write_bytes(b'apk')
            build = {'argv': [sys.executable, '-c', 'pass'], 'cwd': str(Path(tmp).resolve()), 'timeout_seconds': 60, 'output': str(apk)}
            for value in ({'kind': 'none', 'reason': 'the legacy needs a hardware token'}, {'kind': 'browser', 'url': 'https://legacy.example.test/'},
                          {**EMULATOR, 'artifact': str(apk)}, {**EMULATOR, 'kind': 'vm', 'device': {'serial': '10.0.2.15:5555'}, 'build': build, 'launch': '.Main'}):
                self.assertEqual(pc.validate({'legacy_preview': value})['legacy_preview']['kind'], value['kind'])
            for bad, message in (({'kind': 'ios-simulator'}, 'kind is one of'), ({'kind': 'none'}, 'states the reason'), ({'kind': 'browser', 'url': 'legacy'}, 'names the url'),
                                 ({**EMULATOR, 'artifact': str(apk), 'build': build}, 'exactly one of'), ({**EMULATOR, 'artifact': 'legacy.apk'}, 'absolute path'),
                                 ({**EMULATOR, 'artifact': str(apk), 'device': {'avd': 'Pixel_6'}}, 'serial'), ({**EMULATOR, 'artifact': str(apk), 'extra': 1}, 'takes app_id'),
                                 ({**EMULATOR, 'build': {**build, 'output': 'out.apk'}}, 'absolute output'), ({**EMULATOR}, 'exactly one of')):
                with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                    pc.validate({'legacy_preview': bad})
            self.assertIsNone(pc.validate({'legacy_preview': None}).get('legacy_preview'))

    def test_prepare_binds_the_package_hash_and_ui_work_waits_for_the_statement(self):
        t = test_project_context.ProjectContextTests(); t.setUp(); self.addCleanup(t.doCleanups)
        apk = t.base / 'legacy.apk'
        pc.update(t.root, t.request('preview', 1, {'legacy_preview': {**EMULATOR, 'artifact': str(apk)}}), t.actor)
        with self.assertRaises(Rejected):
            t.prepare()  # the package is not there
        apk.write_bytes(b'the legacy build')
        result = t.prepare()
        t.start(t.init_payload(result))
        s = ledger.status(t.run)
        stated = pc.legacy_preview(s)
        self.assertEqual((stated['kind'], stated['artifact_sha256']), ('android-emulator', file_ref(apk)['sha256']))
        pc.preview_settled(s, {'UI', 'Logic'})
        with self.assertRaisesRegex(Rejected, 'legacy_preview is not settled'):
            pc.preview_settled({}, {'UI'})
        pc.preview_settled({}, {'Logic'})


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.shot = self.ref('login.png', 'legacy login pixels'); self.proof = self.ref('why.md', 'the screen needs a paired device')
        original = ui_fidelity.visual_plan_gate
        self.addCleanup(setattr, ui_fidelity, 'visual_plan_gate', original)
        ui_fidelity.visual_plan_gate = lambda analysis, visual: None

    def ref(self, name, content):
        path = self.base / name; path.write_text(content if isinstance(content, str) else json.dumps(content)); return file_ref(path)

    def state(self, preview, media=()):
        return {'ui_fidelity_required': True, 'modules': {}, 'case_ids': ['C1'], 'project_context_ref': self.ref(f"snapshot-{preview['kind']}-{len(media)}.json", {
            'effective_config': {'legacy_preview': preview}, 'source_refs': {'reference_media': list(media)}})}

    def analysis(self, evidence):
        return {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'M001-UI', 'case_ids': ['C1'], 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': {'coverage': 'login:base:viewport', **evidence}}}]}]}

    def gate(self, s, evidence, paths=()):
        with mock.patch.object(ui_fidelity, '_analysis', lambda m: self.analysis(evidence)):
            ui_fidelity.baseline_gate(s, {'module_id': 'M001', 'case_ids': ['C1'], 'plan': {'paths': list(paths)}})

    def test_executability_is_the_runs_statement_not_a_judgment_per_item(self):
        none = self.state({'kind': 'none', 'reason': 'the legacy needs a hardware token'})
        self.gate(none, {'visual_mode': 'source-only'})  # nobody has to decide: the run said it cannot run
        with self.assertRaisesRegex(Rejected, 'contradicts the run statement legacy_preview=none'):
            self.gate(none, {'visual_mode': 'runtime', 'legacy_executable': True, 'baseline_refs': [self.shot]})
        with self.assertRaisesRegex(Rejected, 'falls back to source-only'):
            self.gate(none, {'visual_mode': 'runtime', 'baseline_refs': [self.shot]})
        emulator = self.state({**EMULATOR, 'artifact': str(self.base / 'legacy.apk')})
        visual = {'path_id': 'PV', 'kind': 'visual', 'case_id': 'C1', 'coverage': 'login:base:viewport', 'node_ids': ['node:root'], 'baseline_ref': self.shot}
        self.gate(emulator, {'visual_mode': 'runtime', 'baseline_refs': [self.shot]}, [visual])
        shown = self.state({**EMULATOR, 'artifact': str(self.base / 'legacy.apk')},
                           media=[{'media_id': 'MEDIA-login', 'kind': 'screenshot', 'role': 'legacy-baseline', 'screen': 'login', 'case_ids': ['C1'], 'ref': self.shot}])
        self.gate(shown, {'visual_mode': 'user-reference', 'baseline_refs': [self.shot]}, [visual])  # the user's screenshot of a running legacy is a baseline too
        with self.assertRaisesRegex(Rejected, 'legacy runs on android-emulator: capture the screen'):
            self.gate(emulator, {'visual_mode': 'source-only'})
        self.gate(emulator, {'visual_mode': 'source-only', 'capture_gap': {'reason': 'the screen needs a paired device', 'evidence_refs': [self.proof]}})
        with self.assertRaisesRegex(Rejected, 'contradicts the run statement'):
            self.gate(emulator, {'visual_mode': 'source-only', 'legacy_executable': False})

    def test_the_report_names_the_baseline_origin_and_the_statement(self):
        s = self.state({'kind': 'none', 'reason': 'the legacy needs a hardware token'})
        gap = {'reason': 'the screen needs a paired device', 'evidence_refs': [self.proof]}
        s['modules'] = {'M001': {'module_id': 'M001', 'case_ids': ['C1'], 'plan': {'dimension_analysis_ref': self.ref('analysis.json', self.analysis(
            {'visual_mode': 'source-only', 'legacy_executable': True, 'capture_gap': gap})), 'paths': []}}}
        visual, limitations, _ = migration_report.fidelity(s, [], check_ref)
        self.assertEqual((visual[0]['origin'], visual[0]['status']), ('capture-gap', 'not-verified'))
        self.assertIn('the screen needs a paired device', visual[0]['reason'])
        self.assertTrue(any(row['kind'] == 'visual-coverage' and row['origin'] == 'capture-gap' for row in limitations))
        empty = {key: [] for key in ('cases', 'paths', 'non_green', 'contract_retirements', 'open_issues', 'reference_media', 'rule_debt', 'slicing', 'target_profile', 'unimplemented')}
        text = migration_report.render({**empty, 'schema_version': 1, 'run_id': 'r', 'sequence': 1, 'report_stage': 'in-progress', 'quality': 'yellow-blocked', 'case_counts': {},
                                        'visual_coverage': visual, 'fidelity_limitations': limitations, 'legacy_preview': pc.legacy_preview(s), 'automation': automation_report.build(s, []),
                                        'human_report': None, 'human_report_path': None, 'snapshot': {}, 'audit': {}, 'parent_mo_names': {}, 'entry_mode': 'project',
                                        'single_module_id': None, 'legacy_root': '/l', 'target_root': '/t'})
        self.assertIn('存量预览：不可运行（the legacy needs a hardware token）', text)
        self.assertIn('| capture-gap |', text)


if __name__ == '__main__':
    unittest.main()
