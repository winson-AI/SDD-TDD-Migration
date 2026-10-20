"""The host names no command: build, unit and in-process PATHs run what the plan froze, a device PATH runs the adapter
the project states for its platform, and an explicit --adapter still overrides."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, check_ref, read_json
import execute_test
import project_context as pc
import test_functional_paths

WEB = {'argv': ['/opt/py/bin/python', '/opt/pkg/skills/migration-test/scripts/web_main.py', '--root', '{run_root}'], 'timeout_seconds': 600}


class AdapterChoiceTests(unittest.TestCase):
    def test_the_project_states_one_adapter_per_platform(self):
        config = {'test_adapter': {'adapters': {'web': WEB, 'android': {'argv': ['/opt/py/bin/python', '/opt/pkg/sandbox.py', 'test'], 'cwd': '/opt/target'}}}}
        self.assertEqual(pc.validate(dict(config))['test_adapter']['adapters']['web'], WEB)
        for bad in ({'ios': WEB}, {'web': {'argv': ['python']}}, {'web': {'argv': []}}, {'web': {'argv': WEB['argv'], 'cwd': 'relative'}},
                    {'web': {'argv': WEB['argv'], 'timeout_seconds': 0}}, {'web': {'argv': WEB['argv'], 'extra': 1}}, {'web': WEB['argv']}):
            with self.assertRaisesRegex(Rejected, 'test_adapter.adapters'):
                pc.validate({'test_adapter': {'adapters': bad}})

    def test_the_command_follows_the_path_then_the_platform_then_the_single_adapter(self):
        s = {'target_root': '/opt/target', 'test_adapter': {'adapters': {'web': WEB}, 'executable': '/opt/adapter', 'args': ['--all']}}
        frozen = {'kind': 'unit', 'command': {'argv': ['/usr/bin/gradle', 'test'], 'cwd': '/opt/target/app', 'timeout_seconds': 90}}
        self.assertEqual(execute_test.adapter_for(s, frozen, Path('/runs/r1')), {'argv': ['/usr/bin/gradle', 'test'], 'cwd': '/opt/target/app', 'timeout': 90})
        web = execute_test.adapter_for(s, {'kind': 'automation', 'platform': 'web'}, Path('/runs/r1'))
        self.assertEqual(web, {'argv': ['/opt/py/bin/python', '/opt/pkg/skills/migration-test/scripts/web_main.py', '--root', '/runs/r1'], 'cwd': '/opt/target', 'timeout': 600})
        self.assertEqual(execute_test.adapter_for(s, {'kind': 'automation', 'platform': 'android'}, Path('/runs/r1')),
                         {'argv': ['/opt/adapter', '--all'], 'cwd': '/opt/target', 'timeout': 300})
        with self.assertRaisesRegex(Rejected, 'no adapter runs platform harmony PATHs'):
            execute_test.adapter_for({'target_root': '/opt/target', 'test_adapter': {'adapters': {'web': WEB}}}, {'kind': 'automation', 'platform': 'harmony'}, Path('/runs/r1'))

    def test_an_in_process_path_runs_its_frozen_command_when_the_host_names_none(self):
        t = test_functional_paths.FunctionalPathTests(); t.setUp(); self.addCleanup(t.doCleanups)
        f = t.f
        t.inner.run_unit()
        t.flow_file.write_text(json.dumps({'xml': test_functional_paths.XML % (0, ''), 'code': 0}))
        t.inner.fixture.split.f.assign('test-runner', 'AUTO1')
        receipt = read_json(check_ref(execute_test.execute(f.root, 'M001', 'AUTO1', 'P1', None, None, f.base / 'flow-attempt')))
        self.assertEqual((receipt['requested_argv'], receipt['exit_code']), (t.flow_argv(), 0))

    def test_the_cli_takes_no_adapter_unless_the_host_overrides(self):
        calls = []
        with patch.object(execute_test, 'execute', side_effect=lambda *a: calls.append(a) or 'ref'), \
             patch.object(execute_test.run_storage, 'layout', lambda *a: None), \
             patch.object(sys, 'argv', ['execute_test.py', '--root', '/w/.sdd-runs/r1', '--module', 'M001', '--assignment', 'T1', '--path-id', 'P1', '--output', '/w/.sdd-runs/r1/runs/harmony/automation/a1']):
            self.assertEqual(execute_test.main(), 0)
        self.assertEqual(calls[0][4:], (None, None, '/w/.sdd-runs/r1/runs/harmony/automation/a1', None))


if __name__ == '__main__':
    unittest.main()
