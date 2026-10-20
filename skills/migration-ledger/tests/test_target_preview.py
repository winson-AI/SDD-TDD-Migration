"""The device statement says where the target is previewed, platform by platform, and init writes the run's environment
files from it: the visual capture configuration of each previewed platform and the web Main configuration."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, check_ref, read_json
import ledger
import project_context as pc
import test_project_context

DEVICE = {'platforms': ['android', 'web'], 'android': {'serial': 'emulator-5554', 'avd': 'phone', 'boot': {'argv': ['/opt/sdk/emulator/emulator', '-avd', 'phone'], 'timeout_seconds': 300}},
          'web': {'url': 'http://127.0.0.1:8765/', 'viewport': {'width': 1280, 'height': 800}, 'record_video': True}}


class TargetPreviewTests(unittest.TestCase):
    def test_the_statement_names_each_platforms_preview_and_nothing_else(self):
        self.assertEqual(pc.validate({'test_adapter': {'device': DEVICE}})['test_adapter']['device'], DEVICE)
        pc.validate({'test_adapter': {'device': {'platforms': ['harmony'], 'harmony': {'serial': 'hdc-1', 'tool': '/opt/sdk/hdc', 'boot': {'argv': ['/opt/emu'], 'timeout_seconds': 60}}}}})
        for bad, message in (({**DEVICE, 'harmony': {'serial': 'x'}}, 'describes only the platforms it lists'),
                             ({**DEVICE, 'web': {'viewport': {'width': 1, 'height': 1}}}, 'names the url the target is served at'),
                             ({**DEVICE, 'web': {'url': 'ftp://x'}}, 'names the url'),
                             ({**DEVICE, 'web': {'url': 'http://x/', 'browser': 'ie'}}, 'browser is chromium, firefox or webkit'),
                             ({**DEVICE, 'android': {'serial': 'a', 'tool': 'adb'}}, 'tool is the absolute adb'),
                             ({**DEVICE, 'android': {'serial': 'a', 'boot': {'argv': ['emulator']}}}, 'boot takes the absolute argv'),
                             ({'unavailable': 'no farm', 'web': {'url': 'http://x/'}}, 'unavailable gives the reason no device is available')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                pc.validate({'test_adapter': {'device': bad}})

    def test_init_writes_the_environment_files_from_the_statement_and_the_views_point_at_them(self):
        t = test_project_context.ProjectContextTests(); t.setUp(); self.addCleanup(t.doCleanups)
        pc.update(t.root, t.request('device', 1, {'test_adapter': {'device': DEVICE}}), t.actor)
        prepared = t.prepare()
        self.assertEqual(prepared['open_statements'][0]['field'], 'legacy_preview')  # the device statement is answered; the others are not
        t.start(t.init_payload(prepared))
        state = ledger.read_events(t.run)[0]
        refs = state['target_preview']
        self.assertEqual(set(refs['environments']), {'android', 'web'})
        android = read_json(check_ref(refs['environments']['android']))
        self.assertEqual(android['visual_capture'], {'backend': 'adb', 'tool': 'adb', 'device_id': 'emulator-5554', 'avd': 'phone', 'boot': DEVICE['android']['boot']})
        self.assertEqual(android['visual_model'], {'mode': 'external', 'enabled': False})
        web = read_json(check_ref(refs['environments']['web']))
        self.assertEqual(web['visual_capture'], {'backend': 'browser', 'url': 'http://127.0.0.1:8765/', 'device_id': '127.0.0.1:8765', 'viewport': {'width': 1280, 'height': 800}})
        self.assertEqual(read_json(check_ref(refs['web_main_config'])), {'browser': 'chromium', 'headless': True, 'viewport': {'width': 1280, 'height': 800}, 'record_video': True})
        for ref in (*refs['environments'].values(), refs['web_main_config']):
            self.assertTrue(Path(ref['path']).is_relative_to(t.run / 'runs/harmony/sandbox/environment'))
        self.assertEqual(ledger.status(t.run, 'full')['target_preview'], refs)
        self.assertEqual(pc.target_preview_files(t.run, {'platforms': ['android']}), {})  # platforms without a preview leave the host to write


if __name__ == '__main__':
    unittest.main()
