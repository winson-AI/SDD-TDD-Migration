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

spec = importlib.util.spec_from_file_location('sandbox', ENGINE / 'sandbox.py')
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)


class SandboxTests(unittest.TestCase):
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
            adapter = out / 'adapter.json'
            subprocess.run([sys.executable, str(ENGINE / 'sandbox.py'), 'adapter', '--config', str(config),
                            '--env-file', str(env), '--output', str(adapter)], cwd=out, check=True, capture_output=True)
            data = json.loads(adapter.read_text())
            q = out / 'query.json'; q.write_text(json.dumps(query()))
            result = out / 'result.json'
            isolated_env = {k: v for k, v in os.environ.items() if k != 'HARMONY_DEVICE'}
            run = subprocess.run([*data['argv'], '--query-file', str(q), '--result-file', str(result)],
                                 cwd=out, env=isolated_env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2, run.stderr)
            report = json.loads(result.read_text())
            self.assertEqual(report['quality'], 'yellow-blocked')
            self.assertEqual(report['producer'], 'harmony-adapter')
            self.assertEqual(report['run_id'], query()['run_id'])
            self.assertNotIn('fixture-secret', result.read_text() + run.stdout + run.stderr + adapter.read_text())
            self.assertTrue((out / 'harmony/observations.json').is_file())

    @unittest.skipUnless(importlib.util.find_spec('agents'), 'requires sandbox dependencies')
    def test_ui_execution_does_not_require_converter_key(self):
        from harmony_adapter import configure
        config = json.loads((ENGINE / 'config.default.json').read_text())['models']
        with patch.dict(os.environ, {'EXECUTE_MODEL_API_KEY': 'e', 'DECISION_MODEL_API_KEY': 'd',
                                     'VERIFY_MODEL_API_KEY': 'v'}, clear=True):
            self.assertEqual(configure(config).execute_api_key, 'e')


if __name__ == '__main__':
    unittest.main()
