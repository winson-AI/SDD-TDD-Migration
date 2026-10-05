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


def step_evidence(query, output, passed=True):
    """Synthetic observer receipts for host wiring tests; no device/LLM claim."""
    from datetime import datetime, timezone
    from contracts import digest
    trace, observations = {'query_sha256': digest(query), 'steps': []}, []
    media = output / 'synthetic-screen.txt'; media.write_text('mock device observation')
    for number, step in enumerate(query['steps'], 1):
        started = datetime.now(timezone.utc).isoformat()
        action = {'_metadata': 'do', 'action': 'FixtureAction'}
        actions = output / f'synthetic-actions-{number}.json'
        actions.write_text(json.dumps({'events': [
            {'event_type': 'glm_action', 'step_number': 1, 'data': {'action': action}},
            {'event_type': 'glm_step_end', 'step_number': 1, 'data': {'success': True}}]}))
        trace['steps'].append({'step_number': number, 'step_sha256': digest(step), 'status': 'executed',
            'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'before_ref': file_ref(media), 'after_ref': file_ref(media), 'action_ref': file_ref(actions), 'actions': [action]})
        for a in query['expected_assertions']:
            if a['after_step'] == number:
                observations.append({'assertion_ids': [a['assertion_id']], 'after_step': number,
                    'step_sha256': digest(step), 'recorded_at': datetime.now(timezone.utc).isoformat(),
                    'result': passed, 'tool': 'one_image_assert', 'error': None, 'evidence_refs': [file_ref(media)]})
    trace_file = output / 'step-trace.json'; trace_file.write_text(json.dumps(trace))
    obs = output / 'observations.json'; obs.write_text(json.dumps(observations))
    return {'step_contract_version': 1, 'step_trace_ref': file_ref(trace_file), 'observations_ref': file_ref(obs)}


class HarmonyLedgerTests(unittest.TestCase):
    def setUp(self):
        self.f=test_ledger.FlowTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.outputs=self.f.base.resolve()/'.sdd-runs/fixture/runs/harmony/automation'
        original=self.f.plan
        def plan():
            p=original();path=p['paths'][0];path['steps']=['read target value']
            if getattr(self, 'platform', None): path.update(platform=self.platform, task_type='test')
            path['expected_assertions']=[{'assertion_id':'A1','expected':True,'description':'value equals 2',
                                         'matcher':'exact','verification':'one_image_assert','after_step':1}]
            return p
        self.f.plan=plan
        self.f.prepare();self.f.implementation();self.f.assign('test-runner','H1')

    def run_adapter(self, fault=False, report_platform=None, task_type='test', omit_step_proof=False):
        scripts=str(Path(__file__).resolve().parents[2]/'migration-test/scripts')
        script=self.f.base/'fixture_observer.py'
        script.write_text('''import argparse,json,sys,runpy
from pathlib import Path
sys.path.insert(0,'''+repr(scripts)+''')
from harmony_contract import ObservationSink,write,ref,digest
from datetime import datetime,timezone
p=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()
q=json.loads(Path(a.query_file).read_text());out=Path(a.result_file).parent
s=ObservationSink(q,out)
started=datetime.now(timezone.utc).isoformat()
value=runpy.run_path('m1/code.py')['value']
media=out/'fixture-observation.txt';media.write_text(str(value))
action={'_metadata':'do','action':'ReadFixture'}
action_file=out/'fixture-actions.json'
write(action_file,{'events':[{'event_type':'glm_action','step_number':1,'data':{'action':action}},
    {'event_type':'glm_step_end','step_number':1,'data':{'success':True}}]})
s.current_step=1
s.step_trace={'query_sha256':digest(q),'steps':[{'step_number':1,'step_sha256':digest(q['steps'][0]),
    'status':'executed','started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
    'before_ref':ref(media),'after_ref':ref(media),'action_ref':ref(action_file),'actions':[action]}]}
write(out/'step-trace.json',s.step_trace)
s.record('[ASSERT:A1]',value==2,'observed fixture value','one_image_assert',[media])
'''+("s.error='verification tooling failure'\n" if fault else '')+'''
r=s.report()
if q.get('platform'):
    platform = '''+repr(report_platform)+''' or q['platform']
    environment=out/'environment.json'
    write(environment,{'platform':platform,'task_type':''' + repr(task_type) + ''','device':'fixture'})
    r.update(mobile_contract_version=1,platform=platform,task_type=''' + repr(task_type) + ''',environment_ref=ref(environment))
if ''' + repr(omit_step_proof) + ''':
    r.pop('step_contract_version',None);r.pop('step_trace_ref',None)
write(a.result_file,r)
sys.exit(0 if r['quality']=='green-passed' else 2)
''')
        rr=execute(self.f.root,'M001','H1','P1',[sys.executable,str(script)],str(self.f.target),self.outputs/'exec')
        return build(self.f.root,'M001','H1',[rr])

    def test_receipt_stage_ledger_round_trip(self):
        r=self.run_adapter();a=self.f.state()['modules']['M001']['assignments']['H1']
        self.f.submit(r,a);self.f.call('accept',{'assignment_id':'H1'})
        self.f.call('complete',{'dod_ref':self.f.ref('dod.md','all paths reviewed')})
        self.assertEqual(self.f.state()['modules']['M001']['quality'],'green-passed')

    def test_new_attempt_without_explicit_platform_still_requires_step_evidence(self):
        result = self.run_adapter(omit_step_proof=True)
        row = result['paths'][0]
        self.assertEqual(row['quality'], 'yellow-blocked')
        self.assertEqual(row['execution_status'], 'incomplete')
        receipt = json.loads(Path(row['execution_receipt']['path']).read_text())
        self.assertEqual(receipt['execution_contract_version'], 2)
        a = self.f.state()['modules']['M001']['assignments']['H1']
        self.f.submit(result, a); self.f.call('accept', {'assignment_id': 'H1'})

    def test_new_mobile_report_cannot_bypass_normalization(self):
        result = self.run_adapter(omit_step_proof=True)
        result['paths'][0].pop('host_completion_version')
        result['paths'][0]['quality'] = 'green-passed'
        with self.assertRaisesRegex(Rejected, 'normalization'):
            self.f.submit(result, self.f.state()['modules']['M001']['assignments']['H1'])

    def test_historical_receipt_keeps_its_original_interpretation(self):
        from contracts import digest
        from test_completion import interpret
        from unittest.mock import patch
        result = self.run_adapter(omit_step_proof=True)
        receipt = json.loads(Path(result['paths'][0]['execution_receipt']['path']).read_text())
        receipt.pop('execution_contract_version')
        query = json.loads(Path(receipt['query_ref']['path']).read_text())
        query.pop('execution_contract_version'); query.pop('step_contract_version', None)
        report = json.loads(Path(receipt['result_ref']['path']).read_text())
        report['query_sha256'] = digest(query)
        query_path, report_path = receipt['query_ref']['path'], receipt['result_ref']['path']
        def historical(path):
            return query if str(path) == query_path else report if str(path) == report_path else json.loads(Path(path).read_text())
        with patch('test_completion.read_json', side_effect=historical):
            row = interpret(receipt, query)
        self.assertEqual(row['quality'], 'green-passed')
        self.assertNotIn('execution_status', row)

    def test_adapter_yellow_cannot_be_promoted(self):
        r=self.run_adapter(True);a=self.f.state()['modules']['M001']['assignments']['H1']
        r['paths'][0]['quality']='green-passed'
        with self.assertRaises(Rejected):self.f.submit(r,a)

    def test_changed_media_is_rejected_on_submit(self):
        r=self.run_adapter();(self.outputs/'exec/fixture-observation.txt').write_text('tampered')
        a=self.f.state()['modules']['M001']['assignments']['H1']
        with self.assertRaises(Rejected):self.f.submit(r,a)

    def test_timeout_stops_descendant_and_becomes_yellow(self):
        marker=self.f.base/'child-survived'
        script=self.f.base/'spawn.py'
        child="import time;from pathlib import Path;time.sleep(0.8);Path("+repr(str(marker))+").write_text('bad')"
        script.write_text('import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'])\nprint("started",flush=True)\ntime.sleep(20)\n')
        rr=execute(self.f.root,'M001','H1','P1',[sys.executable,str(script)],str(self.f.target),self.outputs/'timeout',timeout=0.2)
        receipt=json.loads(Path(rr['path']).read_text())
        self.assertEqual(receipt['exit_code'],124)
        self.assertIn('started',Path(receipt['log_ref']['path']).read_text())
        r=build(self.f.root,'M001','H1',[rr]);self.assertEqual(r['paths'][0]['quality'],'yellow-blocked')
        time.sleep(0.8);self.assertFalse(marker.exists())
        a=self.f.state()['modules']['M001']['assignments']['H1']
        self.f.submit(r,a);self.f.call('accept',{'assignment_id':'H1'})

    def test_missing_executable_produces_receipt_and_yellow(self):
        rr=execute(self.f.root,'M001','H1','P1',['/nonexistent/sdd-adapter'],str(self.f.target),self.outputs/'unavailable')
        r=build(self.f.root,'M001','H1',[rr]);self.assertEqual(r['paths'][0]['quality'],'yellow-blocked')
        self.assertEqual(json.loads(Path(rr['path']).read_text())['exit_code'],127)

    def test_mobile_deadline_retains_step_receipt_and_raw_media(self):
        scripts = str(Path(__file__).resolve().parents[2] / 'migration-test/scripts')
        script = self.f.base / 'blocked_mobile.py'
        script.write_text('''import argparse,json,sys,time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,''' + repr(scripts) + ''')
from harmony_steps import Deadline
from harmony_contract import write,digest
p=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()
q=json.loads(Path(a.query_file).read_text());out=Path(a.result_file).parent/'harmony'
(out/'temp').mkdir(parents=True)
(out/'temp/raw.mp4').write_bytes(b'raw recording fixture')
write(out/'step-trace.json',{'query_sha256':digest(q),'steps':[{'step_number':1,'status':'running'}]})
deadline=Deadline(SimpleNamespace(output=out,current_step=0),.1)
time.sleep(30)
''')
        rr = execute(self.f.root, 'M001', 'H1', 'P1', [sys.executable, str(script)], str(self.f.target), self.outputs / 'blocked')
        receipt = json.loads(Path(rr['path']).read_text())
        self.assertIn('partial_step_trace_ref', receipt)
        self.assertIn('interruption_ref', receipt)
        self.assertTrue((self.outputs / 'blocked/harmony/temp/raw.mp4').is_file())
        row = build(self.f.root, 'M001', 'H1', [rr])['paths'][0]
        self.assertEqual(row['quality'], 'yellow-blocked')
        self.assertEqual(row['execution_status'], 'incomplete')
        self.assertTrue(row['executed'])


class AndroidLedgerTests(HarmonyLedgerTests):
    platform = 'android'

    def test_wrong_platform_cannot_pass_frozen_android_path(self):
        with self.assertRaisesRegex(Rejected, 'platform mismatch'): self.run_adapter(report_platform='harmony')

    def test_artifact_only_mode_cannot_pass_automation(self):
        with self.assertRaisesRegex(Rejected, 'test mode'): self.run_adapter(task_type='snapshot')

    def test_current_mobile_query_rejects_legacy_report_without_step_proof(self):
        result = self.run_adapter(omit_step_proof=True)
        self.assertEqual(result['paths'][0]['quality'], 'yellow-blocked')
        self.assertIn('step', result['paths'][0]['root_cause']['summary'])


class ExplicitHarmonyLedgerTests(HarmonyLedgerTests):
    platform = 'harmony'
