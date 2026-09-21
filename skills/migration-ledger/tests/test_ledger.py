import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, baseline, digest, file_ref
import ledger
from execute_test import execute
import audit_code_review


def code_review(f, findings=None, recovery_resolutions=None):
    """An explicit independent review fixture; no automatic Ledger gate bypass."""
    s = f.state()
    if findings is None and audit_code_review.current(s):
        return
    proof = f.ref(f'code-review-evidence-{f.n}.md', 'Reviewed fixture before/after code, production binding, reuse and fidelity.')
    items = findings or []
    report = {'schema_version': 1, 'run_id': s['run_id'], 'auditor_instance_id': 'auditor',
              'change_inventory_ref': f.ref(f'change-inventory-{f.n}.md', 'Fixture R1 / T1 -> code.py -> C1 / P1; frozen diff and consumer impact reviewed.'),
              'snapshot': audit_code_review.snapshot(s), 'findings': items, 'recovery_resolutions': recovery_resolutions or [],
              'modules': [{'module_id': mid, 'diff_refs': [proof], 'checks': {
                  c: {'conclusion': 'finding' if any(x['source_module_id'] == mid and x['category'] == c for x in items) else 'satisfied',
                      'reason': 'Inspected small fixture implementation', 'evidence_refs': [proof]} for c in audit_code_review.CHECKS}}
                  for mid in s['modules']]}
    f.call('audit-code-review', {'report_ref': f.ref(f'code-review-{f.n}.json', report)}, role='auditor', module=None)



