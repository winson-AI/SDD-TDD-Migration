"""Exercise native writers directly: CLI wrappers must not be the only guard."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

ENGINE = Path(__file__).resolve().parents[1] / 'runtime/harmony'
sys.path.insert(0, str(ENGINE))
from AutoTest.storage import output_path, temp_directory
from AutoTest.testcase_preprocessor.pipeline import ensure_task_file, resolve_output_path
from AutoTest.config import AppConfig
from runner_storage import scope


class NativeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / '.sdd-runs/first'
        self.out = self.root / 'runs/harmony/automation/attempt'
        self.out.mkdir(parents=True)
        self.env = patch.dict(os.environ)
        self.env.start(); self.addCleanup(self.env.stop)
        os.environ.pop('SDD_RUNNER_DIR', None)

    def test_xmind_direct_api_requires_managed_output_and_preserves_source(self):
        source = self.base / 'cases.xmind'; source.write_bytes(b'original')
        neighbour = source.with_suffix('.md'); neighbour.write_text('original neighbour')
        with self.assertRaises(ValueError): resolve_output_path(str(source), None)
        with self.assertRaises(ValueError): resolve_output_path(str(source), str(self.base / 'outside'))
        destination = self.root / 'runs/harmony/sandbox/design'
        with patch('AutoTest.testcase_preprocessor.pipeline.extract_tree', return_value='complete tree'), \
             patch('AutoTest.testcase_preprocessor.pipeline.convert_tree_to_md', new=AsyncMock(return_value='converted')):
            result = asyncio.run(ensure_task_file(str(source), AppConfig(), str(ENGINE), str(destination)))
        self.assertEqual(Path(result), destination / 'cases.md')
        self.assertEqual(Path(result).read_text(), 'converted')
        self.assertEqual(neighbour.read_text(), 'original neighbour')
        self.assertEqual(source.read_bytes(), b'original')
        self.assertFalse((self.base / 'outside').exists())
        with scope(self.out):
            self.assertEqual(Path(resolve_output_path(str(source), None)), self.out / 'design/cases.md')

    def test_direct_writers_reject_external_outputs_before_creating_files(self):
        from AutoTest.reporter.generator import ReportGenerator
        from AutoTest.reporter.summary import generate_summary_report
        from AutoTest.memory.tool_recorder import ToolRecorder
        from AutoTest.logger import configure_logger
        from generate_combined_report import generate_summary_report as combined
        from mcp_tools.media_generator import generate_random_gradient_image, generate_random_gradient_video
        outside = self.base / 'outside'
        calls = [lambda: ReportGenerator('task', 'case', str(outside)),
                 lambda: ReportGenerator('task', 'case'),
                 lambda: ToolRecorder('task', str(outside)),
                 lambda: ToolRecorder('task'),
                 lambda: configure_logger(log_file=str(outside / 'engine.log')),
                 lambda: generate_summary_report([], 0, str(outside)),
                 lambda: combined([], 0, str(outside)),
                 lambda: generate_random_gradient_image(1, 1, str(outside / 'image.jpg')),
                 lambda: generate_random_gradient_video(1, 1, output_path=str(outside / 'video.mp4'))]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(ValueError): call()
        self.assertFalse(outside.exists())

    def test_runner_defaults_generate_reports_memory_and_media_inside_attempt(self):
        from AutoTest.reporter.generator import ReportGenerator
        from AutoTest.memory.tool_recorder import ToolRecorder
        from mcp_tools.media_generator import generate_random_gradient_image
        with scope(self.out):
            report = ReportGenerator('task', 'case')
            files = report.save_all()
            recording = ToolRecorder('task').save_to_file()
            generate_random_gradient_image(1, 1)
            for file in [*files.values(), recording, str(self.out / 'gradient_image.jpg')]:
                self.assertTrue(Path(file).is_relative_to(self.out))
                self.assertTrue(Path(file).is_file())
        self.assertFalse((self.out / 'temp').exists())

    def test_cross_run_symlink_and_late_file_redirect_are_rejected(self):
        from AutoTest.reporter.generator import ReportGenerator
        outside = self.base / 'outside'; outside.mkdir()
        (self.out / 'redirect').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): output_path(self.out / 'redirect/file')
        with scope(self.out):
            with self.assertRaises(ValueError):
                output_path(self.base / '.sdd-runs/other/runs/harmony/sandbox/out')
            report = ReportGenerator('task', 'case', str(self.out / 'reports'))
            (report.report_dir / 'result.html').symlink_to(outside / 'result.html')
            with self.assertRaises(ValueError): report.save_all('result')
        self.assertEqual(list(outside.iterdir()), [])

    def test_screenshot_and_temp_without_runner_fail_before_device_io(self):
        from AutoTest.devices.hdc.screenshot import get_screenshot
        from unittest.mock import Mock
        driver = Mock()
        with self.assertRaises(ValueError): temp_directory()
        with self.assertRaises(ValueError): get_screenshot(driver)
        driver.UiTree.dump_page_info.assert_not_called()
        with scope(self.out):
            self.assertEqual(temp_directory(), self.out / 'temp')

    def test_shell_requires_runner_and_rejects_storage_environment_override(self):
        from AutoTest.layered_agent_cli.mcp_tools import _run_shell_command_sync
        self.assertFalse(_run_shell_command_sync('exit 0')['success'])
        with scope(self.out):
            rejected = _run_shell_command_sync('exit 0', env={'TMPDIR': str(self.base / 'outside')})
            self.assertFalse(rejected['success'])
            self.assertFalse(_run_shell_command_sync('exit 0', cwd=str(self.base))['success'])
            result = _run_shell_command_sync('printf fixture > shell-evidence.txt')
            self.assertTrue(result['success'])
            self.assertEqual((self.out / 'shell-evidence.txt').read_text(), 'fixture')
        self.assertFalse((self.base / 'outside').exists())

    def test_external_video_input_is_not_deleted_or_written_beside(self):
        from AutoTest.verify_agent.verify_tools import video_assert_tool
        source = self.base / 'merged_video_source.mp4'; source.write_bytes(b'original')
        metadata = source.with_suffix('.mapping.json'); metadata.write_text('{}')
        def make_clip(**kwargs):
            path = Path(kwargs['output_path'])
            self.assertTrue(path.is_relative_to(self.out / 'temp'))
            path.write_bytes(b'clip'); return str(path)
        with scope(self.out), \
             patch('AutoTest.verify_agent.verify_tools.prepare_video_for_verification', side_effect=make_clip), \
             patch('AutoTest.verify_agent.verify_tools.call_video_verify_api', return_value='结论：通过'):
            passed, _ = video_assert_tool('predicate', 1, 2, video_path=str(source), config=AppConfig(keep_raw_video=False))
        self.assertTrue(passed)
        self.assertEqual(source.read_bytes(), b'original')
        self.assertEqual(metadata.read_text(), '{}')
        self.assertEqual(len(list((self.out / 'reports/videoPath').glob('clip*.mp4'))), 1)
        self.assertEqual(list(self.base.glob('clip*.mp4')), [])


if __name__ == '__main__': unittest.main()
