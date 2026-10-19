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
DECLINED = {'declined': {'copy': 'the target bundles no files', 'parameters': 'values are typed in the design system'}}


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


class IntakeTests(unittest.TestCase):
    def test_the_person_is_asked_what_nobody_infers_until_all_three_statements_are_made(self):
        self.assertEqual([q['field'] for q in pc.intake({})], ['legacy_preview', 'test_adapter.device', 'target_resources'])
        half = {'declined': {'copy': 'the target bundles no files'}}  # one part stated or declined leaves the statement open
        self.assertIn('target_resources', [q['field'] for q in pc.intake({'target_resources': half})])
        self.assertNotIn('target_resources', [q['field'] for q in pc.intake({'target_resources': DECLINED})])
        t = test_project_context.ProjectContextTests(); t.setUp(); self.addCleanup(t.doCleanups)
        result = pc.update(t.root, t.request('device', 1, {'test_adapter': {'device': {'platforms': ['android']}}}), t.actor)
        self.assertEqual([q['field'] for q in result['open_statements']], ['legacy_preview', 'target_resources'])
        prepared = t.prepare()
        self.assertEqual([q['field'] for q in prepared['open_statements']], ['legacy_preview', 'target_resources'])
        t.start(t.init_payload(prepared))
        signals = [s for s in ledger.status(t.run)['workflow_progress']['signals'] if s['reason'] == 'statement-required']
        self.assertEqual([(s['owner'], s['severity'], s['evidence']['field']) for s in signals],
                         [('host', 'human', 'legacy_preview'), ('host', 'human', 'target_resources')])
        self.assertIn('存量应用怎样跑', signals[0]['next_action'])
        self.assertIn('怎样进目标', signals[1]['next_action'])
        self.assertEqual(signals[1]['evidence']['options'], ['copy', 'parameters', 'declined'])
        result = pc.update(t.root, t.request('preview', 2, {'legacy_preview': {'kind': 'none', 'reason': 'no build'}}), t.actor)
        self.assertEqual([q['field'] for q in result['open_statements']], ['target_resources'])
        result = pc.update(t.root, t.request('resources', 3, {'target_resources': DECLINED}), t.actor)
        self.assertEqual(result['open_statements'], [])
        second = pc.prepare(t.root, t.base / '.sdd-runs/r2', t.run_request('r2'), t.actor)
        self.assertEqual(second['open_statements'], [])


class NavigatorStatementTests(unittest.TestCase):
    def test_a_navigator_is_the_absolute_adapter_command_that_walks_a_snapshot_task(self):
        good = {**EMULATOR, 'artifact': '/opt/legacy/legacy.apk', 'navigator': {'argv': ['/usr/bin/python3', '/opt/adapter/main.py'], 'cwd': '/opt/adapter', 'timeout_seconds': 600}}
        self.assertEqual(pc.legacy_preview_config(good)['navigator'], good['navigator'])
        for bad in ({'argv': ['main.py'], 'cwd': '/opt/adapter', 'timeout_seconds': 600}, {'argv': ['/usr/bin/python3'], 'cwd': '/opt/adapter'}, 'adapter'):
            with self.assertRaisesRegex(Rejected, 'navigator takes the absolute argv'):
                pc.legacy_preview_config({**good, 'navigator': bad})


class EmulatorStatementTests(unittest.TestCase):
    def test_the_device_statement_may_say_how_its_emulator_is_booted(self):
        boot = {'argv': ['/opt/sdk/emulator/emulator', '-avd', 'pixel_7'], 'timeout_seconds': 300}
        good = {**EMULATOR, 'artifact': '/opt/legacy/legacy.apk', 'device': {'serial': 'emulator-5554', 'avd': 'pixel_7', 'boot': boot}}
        self.assertEqual(pc.legacy_preview_config(good)['device']['boot'], boot)
        for bad in ({'argv': ['emulator', '-avd', 'x']}, {'argv': []}, {'argv': ['/opt/e'], 'timeout_seconds': 0}, 'emulator'):
            with self.assertRaisesRegex(Rejected, 'device.boot takes'):
                pc.legacy_preview_config({**good, 'device': {'serial': 'emulator-5554', 'boot': bad}})


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
        from contracts import carrying
        with carrying() as gaps:  # owed, not refused: the first version goes on and the gap is reported
            self.gate(emulator, {'visual_mode': 'source-only'})
        self.assertTrue(any('legacy runs on android-emulator: capture the screen' in gap for gap in gaps))
        with carrying() as gaps:
            self.gate(emulator, {'visual_mode': 'source-only', 'capture_gap': {'reason': 'the screen needs a paired device', 'evidence_refs': [self.proof]}})
        self.assertEqual(gaps, [])
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


