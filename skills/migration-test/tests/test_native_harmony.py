"""Native integration with fake device/model I/O; requires the real engine dependencies."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from harmony_adapter import ENGINE, run_engine
from harmony_contract import ObservationSink
from test_harmony import query
from runner_storage import scope


@unittest.skipUnless(importlib.util.find_spec('agents') and importlib.util.find_spec('hypium'), 'native runtime dependencies unavailable')
class NativeIntegrationTests(unittest.TestCase):
    def test_native_decision_reporting_and_observer_wiring(self):
        sys.path.insert(0,str(ENGINE))
        from AutoTest.layered_agent_cli.agent_registry import agent_registry
        from AutoTest.verify_agent.agent import VerifyAgent
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp).resolve()/'.sdd-runs/test/runs/harmony/automation/attempt'
            out.mkdir(parents=True);sink=ObservationSink(query(),out)
            media=out/'screen.png';media.write_bytes(b'fake device fixture')
            class Device:
                def __init__(self,*args,**kwargs):pass
                def teardown(self):pass
            async def runner(*args,**kwargs):
                verifier=agent_registry.get_verify_agent()
                verifier.verify('[ASSERT:A1]')
                return SimpleNamespace(final_output='任务结果: 通过')
            config={'device':'fixture','models':{'decision_models':[{'name':'fixture','base_url':'https://example.invalid','api_key':'unused'}],
                                                'execute_model_name':'fixture','execute_provider':'general','verify_model_name':'fixture'}}
            old=Path.cwd()
            try:
                os.chdir(out)
                with scope(out), patch('AutoTest.devices.hdc_device.HDCDevice',Device), \
                     patch('AutoTest.layered_agent_cli.decision.create_planner_agent',return_value=SimpleNamespace(name='fixture')), \
                     patch('AutoTest.layered_agent_cli.decision.Runner.run',side_effect=runner), \
                     patch.object(VerifyAgent,'_verify',return_value=(True,'通过','one_image_assert',[str(media)])):
                    result=asyncio.run(run_engine(query(),config,out,sink))
                self.assertIn('通过',result)
                self.assertEqual(sink.report()['quality'],'green-passed')
                self.assertTrue(list((out/'reports').glob('*.html')))
                self.assertTrue(list((out/'reports').glob('*.json')))
                self.assertTrue(list((out/'memory').glob('*.json')))
            finally:os.chdir(old)

    def test_video_failure_keeps_original_and_does_not_raise_cleanup_error(self):
        sys.path.insert(0,str(ENGINE))
        from AutoTest.verify_agent.verify_tools import video_assert_tool
        from AutoTest.config import AppConfig
        cfg=AppConfig(keep_raw_video=True)
        passed,reason=video_assert_tool('predicate',1,2,video_path=None,config=cfg)
        self.assertFalse(passed);self.assertIn('not found',reason)
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'merged_video_fixture.mp4';video.write_bytes(b'fixture')
            passed,reason=video_assert_tool('predicate',2,1,video_path=str(video),config=cfg)
            self.assertFalse(passed);self.assertTrue(video.exists())

    def test_xmind_all_sheets_retained(self):
        sys.path.insert(0,str(ENGINE))
        import json,zipfile
        from AutoTest.testcase_preprocessor.xmind_parser import extract_tree
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'cases.xmind'
            with zipfile.ZipFile(source,'w') as z:
                z.writestr('content.json',json.dumps([{'rootTopic':{'title':'first'}},{'rootTopic':{'title':'second'}}]))
            text=extract_tree(str(source))
            self.assertIn('first',text);self.assertIn('second',text)
