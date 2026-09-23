"""Workflow path contracts at CLI boundaries; standalone tools remain usable."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
LEDGER = Path(__file__).resolve().parents[2] / 'migration-ledger'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(LEDGER / 'tests'))
sys.path.insert(0, str(LEDGER / 'scripts'))
import test_project_context
from harmony_adapter import ENGINE
from harmony_stage import save
from contracts import Rejected


class ManagedOutputTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.prepare()

    def call(self, script, *args):
        return subprocess.run([sys.executable, str(script), *map(str, args)],
                              cwd=self.f.base, text=True, capture_output=True)

    def test_adapter_creates_nested_staging_and_binds_execution_root(self):
        output = self.f.run / 'runs/harmony/sandbox/host/new/adapter.json'
        result = self.call(ENGINE / 'sandbox.py', 'adapter', '--root', self.f.run, '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(output.read_text())['argv']
        self.assertEqual(argv[argv.index('--root') + 1], str(self.f.run))
        denied = self.call(ENGINE / 'sandbox.py', 'adapter', '--root', self.f.run,
                           '--output', self.f.base / 'outside.json')
        self.assertNotEqual(denied.returncode, 0)
        self.assertFalse((self.f.base / 'outside.json').exists())
        denied_execution = self.call(ENGINE / 'sandbox.py', 'test', '--root', self.f.run,
                                     '--query-file', self.f.base / 'query.json',
                                     '--result-file', self.f.base / 'result.json')
        self.assertNotEqual(denied_execution.returncode, 0)
        self.assertFalse((self.f.base / 'result.json').exists())

    def test_design_creates_draft_in_nested_staging_and_rejects_symlink(self):
        source = self.f.base / 'cases.md'; source.write_text('## 用例描述: 登录\n验证成功登录。\n')
        output = self.f.run / 'runs/harmony/sandbox/designer/new/draft'
        result = self.call(ENGINE / 'sandbox.py', 'design', '--root', self.f.run,
                           '--input', source, '--module', 'M001', '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((output / 'test-design-draft.json').read_text())['status'], 'draft-not-executable')
        link = self.f.run / 'runs/harmony/sandbox/redirect'; link.symlink_to(self.f.base, target_is_directory=True)
        for script, command in ((ENGINE / 'sandbox.py', ['design']), (SCRIPTS / 'harmony_design.py', [])):
            result = self.call(script, *command, '--root', self.f.run, '--input', source,
                               '--module', 'M001', '--output', link / 'escaped')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.f.base / 'escaped').exists())
        # Omitting --root is the documented standalone import mode.
        standalone = self.call(SCRIPTS / 'harmony_design.py', '--input', source,
                               '--module', 'M001', '--output', self.f.base / '.sdd-runs/standalone/runs/harmony/sandbox/nested/draft')
        self.assertEqual(standalone.returncode, 0, standalone.stderr)

    def test_stage_creates_parent_and_never_overwrites_or_escapes(self):
        output = self.f.run / 'runs/harmony/sandbox/test-runner/new/stage.json'
        save(self.f.run, output, {'fixture': True})
        self.assertEqual(json.loads(output.read_text()), {'fixture': True})
        with self.assertRaises(FileExistsError): save(self.f.run, output, {})
        with self.assertRaises(Rejected): save(self.f.run, self.f.base / 'outside.json', {})
        self.assertFalse((self.f.base / 'outside.json').exists())

    def test_standalone_test_creates_nested_result_parent_and_preserves_existing_attempt(self):
        from test_harmony import query
        queryfile = self.f.base / 'query.json'; queryfile.write_text(json.dumps(query()))
        config = self.f.base / 'config.json'; config.write_text(json.dumps({'device': ''}))
        output = self.f.base / '.sdd-runs/standalone/runs/harmony/automation/new-attempt/result.json'
        args = ['test', '--config', config, '--env-file', self.f.base / 'absent.env',
                '--query-file', queryfile, '--result-file', output]
        from unittest.mock import patch
        import os
        with patch.dict(os.environ, {'HARMONY_DEVICE': ''}):
            result = self.call(ENGINE / 'sandbox.py', *args)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(output.read_text())['quality'], 'yellow-blocked')
            before = {str(p): p.read_bytes() for p in output.parent.rglob('*') if p.is_file()}
            retry = self.call(ENGINE / 'sandbox.py', *args)
            self.assertNotEqual(retry.returncode, 0)
            self.assertEqual(before, {str(p): p.read_bytes() for p in output.parent.rglob('*') if p.is_file()})
            # Even without an engine directory, a preexisting result must not be overwritten.
            output = self.f.base / 'existing-result.json'; output.write_text('preserve me')
            args[-1] = output
            self.assertNotEqual(self.call(ENGINE / 'sandbox.py', *args).returncode, 0)
            self.assertEqual(output.read_text(), 'preserve me')

    def test_combined_report_requires_explicit_paths_and_preserves_detail_links(self):
        history = self.f.run / 'runs/harmony/automation/attempt/harmony/reports'
        case = history / 'case'; case.mkdir(parents=True)
        (case / 'result.json').write_text(json.dumps({'test_case': 'case', 'events': [
            {'event_type': 'task_end', 'content': '任务结果：通过'}]}))
        detail = case / 'detail.html'; detail.write_text('<p>Evidence</p>')
        output = self.f.run / 'runs/harmony/sandbox/auditor/new/summary'
        script = ENGINE / 'generate_combined_report.py'
        result = self.call(script, '--root', self.f.run, '--history-dir', history, '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output / 'index.html').is_file(), result.stdout)
        import os
        self.assertIn(os.path.relpath(detail, output), (output / 'index.html').read_text())
        denied = self.call(script, '--root', self.f.run, '--history-dir', history, '--output', self.f.base / 'outside')
        self.assertNotEqual(denied.returncode, 0)
        self.assertFalse((self.f.base / 'outside').exists())
        standalone = self.call(script, '--history-dir', history, '--output', self.f.base / '.sdd-runs/standalone/runs/harmony/sandbox/report')
        self.assertEqual(standalone.returncode, 0, standalone.stderr)
        self.assertTrue((self.f.base / '.sdd-runs/standalone/runs/harmony/sandbox/report/index.html').is_file())
        self.assertNotEqual(self.call(script).returncode, 0)


if __name__ == '__main__': unittest.main()