class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.target = self.base / 'target'; self.target.mkdir()
        self.legacy = self.base / 'legacy'; self.legacy.mkdir()
        self.root = self.base / 'run'
        self.n = 0
        self.call('init', {'dimension_slicing_required': False, 'split_testing_required': False, 'context_readiness_required': False, 'target_root': str(self.target), 'legacy_root': str(self.legacy),
                          'case_ids': ['C1'], 'requirement_ids': ['R1'],
                          'global_spec': self.ref('global-spec.md', 'R1 spec'), 'new_architecture': self.ref('architecture.md', 'target architecture'), 'global_paths': [{'path_id': 'GP1', 'case_id': 'C1', 'expected_assertions': [{'assertion_id': 'A1', 'expected': 2}]}], 'max_fix_rounds': 1}, role='host')
        self.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [],
                              'write_paths': [str(self.target / 'm1')]}, role='global-orchestrator', module=None)

    def ref(self, name, content):
        p = self.base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(content) if not isinstance(content, str) else content)
        return file_ref(p)

    def state(self):
        return ledger.status(self.root)

    def call(self, op, payload=None, role='module-orchestrator', module='M001', instance=None, request=None):
        self.n += 1
        s = ledger.read_events(self.root)[0]
        if op == 'init': module = None
        rev = (s['modules'][module]['revision'] if module else s['revision']) if s else 0
        req = request or {'schema_version': 1, 'request_id': str(self.n), 'run_id': 'demo',
                          'module_id': module, 'expected_revision': rev, 'operation': op, 'payload': payload or {}}
        return ledger.apply(self.root, req, {'role': role, 'instance_id': instance or role})

    def plan(self):
        contents = {'spec': '## ADDED Requirements\n### Requirement: R1\nSystem SHALL return the result.\n#### Scenario: normal\nWHEN invoked THEN return result.\n', 'tasks': '- [ ] T1 implement R1\n', 'checklist': '- [ ] Review definitions\n'}
        definitions = [{**self.ref(f'defs/{k}.md', contents.get(k, k)), 'kind': k} for k in
                       ('proposal', 'spec', 'design', 'tasks', 'checklist', 'test-design', 'global-contract')]
        evidence = self.ref('source.txt', 'entry -> repository -> production -> observable result')
        return {'schema_version': 1, 'module_id': 'M001', 'definitions': definitions,
                'paths': [{'path_id': 'P1', 'name': 'normal', 'case_id': 'C1', 'requirement_id': 'R1', 'required': True,
                           'expected_assertions': [{'assertion_id': 'A1', 'expected': 2}]}],
                'tasks': [{'task_id': 'T1', 'requirement_ids': ['R1'], 'path_ids': ['P1']}],
                'source_closure': {'entry': 'entry', 'execution_chain': ['handler', 'repository'],
                                   'observable_result': 'result', 'production_binding': 'binding',
                                   'evidence_refs': [evidence], 'unresolved': []},
                'target_feasibility': {'verdict': 'ready', 'evidence_refs': [evidence]},
                'decision_envelope': {'scope': ['feature'], 'acceptance': ['R1'], 'allowed_alternatives': [],
                                      'forbidden_changes': ['reduce-scope']}, 'freeze_checks_passed': True}

    def attach_reuse(self, plan):
        import reuse
        sources = reuse.sources(self.state())
        catalog = {'schema_version': 1, 'sources': sources, 'capabilities': [],
                   'source_reviews': [{'source_id': s['source_id'], 'status': 'reviewed',
                     'scanned_paths': s['module_paths'], 'conclusion': 'no equivalent behavior in fixture',
                     'evidence_refs': [self.ref('reuse-search.md', 'Reviewed target empty implementation and architecture')]} for s in sources]}
        plan['reuse_plan_ref'] = self.ref('reuse-'+plan['module_id']+'.json', {
            'schema_version': 1, 'module_id': plan['module_id'],
            'catalog_ref': self.ref('reuse-catalog.json', catalog),
            'mappings': [{'mapping_id': 'MAP1', 'requirement_ids': ['R1'],
                          'task_ids': ['T1'], 'path_ids': [plan['paths'][0]['path_id']],
                          'capability_id': None, 'decision': 'new', 'rationale': 'no candidate exists',
                          'behavior_delta': 'implement R1', 'binding_plan': 'production entry',
                          'verification': 'existing acceptance asserts R1'}]})
        return plan

    def global_plan(self):
        state = self.state()
        plan = {'global_spec': state['global_spec'], 'new_architecture': state['new_architecture'],
                'boundary_review': {'issues': []},
                'requirement_owners': {'R1': list(state['modules'])},
                'case_owners': {'C1': list(state['modules']) + (['GLOBAL'] if state['global_paths'] else [])}}
        if state.get('context_readiness_required'):
            evidence = self.ref('feature-discovery.md', 'Reviewed legacy entry and complete R1 behavior in fixture')
            inventory = {'schema_version': 1, 'legacy_root': state['legacy_root'], 'entry_mode': state['entry_mode'],
                'single_module_id': state.get('single_module_id'), 'source_mode': 'legacy-source', 'test_summary_ref': None,
                'features': [{'feature_id': 'F1', 'name': 'fixture behavior', 'functional_path': 'Feature/Result',
                    'trigger': 'invoke', 'observable_result': 'result', 'requirement_ids': ['R1'], 'case_ids': ['C1'], 'evidence_refs': [evidence]}],
                'source_units': [{'unit_id': 'U1', 'kind': 'legacy-entry', 'locator': state['legacy_root'], 'feature_ids': ['F1'], 'evidence_refs': [evidence]}],
                'coverage': {'status': 'complete', 'unclassified': [], 'unresolved_questions': []}, 'questions': []}
            plan['feature_inventory_ref'] = self.ref(f'feature-inventory-{self.n}.json', inventory)
            plan['feature_owners'] = {'F1': list(state['modules'])}
        self.call('global-plan', {'plan_ref': self.ref(f'global-plan-{self.n}.json', plan), 'review_ref': self.ref('coverage.md', 'all covered')},
                  role='global-orchestrator', module=None)

    def prepare(self):
        self.global_plan()
        plan = self.plan()
        self.call('plan', {'plan_ref': self.ref('plan.json', plan)}, role='spec-designer')
        self.approve(digest(plan), 'D1')
        self.call('freeze', {'decision_id': 'D1'})

    def approve(self, subject, did):
        self.call('decision', {'decision_id': did, 'decision': 'approved', 'module_id': 'M001',
                              'subject_sha256': subject, 'human_source_ref': self.ref(f'{did}.txt', 'user approved exact subject')},
                  role='host', module=None)

    def assign(self, role, aid):
        self.call('assign', {'assignment_id': aid, 'role': role, 'instance_id': role})
        return self.state()['modules']['M001']['assignments'][aid]

    def submit(self, result, a):
        self.call('submit', {'assignment_id': a['assignment_id'], 'fencing_token': a['fencing_token'],
                             'result_ref': self.ref(f'result-{self.n}.json', result)}, role=a['role'])

    def implementation(self, role='implementer', aid='I1'):
        a = self.assign(role, aid)
        source = self.target / 'm1/code.py'; source.parent.mkdir(exist_ok=True)
        source.write_text('value = 2\n' if role == 'implementer' else 'value = 3\n')
        refs = [file_ref(source)]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
                  'assignment_id': aid, 'actor_instance_id': role, 'freeze_id': a['freeze_id'],
                  'code_files': refs, 'code_baseline': baseline(refs),
                  'task_trace': [{'task_id': 'T1', 'files': [str(source)]}],
                  'production_binding_evidence': self.ref('binding.txt', 'real binding reviewed')}
        if role == 'fixer':
            result['fix_note_ref'] = self.ref(f'fix-note-{aid}.json', {'root_cause': 'code mismatch', 'strategy': 'minimal correction', 'applicability': 'same contract and cause', 'risks': 'verify integrations'})
        self.submit(result, a)
        self.call('accept', {'assignment_id': aid})

    def make_test_result(self, aid='TEST1', quality='green-passed', previous=None):
        a = self.assign('test-runner', aid)
        adapter = self.base / 'adapter.py'
        adapter.write_text('''import argparse,json
p=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()
json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':2,'passed':True}]},open(a.result_file,'w'))
''')
        if quality == 'red-bug':
            adapter.write_text(adapter.read_text().replace("'actual':2,'passed':True", "'actual':1,'passed':False"))
        receipt_ref = execute(self.root, 'M001', aid, 'P1', [sys.executable, str(adapter)], str(self.target),
                              self.base / f'exec-{aid}')
        receipt = json.loads(Path(receipt_ref['path']).read_text())
        assertion = json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']
        record = {'path_id': 'P1', 'test_run_id': receipt['test_run_id'], 'quality': quality, 'executed': True,
                  'execution_receipt': receipt_ref, 'assertions': assertion, 'retest_of': previous}
        if quality != 'green-passed':
            record['root_cause'] = {'category': 'code', 'summary': 'observed issue', 'confidence': 'suspected',
                                    'owner': 'M001', 'next_action': 'diagnose'}
        result = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'M001',
                  'assignment_id': aid, 'actor_instance_id': 'test-runner', 'freeze_id': a['freeze_id'],
                  'code_baseline': a['code_baseline'], 'paths': [record]}
        return a, result

    def test_green_flow_and_independent_global_audit(self):
        self.prepare(); self.implementation()
        a, result = self.make_test_result()
        self.submit(result, a); self.call('accept', {'assignment_id': a['assignment_id']})
        self.call('complete', {'dod_ref': self.ref('dod.md', 'all reviewed'), 'checks_passed': True})
        self.assertEqual(self.state()['modules']['M001']['quality'], 'green-passed')
        self.assertEqual(self.state()['quality'], 'yellow-blocked')
        with self.assertRaises(Rejected):
            self.call('audit-assign', {'assignment_id': 'AUDIT', 'instance_id': 'implementer'}, role='global-orchestrator', module=None)
        code_review(self)
        self.call('audit-assign', {'assignment_id': 'AUDIT', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        scope = ledger.audit_scope(self.state())
        rr = execute(self.root, 'GLOBAL', 'AUDIT', 'GP1', [sys.executable, str(self.base / 'adapter.py')],
                     str(self.target), self.base / 'global-exec')
        receipt = json.loads(Path(rr['path']).read_text())
        assertions = json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']
        report = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'GLOBAL',
                  'assignment_id': 'AUDIT', 'actor_instance_id': 'auditor',
                  'freeze_id': scope['freeze_id'], 'code_baseline': scope['code_baseline'],
                  'snapshot': {'M001': self.state()['modules']['M001']['code_baseline']},
                  'paths': [{'path_id': 'GP1', 'quality': 'green-passed', 'executed': True,
                             'test_run_id': receipt['test_run_id'], 'execution_receipt': rr, 'assertions': assertions}]}
        self.assertEqual([p['path_id'] for p in scope['plan']['paths']], ['GP1'])
        with self.assertRaisesRegex(Rejected, 'outside collected audit scope'):
            execute(self.root, 'GLOBAL', 'AUDIT', 'P1', [sys.executable, str(self.base / 'adapter.py')],
                    str(self.target), self.base / 'must-not-replay-green')
        self.call('audit', {'report_ref': self.ref('audit.json', report)}, role='auditor', module=None)
        self.assertEqual(self.state()['quality'], 'green-passed')

    def test_unfrozen_code_and_precode_test_rejected(self):
        with self.assertRaises((Rejected, TypeError)): self.assign('implementer', 'I1')
        self.prepare()
        with self.assertRaises(Rejected): self.assign('test-runner', 'TEST1')

    def test_approval_bound_to_content(self):
        plan = self.plan(); self.call('plan', {'plan_ref': self.ref('plan.json', plan)}, role='spec-designer')
        self.approve('wrong', 'D1')
        with self.assertRaises(Rejected): self.call('freeze', {'decision_id': 'D1'})

    def test_empty_assertions_and_forged_receipt_rejected(self):
        self.prepare(); self.implementation(); a, r = self.make_test_result()
        r['paths'][0]['assertions'] = []
        with self.assertRaises(Rejected): self.submit(r, a)

    def test_changed_code_invalidates_submission(self):
        self.prepare(); self.implementation(); a, r = self.make_test_result()
        (self.target / 'm1/code.py').write_text('modified')
        with self.assertRaises(Rejected): self.submit(r, a)

    def test_worker_cannot_accept_or_edit_spec(self):
        self.prepare()
        with self.assertRaises(Rejected): self.call('change', {}, role='fixer')
        with self.assertRaises(Rejected): self.call('complete', {}, role='implementer')

    def test_duplicate_and_stale_revision(self):
        s = self.state()
        req = {'schema_version': 1, 'request_id': 'same', 'run_id': 'demo', 'module_id': 'M001',
               'expected_revision': s['modules']['M001']['revision'], 'operation': 'session',
               'payload': {'role': 'implementer', 'session_id': 'S1'}}
        first = self.call('session', request=req)
        second = self.call('session', request=req)
        self.assertTrue(second['duplicate']); self.assertEqual(first['event_id'], second['event_id'])
        bad = copy.deepcopy(req); bad['payload']['session_id'] = 'other'
        with self.assertRaises(Rejected): self.call('session', request=bad)
        bad = copy.deepcopy(req); bad['request_id'] = 'new'
        with self.assertRaises(Rejected): self.call('session', request=bad)

    def test_projection_loss_and_post_commit_crash_replay(self):
        with patch.object(ledger, 'project', side_effect=OSError('crash')):
            with self.assertRaises(OSError): self.call('session', {'role': 'implementer', 'session_id': 'S1'})
        (self.root / 'ledger/global.json').write_text('{"quality":"green-passed"}')
        self.assertEqual(self.state()['modules']['M001']['sessions']['implementer']['session_id'], 'S1')
        self.assertEqual(self.state()['quality'], 'yellow-blocked')

    def test_journal_corruption_stops(self):
        with (self.root / 'ledger/events.jsonl').open('a') as f: f.write('{')
        with self.assertRaises(Rejected): self.state()

    def test_session_cold_recovery_requires_checkpoint(self):
        self.call('session', {'role': 'fixer', 'session_id': 'S1'})
        with self.assertRaises(Rejected): self.call('session', {'role': 'fixer', 'session_id': 'S2'})
        self.call('session', {'role': 'fixer', 'session_id': 'S2', 'reason': 'session-unavailable',
                              'checkpoint_ref': self.ref('checkpoint.json', {'phase': 'context'})})

    def test_no_silent_source_only_completion(self):
        self.prepare(); self.implementation()
        a = self.assign('test-runner', 'TEST1')
        r = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'M001',
             'assignment_id': 'TEST1', 'actor_instance_id': 'test-runner', 'freeze_id': a['freeze_id'],
             'code_baseline': a['code_baseline'], 'paths': [{'path_id': 'P1', 'test_run_id': 'unexecuted-1',
             'executed': False, 'quality': 'yellow-blocked', 'root_cause': {'category': 'source-only',
             'summary': 'no runtime proof', 'confidence': 'confirmed', 'owner': 'host', 'next_action': 'provide device'}}]}
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        with self.assertRaises(Rejected): self.call('complete', {'checks_passed': True})

    def test_overlap_and_unknown_dependency_rejected(self):
        with self.assertRaises(Rejected):
            self.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M003'],
                                  'write_paths': [str(self.target / 'm2')]}, role='global-orchestrator', module=None)
        self.prepare(); self.assign('implementer', 'I1')
        self.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': [],
                              'write_paths': [str(self.target / 'm1/sub')]}, role='global-orchestrator', module=None)
        plan = self.plan(); plan['module_id'] = 'M002'
        plan['paths'][0]['path_id'] = 'P2'; plan['tasks'][0]['path_ids'] = ['P2']
        self.call('plan', {'plan_ref': self.ref('p2.json', plan)}, role='spec-designer', module='M002')
        self.call('decision', {'decision_id': 'D2', 'decision': 'approved', 'module_id': 'M002',
                              'subject_sha256': digest(plan), 'human_source_ref': self.ref('d2.txt', 'approved')}, role='host', module=None)
        self.call('freeze', {'decision_id': 'D2'}, module='M002')
        with self.assertRaises(Rejected): self.call('assign', {'assignment_id': 'I2', 'role': 'implementer',
                                                             'instance_id': 'other'}, module='M002')

    def test_inside_envelope_task_revision_and_outside_acceptance(self):
        self.prepare()
        cr = {'request_ref': self.ref('cr.md', 'task refinement'), 'impact_ref': self.ref('impact.md', 'no semantic change')}
        self.call('change', cr)
        plan = self.plan(); plan['tasks'][0]['description'] = 'refined plan'
        self.call('plan', {'plan_ref': self.ref('p2.json', plan)}, role='spec-designer')
        self.call('freeze', {'change_class': 'within-envelope', 'impact_ref': cr['impact_ref']})
        self.call('change', cr)
        plan['paths'][0]['expected_assertions'][0]['expected'] = 9
        self.call('plan', {'plan_ref': self.ref('p3.json', plan)}, role='spec-designer')
        with self.assertRaises(Rejected): self.call('freeze', {'change_class': 'within-envelope', 'impact_ref': cr['impact_ref']})

    def test_non_green_retest_chain_required(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result(quality='yellow-blocked')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        a2, r2 = self.make_test_result(aid='TEST2')
        with self.assertRaises(Rejected): self.submit(r2, a2)
        r2['paths'][0]['retest_of'] = r['paths'][0]['test_run_id']
        self.submit(r2, a2)

    def test_fix_budget_not_reset_and_recover_requires_scoped_decision(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result(quality='yellow-blocked')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        self.call('diagnose', {'diagnosis_ref': self.ref('diag.md', 'root cause'), 'owner': 'fixer',
                               'root_cause': 'implementation'}, role='diagnostician')
        self.call('diagnosis-accept')
        self.implementation(role='fixer', aid='FIX1')
        a2, r2 = self.make_test_result(aid='TEST2', quality='yellow-blocked', previous=r['paths'][0]['test_run_id'])
        self.submit(r2, a2); self.call('accept', {'assignment_id': 'TEST2'})
        self.call('diagnose', {'diagnosis_ref': self.ref('diag2.md', 'root cause'), 'owner': 'fixer',
                               'root_cause': 'implementation'}, role='diagnostician')
        self.call('diagnosis-accept')
        with self.assertRaises(Rejected): self.assign('fixer', 'FIX2')
        m = self.state()['modules']['M001']
        subject = digest({'module_id': 'M001', 'revision': m['revision'], 'recovery_cycle': 0, 'additional_rounds': 1})
        self.approve(subject, 'RECOVER')
        self.call('recover', {'decision_id': 'RECOVER', 'additional_rounds': 1})
        m = self.state()['modules']['M001']
        self.assertEqual(m['total_fix_rounds'], 1)
        self.assertEqual(m['fix_rounds_used'], 1)
        self.assertEqual(m['recovery_cycle'], 1)

    def test_dependency_requires_global_release_and_does_not_turn_green(self):
        self.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M001'],
                              'write_paths': [str(self.target / 'm2')]}, role='global-orchestrator', module=None)
        self.call('suspend', {'kind': 'dependency', 'reason': 'M001 pending', 'root_cause': 'missing producer',
                              'owner': 'global-orchestrator'}, module='M002')
        with self.assertRaises(Rejected): self.call('resume', module='M002')
        self.prepare(); self.implementation()
        a, result = self.make_test_result()
        self.submit(result, a); self.call('accept', {'assignment_id': 'TEST1'})
        self.call('complete', {'dod_ref': self.ref('dod.md', 'all reviewed'), 'checks_passed': True})
        with self.assertRaises(Rejected): self.call('resume', module='M002')
        self.call('dependency-ready', role='global-orchestrator', module='M002')
        self.call('resume', module='M002')
        self.assertEqual(self.state()['modules']['M002']['phase'], 'context')
        self.assertEqual(self.state()['modules']['M002']['quality'], 'yellow-blocked')

    def test_parallel_cas_has_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        req = {'schema_version': 1, 'request_id': 'race1', 'run_id': 'demo', 'module_id': 'M001',
               'expected_revision': 0, 'operation': 'session', 'payload': {'role': 'fixer', 'session_id': 'S1'}}
        other = copy.deepcopy(req); other['request_id'] = 'race2'
        def send(r):
            try:
                ledger.apply(self.root, r, {'role': 'module-orchestrator', 'instance_id': 'MO'})
                return True
            except Rejected:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, [req, other]))
        self.assertEqual(sorted(results), [False, True])

    def test_revoked_worker_cannot_submit(self):
        self.prepare(); a = self.assign('implementer', 'I1')
        self.call('revoke', {'assignment_id': 'I1', 'stopped_worker_ref': self.ref('stop.txt', 'host terminated worker')}, role='host')
        with self.assertRaises(Rejected): self.call('submit', {'assignment_id': 'I1', 'fencing_token': a['fencing_token']}, role='implementer')

    def test_no_automatic_human_resume(self):
        self.call('suspend', {'kind': 'human', 'reason': 'need decision', 'root_cause': 'ambiguous input', 'owner': 'human'})
        with self.assertRaises(Rejected): self.call('resume')
        blocked = self.state()['modules']['M001']['blocked']
        self.approve(digest(blocked), 'RESUME')
        self.call('resume', {'decision_id': 'RESUME'})
        self.assertEqual(self.state()['modules']['M001']['phase'], 'context')

    def test_flaky_and_missing_paths_rejected(self):
        self.prepare(); self.implementation(); a, result = self.make_test_result()
        result['paths'][0]['flaky'] = True
        with self.assertRaises(Rejected): self.submit(result, a)
        result['paths'] = []
        with self.assertRaises(Rejected): self.submit(result, a)

    def test_raw_report_tampering_rejected(self):
        self.prepare(); self.implementation(); a, result = self.make_test_result()
        receipt = json.loads(Path(result['paths'][0]['execution_receipt']['path']).read_text())
        Path(receipt['result_ref']['path']).write_text('{}')
        with self.assertRaises(Rejected): self.submit(result, a)

    def test_original_evidence_archived_before_event(self):
        self.prepare()
        events = ledger.read_events(self.root)[1]
        event = next(e for e in events if e['operation'] == 'plan')
        snapshots = event['artifact_snapshots']
        self.assertGreater(len(snapshots), 7)
        original = Path(snapshots[0]['source_path'])
        archived = Path(snapshots[0]['path'])
        original.write_text('overwritten')
        self.assertNotEqual(original.read_bytes(), archived.read_bytes())
        self.assertTrue(self.state()['observed_invalidations'] or original.name == 'plan.json')

    def test_cli_status_smoke(self):
        script = Path(ledger.__file__)
        proc = subprocess.run([sys.executable, str(script), 'status', '--root', str(self.root)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['run_id'], 'demo')

    def test_real_red_fix_and_new_green_retest(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result(quality='red-bug')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        self.assertEqual(self.state()['modules']['M001']['quality'], 'red-bug')
        self.call('diagnose', {'diagnosis_ref': self.ref('red-diag.md', 'assert mismatch'), 'owner': 'fixer',
                               'root_cause': 'code'}, role='diagnostician')
        self.call('diagnosis-accept')
        self.implementation(role='fixer', aid='FIX1')
        a2, r2 = self.make_test_result(aid='TEST2', previous=r['paths'][0]['test_run_id'])
        self.submit(r2, a2); self.call('accept', {'assignment_id': 'TEST2'})
        self.call('complete', {'dod_ref': self.ref('dod-red.md', 'reviewed new code'), 'checks_passed': True})
        self.assertEqual(self.state()['modules']['M001']['quality'], 'green-passed')

    def test_false_green_actual_mismatch_rejected(self):
        self.prepare(); self.implementation(); a, r = self.make_test_result(quality='red-bug')
        r['paths'][0]['quality'] = 'green-passed'
        with self.assertRaises(Rejected): self.submit(r, a)

    def test_source_closure_and_target_feasibility_gate(self):
        p = self.plan(); p['source_closure']['unresolved'] = ['unknown runtime branch']
        with self.assertRaises(Rejected): self.call('plan', {'plan_ref': self.ref('bad-source.json', p)}, role='spec-designer')
        p['source_closure']['unresolved'] = []; p['target_feasibility']['verdict'] = 'unknown'
        with self.assertRaises(Rejected): self.call('plan', {'plan_ref': self.ref('bad-target.json', p)}, role='spec-designer')

    def finish_module(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result()
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        self.call('complete', {'dod_ref': self.ref('cursor-dod.md', 'reviewed'), 'checks_passed': True})

    def test_cursor_returns_phase_owner_session_and_does_not_dispatch(self):
        first = self.state()
        self.assertEqual(first['next_steps'][0]['operation'], 'plan')
        self.prepare()
        self.call('session', {'role': 'implementer', 'session_id': 'original-session'})
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['worker_role'], step['session_id']), ('assign', 'implementer', 'original-session'))
        sequence = self.state()['last_sequence']
        self.state()
        self.assertEqual(self.state()['last_sequence'], sequence)
        self.assign('implementer', 'I1')
        step = self.state()['next_steps'][0]
        self.assertEqual(step['operation'], 'await-result')
        self.assertFalse(step['ready'])

    def test_nested_suspend_rejected_preserves_resume_origin(self):
        blocker = {'kind': 'human', 'reason': 'question', 'root_cause': 'unknown', 'owner': 'human'}
        self.call('suspend', blocker)
        before = self.state()['modules']['M001']['blocked']
        with self.assertRaises(Rejected): self.call('suspend', blocker)
        self.assertEqual(self.state()['modules']['M001']['blocked'], before)

    def test_old_revoke_cannot_rewind_new_active_worker(self):
        self.prepare(); self.implementation()
        self.assign('test-runner', 'TEST1')
        with self.assertRaises(Rejected):
            self.call('revoke', {'assignment_id': 'I1', 'stopped_worker_ref': self.ref('old-stop.txt', 'stopped')}, role='host')
        self.assertEqual(self.state()['modules']['M001']['phase'], 'testing')

    def test_audit_assignment_cannot_be_overwritten_and_cancel_keeps_attempts(self):
        self.finish_module()
        code_review(self)
        self.call('audit-assign', {'assignment_id': 'A1', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        with self.assertRaises(Rejected):
            self.call('audit-assign', {'assignment_id': 'A2', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.call('audit-revoke', {'assignment_id': 'A1', 'stopped_worker_ref': self.ref('audit-stop.txt', 'host stopped')}, role='host', module=None)
        with self.assertRaises(Rejected):
            self.call('audit-assign', {'assignment_id': 'A1', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        code_review(self)
        self.call('audit-assign', {'assignment_id': 'A2', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.assertEqual(self.state()['audit_attempts'], 2)
        self.assertEqual(self.state()['global_next_step']['operation'], 'audit')

    def test_blocked_phase_rejects_worker_result(self):
        module = {'phase': 'waiting-dependency', 'blocked': {'kind': 'dependency'}}
        with self.assertRaises(Rejected): ledger.worker_phase(module, {'role': 'implementer'})

    def test_root_cause_change_resets_stagnation_fingerprint(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result(quality='yellow-blocked')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        a2, r2 = self.make_test_result(aid='TEST2', quality='yellow-blocked', previous=r['paths'][0]['test_run_id'])
        r2['paths'][0]['root_cause']['summary'] = 'a different confirmed prerequisite'
        self.submit(r2, a2); self.call('accept', {'assignment_id': 'TEST2'})
        self.assertEqual(self.state()['modules']['M001']['no_progress_rounds'], 0)

    def test_cursor_identifies_stale_evidence_before_dispatch(self):
        self.prepare(); self.implementation()
        (self.target / 'm1/code.py').write_text('changed externally')
        step = self.state()['next_steps'][0]
        self.assertEqual(step['operation'], 'invalidate')
        self.assertTrue(step['ready'])  # Recovery is actionable; coding remains forbidden.

    def test_complete_module_cannot_be_suspended(self):
        self.finish_module()
        with self.assertRaises(Rejected):
            self.call('suspend', {'kind': 'human', 'reason': 'late', 'root_cause': 'late', 'owner': 'human'})

    def test_dod_resume_retests_before_completion(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result()
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        self.call('suspend', {'kind': 'human', 'reason': 'review', 'root_cause': 'question', 'owner': 'human'})
        self.assertFalse(self.state()['next_steps'][0]['ready'])
        self.approve(digest(self.state()['modules']['M001']['blocked']), 'RESUME')
        self.assertTrue(self.state()['next_steps'][0]['ready'])
        self.call('resume', {'decision_id': 'RESUME'})
        self.assertEqual(self.state()['modules']['M001']['phase'], 'testing')
        with self.assertRaises(Rejected):
            self.call('complete', {'dod_ref': self.ref('dod.md', 'reviewed'), 'checks_passed': True})
        a2, r2 = self.make_test_result('TEST2', previous=r['paths'][0]['test_run_id'])
        self.submit(r2, a2); self.call('accept', {'assignment_id': 'TEST2'})
        self.call('complete', {'dod_ref': self.ref('dod.md', 'reviewed'), 'checks_passed': True})

    def test_invalidate_blocked_module_can_replan_and_submit(self):
        self.prepare()
        self.call('suspend', {'kind': 'human', 'reason': 'review', 'root_cause': 'question', 'owner': 'human'})
        self.call('invalidate', {'reason': 'new plan needed'})
        self.assertIsNone(self.state()['modules']['M001']['blocked'])
        p = self.plan()
        self.call('plan', {'plan_ref': self.ref('new-plan.json', p)}, role='spec-designer')
        with self.assertRaises(Rejected):
            self.call('freeze', {'change_class': 'within-envelope', 'impact_ref': self.ref('bypass.md', 'old blocker unresolved')})
        self.approve(digest(p), 'D2'); self.call('freeze', {'decision_id': 'D2'})
        self.implementation()
        self.assertEqual(self.state()['modules']['M001']['phase'], 'testing')

    def test_diagnosis_requires_idle_worker_and_mo_acceptance(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result(quality='red-bug')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        report = {'diagnosis_ref': self.ref('diagnosis.md', 'cause'), 'owner': 'M001', 'root_cause': 'code'}
        a2, r2 = self.make_test_result('TEST2', previous=r['paths'][0]['test_run_id'], quality='red-bug')
        with self.assertRaises(Rejected): self.call('diagnose', report, role='diagnostician')
        self.submit(r2, a2); self.call('accept', {'assignment_id': 'TEST2'})
        self.call('diagnose', report, role='diagnostician')
        self.assertEqual(self.state()['modules']['M001']['phase'], 'testing')
        self.assertEqual(self.state()['next_steps'][0]['operation'], 'diagnosis-accept')
        with self.assertRaises(Rejected): self.assign('fixer', 'FIX1')
        with self.assertRaises(Rejected): self.call('diagnosis-accept', role='diagnostician')
        self.call('diagnosis-accept')
        self.assign('fixer', 'FIX1')

    def test_yellow_cursor_routes_known_blockers_and_unknown_diagnosis(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result(quality='yellow-blocked')
        r['paths'][0]['root_cause'].update(category='dependency', confidence='confirmed')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        state = self.state(); m = state['modules']['M001']
        for category in ('dependency', 'environment', 'tooling', 'human', 'unknown'):
            m['results']['P1']['root_cause']['category'] = category
            step = ledger.next_step(state, m)
            self.assertEqual(step['operation'], 'diagnose' if category == 'unknown' else 'audit-defer')
        m['results']['P1']['quality'] = 'red-bug'
        m['results']['P1']['root_cause']['category'] = 'external'
        self.assertEqual(ledger.next_step(state, m)['operation'], 'audit-defer')

    def test_within_envelope_cursor_proposes_executable_freeze(self):
        self.prepare()
        cr = {'request_ref': self.ref('cr.md', 'task refinement'), 'impact_ref': self.ref('impact.md', 'within scope')}
        self.call('change', cr)
        p = self.plan(); p['tasks'][0]['detail'] = 'refinement'
        self.call('plan', {'plan_ref': self.ref('refined-plan.json', p)}, role='spec-designer')
        step = self.state()['next_steps'][0]
        self.assertTrue(step['ready'])
        self.call(step['operation'], step['payload'])
        self.assertEqual(self.state()['modules']['M001']['phase'], 'frozen')

    def audit_report(self, aid, failed=()):
        code_review(self)
        self.call('audit-assign', {'assignment_id': aid, 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        state = self.state(); scope = ledger.audit_scope(state)
        report = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'GLOBAL',
                  'assignment_id': aid, 'actor_instance_id': 'auditor', 'freeze_id': scope['freeze_id'],
                  'code_baseline': scope['code_baseline'], 'snapshot': {'M001': state['modules']['M001']['code_baseline']},
                  'paths': []}
        for path in scope['plan']['paths']:
            pid = path['path_id']; bad = pid in failed
            adapter = self.base / f'adapter-{aid}-{pid}.py'
            adapter.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\n" +
                               "json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':" + ('1' if bad else '2') +
                               ",'passed':" + ('False' if bad else 'True') + "}]},open(a.result_file,'w'))\n")
            rr = execute(self.root, 'GLOBAL', aid, pid, [sys.executable, str(adapter)], str(self.target), self.base / f'{aid}-{pid}')
            receipt = json.loads(Path(rr['path']).read_text())
            record = {'path_id': pid, 'quality': 'red-bug' if bad else 'green-passed', 'executed': True,
                      'test_run_id': receipt['test_run_id'], 'execution_receipt': rr,
                      'assertions': json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']}
            if pid in scope['results']: record['retest_of'] = scope['results'][pid]['test_run_id']
            if bad: record['root_cause'] = {'category': 'code', 'summary': 'integration mismatch', 'owner': 'M001',
                                           'confidence': 'confirmed', 'next_action': 'diagnose'}
            report['paths'].append(record)
        return report

    def test_audit_failure_routes_repair_and_preserves_retest_chain(self):
        self.finish_module()
        report = self.audit_report('AUD1', failed=['GP1'])
        self.call('audit', {'report_ref': self.ref('audit1.json', report)}, role='auditor', module=None)
        self.assertEqual(self.state()['global_next_step']['operation'], 'audit-route')
        with self.assertRaises(Rejected):
            self.call('audit-assign', {'assignment_id': 'EARLY', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.call('audit-route', {'path_id': 'GP1', 'module_ids': ['M001'], 'reason_ref': self.ref('route.md', 'owner reviewed')},
                  role='global-orchestrator', module=None)
        with self.assertRaises(Rejected): self.call('repair-accept', {'path_ids': ['GP1']}, role='auditor')
        self.call('repair-accept', {'path_ids': ['GP1']})
        self.assertEqual(self.state()['next_steps'][0]['operation'], 'diagnose')
        self.call('diagnose', {'diagnosis_ref': self.ref('audit-diag.md', 'cause'), 'owner': 'M001', 'root_cause': 'code'}, role='diagnostician')
        self.call('diagnosis-accept'); self.implementation(role='fixer', aid='FIX1')
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['worker_role']), ('assign', 'test-runner'))
        previous = self.state()['modules']['M001']['results']['P1']['test_run_id']
        a, r = self.make_test_result('TEST2', previous=previous)
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST2'})
        self.call('complete', {'dod_ref': self.ref('dod2.md', 'reviewed'), 'checks_passed': True})
        report2 = self.audit_report('AUD2')
        broken = copy.deepcopy(report2); broken['paths'][0].pop('retest_of')
        with self.assertRaises(Rejected):
            self.call('audit', {'report_ref': self.ref('audit-missing-chain.json', broken)}, role='auditor', module=None)
        self.call('audit', {'report_ref': self.ref('audit2.json', report2)}, role='auditor', module=None)
        self.assertEqual(self.state()['quality'], 'green-passed')
        self.assertFalse(self.state()['audit_repairs'])

    def test_diagnosis_rejected_after_new_test_result(self):
        self.prepare(); self.implementation()
        a, r = self.make_test_result(quality='red-bug')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        self.call('diagnose', {'diagnosis_ref': self.ref('diag.md', 'cause'), 'owner': 'M001', 'root_cause': 'code'}, role='diagnostician')
        a2, r2 = self.make_test_result('TEST2', previous=r['paths'][0]['test_run_id'])
        self.submit(r2, a2); self.call('accept', {'assignment_id': 'TEST2'})
        with self.assertRaises(Rejected): self.call('diagnosis-accept')
        self.assertEqual(self.state()['modules']['M001']['phase'], 'dod')

    def test_audit_owner_path_ids_cannot_collide(self):
        p = self.plan(); p['paths'][0]['path_id'] = 'GP1'; p['tasks'][0]['path_ids'] = ['GP1']
        with self.assertRaises(Rejected):
            self.call('plan', {'plan_ref': self.ref('collision.json', p)}, role='spec-designer')

    def test_pending_audit_repair_waits_for_module_rebuild(self):
        self.prepare()
        state = self.state(); m = state['modules']['M001']
        state['audit_repairs'] = {'GP1': {'module_ids': ['M001'], 'accepted_by': []}}
        step = ledger.next_step(state, m)
        self.assertEqual((step['operation'], step['worker_role']), ('assign', 'implementer'))
        self.implementation()
        state = self.state(); m = state['modules']['M001']
        state['audit_repairs'] = {'GP1': {'module_ids': ['M001'], 'accepted_by': []}}
        m['dependencies'] = ['M002']
        state['modules']['M002'] = {'phase': 'context', 'stale': True, 'assignments': {}}
        step = ledger.next_step(state, m)
        self.assertEqual(step['operation'], 'repair-accept')
        self.assertFalse(step['ready'])


if __name__ == '__main__':
    unittest.main()
