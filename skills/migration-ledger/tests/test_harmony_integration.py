"""Real host subprocess + Ledger tests; fixture observer is not a device/LLM test."""
import json
from pathlib import Path
import sys
import time
import unittest
import test_ledger

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'migration-test/scripts'))
from harmony_stage import build
from contracts import Rejected, file_ref
from execute_test import execute


class HarmonyLedgerTests(unittest.TestCase):
    def setUp(self):
        self.f=test_ledger.FlowTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        original=self.f.plan
        def plan():
            p=original();path=p['paths'][0];path['steps']=['read target value']
            path['expected_assertions']=[{'assertion_id':'A1','expected':True,'description':'value equals 2',
                                         'matcher':'exact','verification':'one_image_assert','after_step':1}]
            return p
        self.f.plan=plan
        self.f.prepare();self.f.implementation();self.f.assign('test-runner','H1')

    def run_adapter(self, fault=False):
        scripts=str(Path(__file__).resolve().parents[2]/'migration-test/scripts')
        script=self.f.base/'fixture_observer.py'
        script.write_text('''import argparse,json,sys,runpy
from pathlib import Path
sys.path.insert(0,'''+repr(scripts)+''')
from harmony_contract import ObservationSink,write,ref
p=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()
q=json.loads(Path(a.query_file).read_text());out=Path(a.result_file).parent
s=ObservationSink(q,out)
value=runpy.run_path('m1/code.py')['value']
media=out/'fixture-observation.txt';media.write_text(str(value))
s.record('[ASSERT:A1]',value==2,'observed fixture value','one_image_assert',[media])
'''+("s.error='verification tooling failure'\n" if fault else '')+'''
r=s.report();write(a.result_file,r)
sys.exit(0 if r['quality']=='green-passed' else 2)
''')
        rr=execute(self.f.root,'M001','H1','P1',[sys.executable,str(script)],str(self.f.target),self.f.base/'exec')
        return build(self.f.root,'M001','H1',[rr])

    def test_receipt_stage_ledger_round_trip(self):
        r=self.run_adapter();a=self.f.state()['modules']['M001']['assignments']['H1']
        self.f.submit(r,a);self.f.call('accept',{'assignment_id':'H1'})
        self.f.call('complete',{'dod_ref':self.f.ref('dod.md','all paths reviewed'),'checks_passed':True})
        self.assertEqual(self.f.state()['modules']['M001']['quality'],'green-passed')

    def test_adapter_yellow_cannot_be_promoted(self):
        r=self.run_adapter(True);a=self.f.state()['modules']['M001']['assignments']['H1']
        r['paths'][0]['quality']='green-passed'
        with self.assertRaises(Rejected):self.f.submit(r,a)

    def test_changed_media_is_rejected_on_submit(self):
        r=self.run_adapter();(self.f.base/'exec/fixture-observation.txt').write_text('tampered')
        a=self.f.state()['modules']['M001']['assignments']['H1']
        with self.assertRaises(Rejected):self.f.submit(r,a)

    def test_timeout_stops_descendant_and_becomes_yellow(self):
        marker=self.f.base/'child-survived'
        script=self.f.base/'spawn.py'
        child="import time;from pathlib import Path;time.sleep(0.8);Path("+repr(str(marker))+").write_text('bad')"
        script.write_text('import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'])\nprint("started",flush=True)\ntime.sleep(20)\n')
        rr=execute(self.f.root,'M001','H1','P1',[sys.executable,str(script)],str(self.f.target),self.f.base/'timeout',timeout=0.2)
        receipt=json.loads(Path(rr['path']).read_text())
        self.assertEqual(receipt['exit_code'],124)
        self.assertIn('started',Path(receipt['log_ref']['path']).read_text())
        r=build(self.f.root,'M001','H1',[rr]);self.assertEqual(r['paths'][0]['quality'],'yellow-blocked')
        time.sleep(0.8);self.assertFalse(marker.exists())
        a=self.f.state()['modules']['M001']['assignments']['H1']
        self.f.submit(r,a);self.f.call('accept',{'assignment_id':'H1'})

    def test_missing_executable_produces_receipt_and_yellow(self):
        rr=execute(self.f.root,'M001','H1','P1',['/nonexistent/sdd-adapter'],str(self.f.target),self.f.base/'unavailable')
        r=build(self.f.root,'M001','H1',[rr]);self.assertEqual(r['paths'][0]['quality'],'yellow-blocked')
        self.assertEqual(json.loads(Path(rr['path']).read_text())['exit_code'],127)
