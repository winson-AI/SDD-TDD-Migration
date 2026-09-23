"""Sandbox configuration, credential isolation and adapter handoff; no live LLM/device."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from harmony_adapter import ENGINE, resolve_env, public_config
from test_harmony import query
from harmony_environment import prepare_environment
import harmony_environment as environment_module

spec = importlib.util.spec_from_file_location('sandbox', ENGINE / 'sandbox.py')
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)


class SandboxTests(unittest.TestCase):
    def test_run_configuration_is_private_stable_and_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            source = workspace / '.sdd-migration/harmony'
            source.mkdir(parents=True)
            (source / 'config.json').write_text('{"device":"first"}')
            (source / '.env').write_text('DASHSCOPE_API_KEY=private-fixture\n')
            first = workspace / '.sdd-runs/first'
            config, env = prepare_environment(first)
            self.assertEqual(config.parent, first / 'runs/harmony/sandbox/environment')
            self.assertEqual(json.loads(config.read_text())['device'], 'first')
            self.assertEqual(env.read_text(), (source / '.env').read_text())
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)
            before = (config.stat().st_mtime_ns, env.stat().st_mtime_ns)
            (source / 'config.json').write_text('{"device":"second"}')
            prepare_environment(first)
            self.assertEqual(before, (config.stat().st_mtime_ns, env.stat().st_mtime_ns))
            with self.assertRaisesRegex(ValueError, 'already exists'):
                prepare_environment(first, source / 'config.json')
            other, _ = prepare_environment(workspace / '.sdd-runs/second')
            self.assertEqual(json.loads(other.read_text())['device'], 'second')
            self.assertEqual(json.loads(config.read_text())['device'], 'first')

    def test_missing_source_does_not_partially_copy_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / '.sdd-runs/run'
            with self.assertRaises(FileNotFoundError):
                prepare_environment(root, env_source=Path(tmp) / 'missing.env')
            self.assertFalse((root / 'runs/harmony/sandbox/environment/config.json').exists())
            config, env = prepare_environment(root)
            self.assertEqual(config.read_bytes(), (ENGINE / 'config.default.json').read_bytes())
            self.assertEqual(env.read_bytes(), (ENGINE / '.env.example').read_bytes())

    def test_parallel_prepare_produces_one_run_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / '.sdd-runs/shared'
            command = [sys.executable, str(ENGINE / 'sandbox.py'), 'prepare', '--root', str(root)]
            processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                         for _ in range(3)]
            responses = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
                responses.append(json.loads(stdout))
            self.assertEqual(responses, [responses[0]] * 3)
            self.assertEqual(set(Path(responses[0]['config']).parent.iterdir()),
                             {Path(responses[0]['config']), Path(responses[0]['env_file']),
                              Path(responses[0]['config']).parent / '.prepare.lock',
                              Path(responses[0]['config']).parent / 'manifest.json'})

    def test_partial_write_retries_the_frozen_bundle_after_reference_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve(); source = workspace / '.sdd-migration/harmony'; source.mkdir(parents=True)
            (source / 'config.json').write_text('{"version":1}')
            (source / '.env').write_text('FIXTURE_VERSION=1\n')
            (source / 'config.native.yaml').write_text('version: 1\n')
            root = workspace / '.sdd-runs/first'; folder = root / 'runs/harmony/sandbox/environment'
            original = environment_module.atomic_bytes
            def fail(path, content):
                if path.name == '.env': raise OSError('injected write failure')
                return original(path, content)
            with patch.object(environment_module, 'atomic_bytes', side_effect=fail), self.assertRaises(OSError):
                prepare_environment(root)
            self.assertFalse((folder / 'manifest.json').exists())
            self.assertEqual((folder / 'preparation.json').stat().st_mode & 0o777, 0o600)
            for name in ('config.json', '.env', 'config.native.yaml'): (source / name).unlink()
            config, env = prepare_environment(root)
            self.assertEqual(json.loads(config.read_text())['version'], 1)
            self.assertEqual(env.read_text(), 'FIXTURE_VERSION=1\n')
            self.assertEqual((folder / 'config.native.yaml').read_text(), 'version: 1\n')
            self.assertFalse((folder / 'preparation.json').exists())
            self.assertEqual(json.loads((folder / 'manifest.json').read_text())['status'], 'ready')

    def test_commit_failure_retries_without_replacing_written_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / '.sdd-runs/first'; folder = root / 'runs/harmony/sandbox/environment'
            original = environment_module.atomic_bytes
            def fail(path, content):
                if path.name == 'manifest.json': raise OSError('injected commit failure')
                return original(path, content)
            with patch.object(environment_module, 'atomic_bytes', side_effect=fail), self.assertRaises(OSError):
                prepare_environment(root)
            before = {name: (folder / name).stat().st_mtime_ns for name in ('config.json', '.env')}
            prepare_environment(root)
            self.assertEqual(before, {name: (folder / name).stat().st_mtime_ns for name in before})
            self.assertFalse((folder / 'preparation.json').exists())

    def test_native_absence_is_frozen_and_new_run_can_include_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve(); first = workspace / '.sdd-runs/first'
            config, _ = prepare_environment(first)
            source = workspace / '.sdd-migration/harmony'; source.mkdir(parents=True)
            (source / 'config.native.yaml').write_text('version: 2\n')
            prepare_environment(first)
            self.assertFalse((config.parent / 'config.native.yaml').exists())
            self.assertIsNone(json.loads((config.parent / 'manifest.json').read_text())['files']['config.native.yaml'])
            second, _ = prepare_environment(workspace / '.sdd-runs/second')
            self.assertEqual((second.parent / 'config.native.yaml').read_text(), 'version: 2\n')

    def test_changed_environment_or_partial_output_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / '.sdd-runs/first'
            config, _ = prepare_environment(root)
            config.write_text('{"tampered":true}')
            with self.assertRaisesRegex(ValueError, 'environment changed'): prepare_environment(root)
            self.assertEqual(config.read_text(), '{"tampered":true}')
            (config.parent / 'manifest.json').unlink()
            (config.parent / '.env').unlink()
            with self.assertRaisesRegex(ValueError, 'incomplete legacy environment'): prepare_environment(root)
            self.assertFalse((config.parent / '.env').exists())

    def test_complete_legacy_environment_is_adopted_without_late_native_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve(); root = workspace / '.sdd-runs/legacy'
            folder = root / 'runs/harmony/sandbox/environment'; folder.mkdir(parents=True)
            (folder / 'config.json').write_text('{"version":1}'); (folder / '.env').write_text('FIXTURE=1\n')
            source = workspace / '.sdd-migration/harmony'; source.mkdir(parents=True)
            (source / 'config.native.yaml').write_text('version: 2\n')
            config, _ = prepare_environment(root)
            self.assertEqual(json.loads(config.read_text())['version'], 1)
            self.assertFalse((folder / 'config.native.yaml').exists())
            self.assertTrue((folder / 'manifest.json').exists())

    def test_key_fallback_and_role_override_never_serialize_secrets(self):
        config = json.loads((ENGINE / 'config.default.json').read_text())
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'shared-fixture',
                                     'EXECUTE_MODEL_API_KEY': 'executor-fixture'}, clear=True):
            resolved = resolve_env(config['models'])
            self.assertEqual(resolved['execute_api_key'], 'executor-fixture')
            self.assertEqual(resolved['verify_api_key'], 'shared-fixture')
            self.assertEqual(resolved['decision_models'][0]['api_key'], 'shared-fixture')
            self.assertNotIn('shared-fixture', json.dumps(public_config(resolved)))
            self.assertNotIn('executor-fixture', json.dumps(public_config(resolved)))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'missing environment variable'):
                resolve_env(config['models'])

    def test_default_models_match_reference_and_device_is_not_inherited(self):
        config = json.loads((ENGINE / 'config.default.json').read_text())
        self.assertEqual(config['device'], '')
        self.assertEqual(config['models']['execute_provider'], 'general')
        self.assertEqual(config['models']['decision_models'][0]['name'], 'qwen3.7-plus')
        self.assertEqual(config['models']['xmind_convert_models'][0]['name'], 'deepseek-v4-flash-0731')

    @unittest.skipUnless(importlib.util.find_spec('dotenv'), 'requires sandbox dependencies')
    def test_explicit_env_file_and_process_environment_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / '.env'
            env.write_text('DASHSCOPE_API_KEY=from-file\nVERIFY_MODEL_API_KEY=verify-file\n')
            with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'from-process'}, clear=True):
                sandbox.load_environment(env)
                self.assertEqual(os.environ['DASHSCOPE_API_KEY'], 'from-process')
                self.assertEqual(os.environ['VERIFY_MODEL_API_KEY'], 'verify-file')

    @unittest.skipUnless(importlib.util.find_spec('dotenv'), 'requires sandbox dependencies')
    def test_generated_adapter_runs_from_other_cwd_and_preserves_yellow(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            config = out / 'config.json'; config.write_text('{}')
            env = out / '.env'; env.write_text('DASHSCOPE_API_KEY=fixture-secret\n')
            root = out / '.sdd-runs/standalone'
            adapter = root / 'runs/harmony/sandbox/adapter/adapter.json'
            subprocess.run([sys.executable, str(ENGINE / 'sandbox.py'), 'adapter', '--config', str(config),
                            '--env-file', str(env), '--output', str(adapter)], cwd=out, check=True, capture_output=True)
            data = json.loads(adapter.read_text())
            self.assertIn(str(root.resolve() / 'runs/harmony/sandbox/environment/config.json'), data['argv'])
            self.assertIn(str(root.resolve() / 'runs/harmony/sandbox/environment/.env'), data['argv'])
            # External sources are no longer runtime dependencies after preparation.
            config.unlink(); env.unlink()
            q = out / 'query.json'; q.write_text(json.dumps(query()))
            result = root / 'runs/harmony/automation/attempt/result.json'
            isolated_env = {k: v for k, v in os.environ.items() if k != 'HARMONY_DEVICE'}
            run = subprocess.run([*data['argv'], '--query-file', str(q), '--result-file', str(result)],
                                 cwd=out, env=isolated_env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2, run.stderr)
            report = json.loads(result.read_text())
            self.assertEqual(report['quality'], 'yellow-blocked')
            self.assertEqual(report['producer'], 'harmony-adapter')
            self.assertEqual(report['run_id'], query()['run_id'])
            self.assertNotIn('fixture-secret', result.read_text() + run.stdout + run.stderr + adapter.read_text())
            self.assertTrue((result.parent / 'harmony/observations.json').is_file())

    @unittest.skipUnless(importlib.util.find_spec('agents'), 'requires sandbox dependencies')
    def test_ui_execution_does_not_require_converter_key(self):
        from harmony_adapter import configure
        config = json.loads((ENGINE / 'config.default.json').read_text())['models']
        with patch.dict(os.environ, {'EXECUTE_MODEL_API_KEY': 'e', 'DECISION_MODEL_API_KEY': 'd',
                                     'VERIFY_MODEL_API_KEY': 'v'}, clear=True):
            self.assertEqual(configure(config).execute_api_key, 'e')


if __name__ == '__main__':
    unittest.main()
