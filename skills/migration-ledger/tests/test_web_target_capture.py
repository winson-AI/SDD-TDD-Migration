"""A web target is not installed: the host deploys the accepted build and the served page declares its hash; the worker
reads that declaration, walks the frozen clicks and captures the page as a web-candidate record the pipeline compares."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, file_ref, read_json
import lean_visual_worker as worker
import test_lean_visual_worker as base
import test_legacy_capture
import visual_evidence
from lean_tools import validate_manifest

HOST = '127.0.0.1:8765'


class TargetPage(test_legacy_capture.FakePage):
    """The served target: a page that says which build it is."""
    def __init__(self, png, build):
        super().__init__(png); self.text, self.build = 'Home', build

    def identity(self): self.calls.append(('identity',)); return self.build


class WebTargetTests(unittest.TestCase):
    def setUp(self):
        self.t = t = base.VisualExecutionTests(); t.setUp(); self.addCleanup(t.doCleanups)
        env = t.write('runs/harmony/sandbox/environment/visual-web.json', {
            'visual_capture': {'backend': 'browser', 'url': 'http://' + HOST + '/', 'device_id': HOST, 'viewport': {'width': 1280, 'height': 800}},
            'visual_model': {'mode': 'external', 'enabled': False, 'name': 'vision-test', 'base_url': 'https://model.example/v1', 'api_key_env': 'SDD_TEST_VISION_KEY'}})
        self.bundle = t.write('runs/build/build-1/dist.zip', b'web-bundle-bytes')
        self.sha = hashlib.sha256(b'web-bundle-bytes').hexdigest()
        t.path['visual_execution'].update(environment_ref=file_ref(env), app_id=HOST, url='http://' + HOST + '/home')
        t.module['build_artifacts'] = [file_ref(self.bundle)]; t.args['artifact_ref'] = file_ref(self.bundle)
        t.actor['device_lock']['device_id'] = HOST
        self.page = TargetPage(t.image('PNG'), self.sha); self.viewports = []
        self.open = patch.object(worker, 'open_browser', lambda out, viewport=None: (self.viewports.append(viewport), self.page)[1]); self.open.start(); self.addCleanup(self.open.stop)

    def run_tool(self, operation, **extra):
        t = self.t; out = t.sandbox / 'test-1' / f'web-{len(list(t.sandbox.glob("test-1/*")))}'; out.mkdir(parents=True)
        result = worker.run(operation, {**t.args, **extra}, root=t.root, out=out, module=t.module, task=t.task, actor=t.actor, config={})
        return result, worker.save(out / 'result.json', result)

    def test_the_served_page_declares_the_accepted_build_and_is_captured_as_a_web_candidate(self):
        install, install_ref = self.run_tool('visual-install')
        self.assertEqual((install['status'], install['artifact_identity']['sha256'], install['installed_metadata']['url'], install['device_id'], install['app_id']),
                         ('INSTALLED', self.sha, 'http://' + HOST + '/home', HOST, HOST))
        self.assertEqual(self.viewports, [{'width': 1280, 'height': 800}])
        result, _ = self.run_tool('visual-capture', install_ref=install_ref, round=1, reference_manifest_ref=file_ref(self.t.manifest))
        self.assertEqual(result['status'], 'CAPTURED', result)
        record = read_json(result['manifest_ref']['path'])['targets'][-1]
        self.assertEqual((record['phase'], record['platform'], record['round'], record['snapshot']['device_backend']['name'], record['snapshot']['device_backend']['device']),
                         ('web-candidate', 'web', 1, 'playwright', HOST))
        self.assertTrue(visual_evidence.is_candidate(record))
        validate_manifest.validate_snapshot(record['snapshot'], 'viewport', 'candidate')
        execution = read_json(result['capture_execution_ref']['path'])
        self.assertTrue(execution['observations'] and execution['app_id'] == HOST)
        self.assertEqual(read_json(record['snapshot']['meta'])['artifact_identity']['kind'], 'meta[name=sdd-build]')
        self.assertIn(('goto', 'http://' + HOST + '/home'), self.page.calls); self.assertIn(('identity',), self.page.calls)
        self.page.text = 'Elsewhere'
        again, _ = self.run_tool('visual-capture', install_ref=install_ref, round=2, reference_manifest_ref=file_ref(self.t.manifest))
        self.assertEqual((again['status'], again['root_cause']['reason']), ('BLOCKED', 'frozen target selectors not observed'))

    def test_a_page_that_declares_another_build_or_another_host_is_refused(self):
        self.page.build = 'f' * 64
        install, _ = self.run_tool('visual-install')
        self.assertEqual((install['status'], install['root_cause']['kind']), ('BLOCKED', 'artifact-identity-unverified'))
        self.page.build = self.sha
        install, install_ref = self.run_tool('visual-install')
        self.assertEqual(install['status'], 'INSTALLED')
        self.page.build = ''  # redeployed with something else before the capture
        result, _ = self.run_tool('visual-capture', install_ref=install_ref, round=1, reference_manifest_ref=file_ref(self.t.manifest))
        self.assertEqual((result['status'], result['root_cause']['kind']), ('BLOCKED', 'artifact-identity-unverified'))
        self.t.path['visual_execution']['url'] = 'http://other.example:1/x'
        with self.assertRaisesRegex(Rejected, 'url served at its app_id host'):
            self.run_tool('visual-install')


if __name__ == '__main__':
    unittest.main()
