"""snapshot and recording walk a frozen path and keep its media: no verify, no verdict; the adapter turns the engine's
outcome into a receipt a capture or an evidence binding can stand on."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from harmony_adapter import ENGINE, execution_config, media_report, recording_refs
from harmony_contract import validate_query
from runner_storage import scope
from test_harmony import query


def media_query(task_type='snapshot'):
    q = {**query(), 'task_type': task_type}
    for key in ('expected_assertions', 'freeze_id', 'code_baseline'):
        q.pop(key)
    return q


class MediaQueryTests(unittest.TestCase):
    def test_a_media_task_walks_frozen_steps_and_verifies_nothing(self):
        raw = {'devices': {'android': 'A'}, 'models': {'execute_provider': 'general'}}
        for mode in ('snapshot', 'recording'):
            validate_query(media_query(mode))
            self.assertEqual(execution_config(raw, {**media_query(mode), 'platform': 'android'})['task_type'], mode)
        with self.assertRaisesRegex(ValueError, 'carry no assertions'):
            validate_query({**query(), 'task_type': 'snapshot'})
        with self.assertRaisesRegex(ValueError, 'frozen steps'):
            validate_query({**media_query(), 'steps': []})
        without_path = {k: v for k, v in media_query().items() if k != 'path_id'}
        with self.assertRaisesRegex(ValueError, 'path_id or capture_id'):
            validate_query(without_path)
        validate_query({**without_path, 'capture_id': 'CAP-1'})
        with self.assertRaises(ValueError):
            validate_query({**media_query(), 'task_type': 'preview'})
        with self.assertRaisesRegex(ValueError, 'task_type test, snapshot or recording'):
            execution_config({**raw, 'task_type': 'snapshot'}, {**query(), 'platform': 'android'})  # a config pinned to another type


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name).resolve() / '.sdd-runs/media/runs/harmony/automation/attempt'
        self.report_dir = self.out / 'reports/run'
        (self.report_dir / 'layout').mkdir(parents=True); (self.report_dir / 'screenshots').mkdir()
        sys.path.insert(0, str(ENGINE))

    def reporter(self):
        out = self.report_dir

        class Reporter:
            report_dir, layout_dir, screenshot_dir, video_dir = out, out / 'layout', out / 'screenshots', None
            saved = []

            def task_start(self): pass

            def task_end(self, task_result=None): pass

            def save_screenshot(self, base64_data, layout_data='', prefix='screenshot'):
                path = out / 'screenshots' / f'{prefix}_1.jpeg'; path.write_bytes(b'frame')
                (out / 'layout' / f'{prefix}_1.json').write_text(layout_data)
                self.saved.append(prefix); return str(path)
        return Reporter()

    def walk(self, task_type, runner):
        from AutoTest.layered_agent_cli import decision as module
        hooks = []

        def hooks_factory(*args, **kwargs):
            hooks.append(kwargs); return SimpleNamespace()

        async def no_sleep(_): pass
        shot = SimpleNamespace(base64_data='AAAA', layout_data='<hierarchy/>')
        device = SimpleNamespace(get_screenshot=lambda save_to_report=True: shot, teardown=lambda: None)
        cfg = SimpleNamespace(decision_model_name='fixture', task_timeout=5, max_steps=3)
        reporter = self.reporter()
        with scope(self.out), patch.object(module, 'create_planner_agent', return_value=SimpleNamespace(name='fixture')), \
             patch.object(module, 'DecisionHooks', side_effect=hooks_factory), patch.object(module.Runner, 'run', side_effect=runner), \
             patch('AutoTest.utils.utils.asyncio.sleep', no_sleep):
            text = asyncio.run(module.decision('walk to the login screen', cfg, reporter, device, task_type=task_type))
        return text, hooks[0], reporter

    def test_a_snapshot_keeps_the_stable_final_frame_and_says_whether_the_path_was_walked(self):
        async def reached(*args, **kwargs): return SimpleNamespace(final_output='到达终点')
        text, hook, reporter = self.walk('snapshot', reached)
        self.assertFalse(hook['require_verify']); self.assertEqual(reporter.saved, ['final_snapshot'])
        outcome = json.loads((self.report_dir / 'media_outcome.json').read_text())
        self.assertTrue(outcome['reached']); self.assertTrue(outcome['snapshot_path'].endswith('final_snapshot_1.jpeg')); self.assertTrue(outcome['layout_path'])
        self.assertIn('最终截图', text)
        report = media_report(media_query('snapshot'), self.out)
        self.assertEqual((report['status'], report['reason'], report['snapshot_ref']['path'], bool(report['layout_ref']), report['outcome_ref']['path']),
                         ('reached', None, outcome['snapshot_path'], True, str(self.report_dir / 'media_outcome.json')))
        from agents.exceptions import MaxTurnsExceeded

        async def cut_short(*args, **kwargs): raise MaxTurnsExceeded('too many')
        text, hook, reporter = self.walk('snapshot', cut_short)
        outcome = json.loads((self.report_dir / 'media_outcome.json').read_text())
        self.assertFalse(outcome['reached']); self.assertIn('超过步数', outcome['reason']); self.assertTrue(outcome['snapshot_path'])  # best effort, for review
        self.assertIn('需人工review', text)
        self.assertEqual(media_report(media_query('snapshot'), self.out)['status'], 'needs-review')
        self.assertEqual(media_report(media_query('snapshot'), self.out, error='device busy')['status'], 'blocked')
        text, hook, _ = self.walk('test', reached)
        self.assertTrue(hook['require_verify']); self.assertEqual(text, '到达终点')
        with self.assertRaisesRegex(ValueError, 'task_type must be one of'):
            self.walk('preview', reached)

    def test_a_recording_is_the_pulled_final_video_and_a_test_may_keep_one_as_evidence(self):
        video = self.report_dir / 'videoPath'; video.mkdir(); (video / 'final.mp4').write_bytes(b'mp4')
        (self.report_dir / 'media_outcome.json').write_text(json.dumps({'task_type': 'recording', 'reached': True, 'recording_path': str(video / 'final.mp4'), 'snapshot_path': None, 'layout_path': None, 'reason': None}))
        report = media_report(media_query('recording'), self.out)
        self.assertEqual((report['status'], report['recording_ref']['path']), ('reached', str(video / 'final.mp4')))
        self.assertEqual([m['kind'] for m in recording_refs(self.out)], ['recording'])
        (self.report_dir / 'media_outcome.json').write_text(json.dumps({'task_type': 'recording', 'reached': True, 'recording_path': None}))
        self.assertEqual(media_report(media_query('recording'), self.out)['reason'], 'the engine reached the end without the media it was asked for')
        (self.report_dir / 'media_outcome.json').unlink()
        self.assertEqual(media_report(media_query('recording'), self.out)['reason'], 'engine produced no media outcome')


if __name__ == '__main__':
    unittest.main()