class CaptureDueTests(BaselineTests):
    """Where the legacy runs, the planner is told what to capture and reads how; nothing is due where it cannot run."""
    def test_the_step_lists_uncaptured_items_and_the_latest_capture(self):
        import reading
        emulator = self.state({**EMULATOR, 'artifact': str(self.base / 'legacy.apk')})
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'U-login', 'case_ids': ['C1'], 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': {'coverage': 'login:base:viewport', 'visual_mode': 'runtime', 'baseline_refs': [self.shot]}}},
            {'item_id': 'U-list', 'case_ids': ['C2'], 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': {'coverage': 'list:base:viewport', 'visual_mode': 'source-only'}}},
            {'item_id': 'U-settings', 'case_ids': ['C3']},
            {'item_id': 'U-gap', 'case_ids': ['C4'], 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': {'coverage': 'gap:base:viewport', 'visual_mode': 'source-only', 'capture_gap': {'reason': 'paired device', 'evidence_refs': [self.proof]}}}}]}]}
        m = {'module_id': 'M001', 'dimension_analysis_ref': self.ref('allocation.json', analysis)}
        due = ui_fidelity.capture_due(emulator, m)
        self.assertEqual((due['legacy_preview'], [i['item_id'] for i in due['items']], due['last_capture']), ('android-emulator', ['U-list', 'U-settings'], None))
        run_root = self.base / '.sdd-runs/run-1'; emulator['run_root'] = str(run_root)
        out = run_root / 'runs/harmony/sandbox/spec-1/cap-1'; out.mkdir(parents=True)
        manifest = self.ref('.sdd-runs/run-1/runs/harmony/sandbox/spec-1/cap-1/manifest.json', {'schema_version': 2, 'targets': []})
        result = self.ref('.sdd-runs/run-1/runs/harmony/sandbox/spec-1/cap-1/result.json', {'status': 'PARTIAL', 'manifest_ref': manifest, 'captured': ['list:base:viewport'], 'blocked': []})
        self.ref('.sdd-runs/run-1/runs/harmony/sandbox/spec-1/cap-1/receipt.json', {'operation': 'legacy-capture', 'module_id': 'M001', 'status': 'produced', 'result_ref': result, 'finished_at': '2026-01-01T00:00:00+00:00'})
        self.assertEqual(ui_fidelity.capture_due(emulator, m)['last_capture']['manifest_ref'], manifest)
        self.assertIsNone(ui_fidelity.capture_due(self.state({'kind': 'none', 'reason': 'no build'}), m))
        card = {(row['ref'].split('/')[-1], row['section']) for row in reading.card(emulator, m, {'role': 'spec-designer', 'operation': 'plan'})}
        self.assertLessEqual({('project-context.md', '存量预览'), ('visual-execution.md', '4. 存量捕获')}, card)
        quiet = {(row['ref'].split('/')[-1], row['section']) for row in reading.card(self.state({'kind': 'none', 'reason': 'no build'}), m, {'role': 'spec-designer', 'operation': 'plan'})}
        self.assertNotIn(('visual-execution.md', '4. 存量捕获'), quiet)

    def test_the_plan_step_carries_what_is_due(self):
        import test_ledger
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()
        with mock.patch.object(ui_fidelity, 'capture_due', return_value={'legacy_preview': 'vm', 'items': [{'item_id': 'U1'}], 'last_capture': None}):
            step = next(x for x in f.state()['next_steps'] if x['operation'] == 'plan')
        self.assertEqual(step['capture_due']['items'], [{'item_id': 'U1'}])


class CarriedStatementTests(unittest.TestCase):
    """What a run settled about the legacy is carried to the project's next run unless that run says otherwise."""
    def test_experience_carries_the_statement_and_prepare_takes_it_when_the_config_is_silent(self):
        import experience
        t = test_project_context.ProjectContextTests(); t.setUp(); self.addCleanup(t.doCleanups)
        none = {'kind': 'none', 'reason': 'the legacy needs a hardware token'}
        pc.update(t.root, t.request('preview', 1, {'legacy_preview': none}), t.actor)
        result = t.prepare(); t.start(t.init_payload(result))
        self.assertEqual(experience.settled(ledger.status(t.run))['legacy_preview'], none)
        pc.update(t.root, t.request('forget', 2, {'legacy_preview': None}), t.actor)
        apk = t.base / 'carried.apk'; apk.write_bytes(b'apk')
        carried = {**EMULATOR, 'artifact': str(apk), 'artifact_sha256': 'stale'}
        with mock.patch.object(experience, 'conventions', return_value={'legacy_preview': carried}):
            second = pc.prepare(t.root, t.base / '.sdd-runs/r2', t.run_request('r2'), t.actor)
        stated = pc.verify_snapshot(second['project_context_ref'])['effective_config']['legacy_preview']
        self.assertEqual((stated['kind'], stated['artifact_sha256']), ('android-emulator', file_ref(apk)['sha256']))  # re-hashed for this run
        apk.unlink()
        with mock.patch.object(experience, 'conventions', return_value={'legacy_preview': carried}):
            third = pc.prepare(t.root, t.base / '.sdd-runs/r3', t.run_request('r3'), t.actor)
        self.assertIsNone(pc.verify_snapshot(third['project_context_ref'])['effective_config'].get('legacy_preview'))  # the package is gone: nothing is assumed

    def test_the_sandbox_doctor_names_the_capture_tools_without_blocking_on_them(self):
        import importlib.util, sys
        root = Path(__file__).resolve().parents[2] / 'migration-test/runtime/harmony'
        spec = importlib.util.spec_from_file_location('sandbox_doctor_probe', root / 'sandbox.py'); module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(root)); sys.path.insert(0, str(root.parent.parent / 'scripts'))
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.json'; config.write_text('{}')
            report = module.doctor(str(config))
        probes = {c['name']: c['status'] for c in report['checks'] if c['name'] in ('adb-on-path', 'playwright')}
        self.assertEqual(set(probes), {'adb-on-path', 'playwright'})
        self.assertTrue(all(status in ('ready', 'optional-absent') for status in probes.values()))


if __name__ == '__main__':
    unittest.main()
