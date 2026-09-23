"""Same-run source changes use real prepared snapshots, receipts and Ledger events."""
import copy
from pathlib import Path
import sys
import json
import unittest
from unittest.mock import patch

import test_context_readiness
import test_decomposition
import test_dimensions
import test_ledger
import test_audit_scope
import context_readiness as cr
import decomposition
import ledger
import project_context as pc
import reuse
import source_changes
from contracts import Rejected, baseline, check_ref, digest, file_ref, read_json
from execute_test import execute
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
from harmony_stage import build as stage_result


class SourceChangeTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        old = f.state(); f.root = (f.base/'.sdd-runs/demo').resolve()
        actor = {'role': 'host', 'instance_id': 'host'}
        self.config_root = f.base/'.sdd-migration'
        self.config = {'legacy_root': str(f.legacy), 'target_root': str(f.target),
                       'architecture_path': old['new_architecture']['path']}
        pc.update(self.config_root, {'schema_version': 1, 'project_id': 'demo', 'request_id': 'config',
                  'expected_revision': 0, 'patch': self.config, 'source_ref': f.ref('user-config.md', 'Use these roots')}, actor, True)
        prepared = pc.prepare(self.config_root, f.root, {'schema_version': 1, 'project_id': 'demo', 'request_id': 'prepare',
            'run_id': 'demo', 'source_ref': f.ref('user-run.md', 'Migrate fixture')}, actor)
        self.original_ref = prepared['project_context_ref']
        f.call('init', {**{k: old[k] for k in ('target_root', 'legacy_root', 'global_spec', 'case_ids', 'requirement_ids')},
            'new_architecture': prepared['input']['new_architecture'], 'project_context_ref': self.original_ref,
            'global_paths': []}, role='host')
        self.d = test_dimensions.DimensionTests(); self.d.f = f
        analysis = self.d.analysis()
        self.d.root_ref = f.ref('root-dimensions.json', analysis)
        f.call('register', {'module_id': 'M010', 'case_ids': ['C1'], 'write_paths': [str(f.target)],
            'scope': analysis['scope'], 'context_refs': [f.ref('root-context.md', 'Parent scope')],
            'dimension_analysis_ref': self.d.root_ref, 'decomposition_required': True}, role='global-orchestrator', module=None)
        f.split(self.d.proposal(ids=('M001', 'M002')))
        f.global_plan()
        self.library = (f.base/'library').resolve(); self.library.mkdir()
        self.sources = reuse.normalize_sources([{'source_id': 'LIB', 'root': str(self.library)}], str(f.target), True)

    def plan(self, mid):
        f = self.f
        # Fixture helpers share definition paths; give every frozen plan its own copies.
        p = test_ledger.FlowTests.plan(f)
        module = f.state()['modules'][mid]; iid = mid+'-Logic'; pid = mid+'-P'; bid = mid+'-B'
        p.update(module_id=mid, planning_context=f.state()['planning_context'], assigned_module=f.state()['module_inputs'][mid],
                 dimension_analysis_ref=module['dimension_analysis_ref'])
        p['definitions'] = [{**f.ref(f'defs-{mid}-{f.n}/{r["kind"]}.md', check_ref(r).read_text() + '\n'+iid+'\n'), 'kind': r['kind']}
                            for r in p['definitions']]
        p['paths'][0].update(path_id=pid, kind='automation')
        p['paths'].append({'path_id': bid, 'kind': 'build', 'name': 'compile', 'case_id': 'C1', 'requirement_id': 'R1',
            'required': True, 'expected_assertions': [{'assertion_id': 'BUILD-EXIT', 'expected': 0}],
            'command': {'argv': [sys.executable, '-c', 'pass'], 'cwd': str(f.target), 'timeout_seconds': 20,
                        'selection_ref': f.ref('build-command.md', 'Fixture build')}})
        p['dimension_trace'] = [{'item_id': iid, 'task_ids': ['T1'], 'path_ids': [pid],
                                 'assertions': [{'path_id': pid, 'assertion_id': 'A1'}]}]
        task = p['tasks'][0]; task['path_ids'] = [pid, bid]
        task['scope'] = {'in': ['implement subfunction'], 'out': ['Orders'], 'write_paths': module['write_paths']}
        task['dimension_analysis'] = {'scope_sha256': digest(task['scope']), 'parent_ref': p['dimension_analysis_ref'], 'unresolved': [],
            'dimensions': [{'dimension': k, 'status': 'applicable' if k == 'Logic' else 'not-applicable',
                'reason': 'Reviewed source behavior', 'implementation': 'Implement and verify scoped behavior',
                'item_ids': [iid] if k == 'Logic' else [], 'evidence_refs': [f.ref('task-evidence.md', 'Task review')]}
                for k in ('UI', 'Logic', 'Adhesive', 'Resource')]}
        test_ledger.FlowTests.attach_reuse(f, p)
        review = read_json(check_ref(p['reuse_plan_ref']))
        review['catalog_ref'] = f.ref(f'catalog-{mid}-{f.n}.json', read_json(check_ref(review['catalog_ref'])))
        p['reuse_plan_ref'] = f.ref(f'reuse-{mid}-{f.n}.json', review)
        return p

    def freeze(self, mid):
        f = self.f; p = self.plan(mid)
        f.call('plan', {'plan_ref': f.ref(f'plan-{mid}-{f.n}.json', p)}, role='spec-designer', module=mid)
        did = 'freeze-'+str(f.n)
        f.call('decision', {'decision_id': did, 'module_id': mid, 'decision': 'approved', 'subject_sha256': digest(p),
                           'human_source_ref': f.ref(did+'.md', 'Approve exact plan')}, role='host', module=None)
        f.call('freeze', {'decision_id': did}, module=mid)
        return p

    def report(self, affected=('M001', 'M002'), release=()):
        f = self.f; s = f.state()
        sources = reuse.sources({**s, 'reuse_sources': self.sources})
        proof = f.ref(f'impact-evidence-{f.n}.md', 'Compared new source to all routes including new implementations; reviewed ownership and locks')
        catalog = {'schema_version': 2, 'sources': sources, 'capabilities': [], 'source_reviews': [
            {'source_id': row['source_id'], 'status': 'reviewed', 'scanned_paths': row['module_paths'],
             'conclusion': 'Reviewed available behavior; no direct candidate', 'evidence_refs': [proof]} for row in sources]}
        return {'schema_version': 1, 'run_id': 'demo', 'reuse_sources': self.sources,
            'catalog_ref': f.ref(f'new-catalog-{f.n}.json', catalog),
            'parent_reviews': {'M010': proof},
            'modules': [{'module_id': mid, 'action': 'replan' if mid in affected else 'unchanged',
                'reason': 'Scoped source impact review', 'evidence_refs': [proof],
                'resume_blocker_sha256': digest(m['blocked']) if mid in release else None} for mid, m in s['modules'].items()]}

    def review(self, report=None):
        f = self.f
        ref = f.ref(f'source-impact-{f.n}.json', report or self.report())
        receipt = f.record(f.report('global-planning', module=None, draft=ref))
        f.raw('source-review', {'report_ref': ref, 'context_ref': receipt}, role='global-orchestrator', module=None)
        return ref

    def approve(self):
        f = self.f; subject = f.state()['source_change_review']['subject_sha256']
        did = 'sources-'+str(f.n)
        f.call('decision', {'decision_id': did, 'module_id': None, 'decision': 'approved', 'subject_sha256': subject,
                           'human_source_ref': f.ref(did+'.md', 'Append sources with exact listed replan/blocker effects')}, role='host', module=None)
        return {'decision_id': did, 'subject_sha256': subject}

    def apply(self, payload=None):
        return self.f.raw('reconfigure-sources', payload or self.approve(), role='host', module=None)

    def implement_and_test(self, mid, value=2, role='implementer'):
        f = self.f; aid = 'I-'+mid+'-'+str(f.n)
        actor = 'coder' if role == 'implementer' else 'fixer'
        f.call('assign', {'role': role, 'assignment_id': aid, 'instance_id': actor}, module=mid)
        m = f.state()['modules'][mid]; a = m['assignments'][aid]
        code = Path(m['write_paths'][0])/'code.py'; code.parent.mkdir(exist_ok=True); code.write_text(f'value = {value}\n')
        proof = f.ref('binding-'+aid+'.md', 'Real scoped implementation')
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': mid,
            'assignment_id': aid, 'actor_instance_id': actor, 'freeze_id': m['freeze_id'],
            'code_files': [file_ref(code)], 'code_baseline': baseline([file_ref(code)]),
            'task_trace': [{'task_id': 'T1', 'files': [str(code)]}], 'production_binding_evidence': proof,
            'dimension_evidence': [{'item_id': mid+'-Logic', 'task_ids': ['T1'], 'summary': 'Implemented scoped behavior', 'evidence_refs': [proof]}]}
        if role == 'fixer':
            result['fix_note_ref'] = f.ref('fix-note-'+aid+'.json', {'root_cause': 'wrong value', 'strategy': 'correct calculation',
                'applicability': 'same source behavior', 'risks': 'rerun full module'})
        f.call('submit', {'assignment_id': aid, 'fencing_token': a['fencing_token'], 'result_ref': f.ref(aid+'.json', result)},
               role=role, instance=actor, module=mid)
        f.call('accept', {'assignment_id': aid}, module=mid)
        for scope, stage, suffix in (('build', 'building', '-B'), ('automation', 'testing', '-P')):
            aid = scope+'-'+mid+'-'+str(f.n)
            if scope == 'build': argv = [sys.executable, '-c', 'pass']
            else:
                script = f.root/'staging/test-runner'/(aid+'.py')
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text('import argparse,json,runpy\np=argparse.ArgumentParser();p.add_argument("--query-file");p.add_argument("--result-file");a=p.parse_args()\n'
                    +f'v=runpy.run_path({str(code)!r})["value"]; passed=v==2\n'
                    +'r={"flaky":False,"quality":"green-passed" if passed else "red-bug",'
                    +'"assertions":[{"assertion_id":"A1","expected":2,"actual":v,"passed":passed}]}\n'
                    +'if not passed: r["root_cause"]={"category":"code","summary":"wrong value","confidence":"confirmed","owner":"'+mid+'","next_action":"fix"}\n'
                    +'json.dump(r,open(a.result_file,"w"))\n')
                argv = [sys.executable, str(script)]
            report = f.report(stage, module=mid)
            report['execution'] = {'argv': argv, 'cwd': str(f.target), 'environment_ref': f.ref('environment.md', 'Python fixture available')}
            receipt = f.record(report)
            f.raw('assign', {'role': 'test-runner', 'assignment_id': aid, 'instance_id': 'test-runner',
                'test_scope': scope, 'context_ref': receipt}, module=mid)
            a = f.state()['modules'][mid]['assignments'][aid]
            rr = execute(f.root, mid, aid, mid+suffix, argv, str(f.target), f.root/('runs/build' if scope == 'build' else 'runs/harmony/automation')/aid)
            if scope == 'build':
                result = stage_result(f.root, mid, aid, [rr])
            else:
                receipt_data = read_json(check_ref(rr)); captured = read_json(check_ref(receipt_data['result_ref']))
                m = f.state()['modules'][mid]
                row = {**captured, 'path_id': mid+suffix, 'executed': True, 'execution_receipt': rr,
                       'test_run_id': receipt_data['test_run_id'], 'retest_of': m['results'].get(mid+suffix, {}).get('test_run_id')}
                result = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': mid,
                    'assignment_id': aid, 'actor_instance_id': 'test-runner', 'freeze_id': m['freeze_id'],
                    'code_baseline': m['code_baseline'], 'paths': [row]}
            f.call('submit', {'assignment_id': aid, 'fencing_token': a['fencing_token'], 'result_ref': f.ref(aid+'.json', result)},
                   role='test-runner', module=mid)
            f.call('accept', {'assignment_id': aid}, module=mid)
        if value == 2:
            f.call('complete', {'dod_ref': f.ref('dod-'+mid+'.md', 'All paths Green'), 'checks_passed': True}, module=mid)

    def test_red_evidence_and_unrelated_green_survive_then_real_retest_resolves(self):
        f = self.f
        self.freeze('M001'); self.freeze('M002')
        self.implement_and_test('M001', value=9); self.implement_and_test('M002')
        before = f.state(); red = before['modules']['M001']['results']['M001-P']
        peer = before['modules']['M002']
        self.review(self.report(affected=('M001',))); self.apply()
        s = f.state()
        self.assertEqual(s['modules']['M001']['results']['M001-P'], red)
        self.assertEqual(s['modules']['M001']['quality'], 'red-bug')
        for key in ('results', 'code_baseline', 'freeze_id', 'phase', 'quality', 'local_fix_used', 'fix_rounds_used'):
            self.assertEqual(s['modules']['M002'].get(key), peer.get(key))
        self.freeze('M001'); self.implement_and_test('M001')
        after = f.state()['modules']['M001']['results']['M001-P']
        self.assertEqual(after['quality'], 'green-passed')
        self.assertEqual(after['retest_of'], red['test_run_id'])
        self.assertNotEqual(after['test_run_id'], red['test_run_id'])
        self.assertFalse(f.state()['module_rounds']['all_settled'])  # Parent still owns its summary.
        state = f.state()
        ledger.apply(f.root, {'schema_version': 1, 'run_id': 'demo', 'request_id': 'parent-summary-after-sources',
            'module_id': 'M010', 'expected_revision': state['module_groups']['M010']['revision'], 'operation': 'module-summary',
            'payload': {'summary_ref': f.ref('parent-summary.md', 'Reviewed both child results and source-change evidence'),
                        'subject_sha256': decomposition.summary_subject(state, state['module_groups']['M010'])}},
            {'role': 'module-orchestrator', 'instance_id': 'parent-mo-M010'})
        report = test_audit_scope.AuditScopeTests().review(f)
        self.assertEqual(report['paths'], [])
        f.raw('audit', {'report_ref': f.ref('independent-review.json', report)}, role='auditor', module=None)
        self.assertEqual(f.state()['quality'], 'green-passed')

    def test_source_change_cannot_interrupt_active_auditor_or_repair_batch(self):
        f = self.f
        for field, value in (('audit_assignment', {'closed': False}), ('audit_batch', {'status': 'repairing'})):
            s = ledger.read_events(f.root)[0]; s[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, 'audit .*'):
                ledger.mutate(s, {'operation': 'reconfigure-sources', 'module_id': None, 'payload': {}},
                              {'role': 'host', 'instance_id': 'host'}, [], f.root)

    def test_failed_fixer_budget_and_memory_survive_reconfiguration(self):
        f = self.f; self.freeze('M001'); self.freeze('M002')
        self.implement_and_test('M001', value=9)
        f.call('diagnose', {'diagnosis_ref': f.ref('diagnosis.md', 'Calculation error'), 'owner': 'fixer',
                           'root_cause': 'code'}, role='diagnostician')
        f.call('diagnosis-accept')
        self.implement_and_test('M001', value=8, role='fixer')
        before = f.state()['modules']['M001']
        self.assertEqual(before['local_fix_used'], 1)
        self.review(self.report(affected=('M001',))); self.apply()
        after = f.state()['modules']['M001']
        for key in ('local_fix_used', 'fix_rounds_used', 'fix_memory', 'no_progress_rounds'):
            self.assertEqual(after[key], before[key])
        self.freeze('M001'); self.implement_and_test('M001', value=7)
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M001')
        self.assertEqual(step['operation'], 'audit-defer')

    def test_incomplete_impact_receipt_and_unknown_configuration_rejected(self):
        f = self.f
        report = self.report(); report['modules'].pop()
        with self.assertRaisesRegex(Rejected, 'every leaf'): self.review(report)
        report = self.report(); report['parent_reviews'] = {}
        with self.assertRaisesRegex(Rejected, 'parent allocations'): self.review(report)
        report = self.report(); report['write_paths'] = [str(f.target)]
        with self.assertRaisesRegex(Rejected, 'fields invalid'): self.review(report)
        ref = f.ref('missing-receipt.json', self.report())
        with self.assertRaisesRegex(Rejected, 'receipt required'):
            f.raw('source-review', {'report_ref': ref}, role='global-orchestrator', module=None)

    def test_dependency_closure_cannot_be_omitted_from_impact(self):
        self.freeze('M001'); self.freeze('M002')
        state = ledger.read_events(self.f.root)[0]
        # Pure validator fixture: existing registered consumer of M001.
        state['modules']['M002']['dependencies'] = ['M001']
        import workflow
        state['global_plan']['registry_hash'] = digest(workflow.registry(state))
        ref = self.f.ref('missing-consumer.json', self.report(affected=('M001',)))
        with self.assertRaisesRegex(Rejected, 'dependent closure'): source_changes.validate(state, ref)

    def test_append_keeps_original_snapshot_links_defaults_and_event_history(self):
        f = self.f; old_bytes = check_ref(self.original_ref).read_bytes()
        before_events = (f.root/'ledger/events.jsonl').read_bytes()
        self.review(); self.apply(); s = f.state()
        self.assertEqual(check_ref(self.original_ref).read_bytes(), old_bytes)
        self.assertTrue((f.root/'ledger/events.jsonl').read_bytes().startswith(before_events))
        self.assertNotEqual(s['project_context_ref'], self.original_ref)
        snap = pc.verify_snapshot(s['project_context_ref'])
        self.assertEqual(snap['previous_context_ref'], self.original_ref)
        old = pc.verify_snapshot(self.original_ref)
        self.assertEqual(snap['source_refs'], old['source_refs'])
        self.assertEqual(snap['source_paths'], old['source_paths'])
        self.assertNotIn('reuse_sources', pc.current(self.config_root)['config'])
        self.assertEqual(pc.prepared_input(s['project_context_ref'])['reuse_sources'], self.sources)
        self.assertTrue(all(m['phase'] == 'specifying' for m in s['modules'].values()))
        self.freeze('M001')  # Fresh plan and human freeze actually work on the new context.
        f.call('assign', {'role': 'implementer', 'assignment_id': 'I', 'instance_id': 'coder'})

    def test_unchanged_frozen_sibling_keeps_plan_and_can_dispatch_with_new_receipt(self):
        f = self.f; self.freeze('M001'); old = self.freeze('M002')
        before = f.state()['modules']['M002']
        self.review(self.report(affected=('M001',))); self.apply()
        s = f.state(); peer = s['modules']['M002']
        self.assertEqual(peer['freeze_id'], before['freeze_id']); self.assertEqual(peer['plan'], old)
        self.assertIsNone(s['modules']['M001']['plan'])
        self.assertFalse((f.root/'openspec/changes/demo-m001/tasks.md').exists())
        self.assertIn('Replanning required', (f.base/'openspec/changes/demo-m001/status.md').read_text())
        f.call('assign', {'role': 'implementer', 'assignment_id': 'PEER', 'instance_id': 'coder'}, module='M002')
        self.assertEqual(f.state()['modules']['M002']['phase'], 'implementing')

    def test_related_blocker_can_replan_unrelated_blocker_remains(self):
        f = self.f
        for mid in ('M001', 'M002'):
            f.call('suspend', {'kind': 'human', 'reason': 'need source' if mid == 'M001' else 'business decision pending',
                               'root_cause': 'missing context', 'owner': 'human'}, module=mid)
        other = copy.deepcopy(f.state()['modules']['M002']['blocked'])
        self.review(self.report(release=('M001',))); self.apply()
        s = f.state()
        self.assertIsNone(s['modules']['M001']['blocked'])
        self.assertEqual(s['modules']['M001']['phase'], 'specifying')
        self.assertEqual(s['modules']['M002']['blocked']['reason'], other['reason'])
        self.assertEqual(s['modules']['M002']['phase'], 'waiting-human')
        self.assertTrue(s['modules']['M001']['planning_history'][-1]['blocked'])

    def test_approval_role_scope_idempotency_and_replay(self):
        f = self.f; self.review()
        with self.assertRaises(Rejected): self.apply({'decision_id': 'missing', 'subject_sha256': 'wrong'})
        payload = self.approve()
        with self.assertRaisesRegex(Rejected, 'role denied'):
            f.raw('reconfigure-sources', payload, role='global-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'other run configuration'):
            self.apply({**payload, 'target_root': str(f.legacy)})
        s = ledger.read_events(f.root)[0]
        req = {'schema_version': 1, 'run_id': 'demo', 'request_id': 'retry-source', 'expected_revision': s['revision'],
               'module_id': None, 'operation': 'reconfigure-sources', 'payload': payload}
        actor = {'role': 'host', 'instance_id': 'host'}
        first = ledger.apply(f.root, req, actor); replayed = ledger.read_events(f.root)[0]
        second = ledger.apply(f.root, req, actor)
        self.assertEqual(first['event_id'], second['event_id']); self.assertTrue(second['duplicate'])
        self.assertEqual(replayed['project_context_ref'], f.state()['project_context_ref'])

    def test_revision_drift_rejects_approval_and_emits_review_signal(self):
        f = self.f; self.review(); p = self.approve()
        f.call('suspend', {'kind': 'human', 'reason': 'new issue', 'root_cause': 'new question', 'owner': 'human'})
        with self.assertRaisesRegex(Rejected, 'review stale'): self.apply(p)
        self.assertEqual(f.state()['source_change_next_step']['operation'], 'source-review')

    def test_existing_source_cannot_change_or_be_removed(self):
        self.review(); self.apply()
        second = self.library/'second'; second.mkdir()
        self.sources = self.sources + [{'source_id': 'LIB2', 'root': str(second), 'module_paths': [str(second)]}]
        for mode in ('remove', 'change'):
            report = self.report()
            if mode == 'remove': report['reuse_sources'] = report['reuse_sources'][1:]
            else: report['reuse_sources'] = copy.deepcopy(report['reuse_sources']); report['reuse_sources'][0]['description'] = 'changed'
            with self.subTest(mode=mode), self.assertRaisesRegex(Rejected, 'immutable'):
                self.review(report)

    def test_active_worker_does_not_get_cancelled_by_source_append(self):
        f = self.f; self.freeze('M001')
        f.call('assign', {'role': 'implementer', 'assignment_id': 'I', 'instance_id': 'coder'})
        self.review(); payload = self.approve()
        with self.assertRaisesRegex(Rejected, 'stop/revoke'): self.apply(payload)
        self.assertFalse(f.state()['modules']['M001']['assignments']['I']['closed'])

    def test_failed_projection_is_recovered_by_idempotent_retry(self):
        f = self.f; self.review(); p = self.approve()
        req = {'schema_version': 1, 'run_id': 'demo', 'request_id': 'crash-source', 'expected_revision': f.state()['revision'],
               'module_id': None, 'operation': 'reconfigure-sources', 'payload': p}
        actor = {'role': 'host', 'instance_id': 'host'}
        with patch('ledger.project', side_effect=OSError('projection crash')):
            ack = ledger.apply(f.root, req, actor)
            self.assertTrue(ack['committed'])
            self.assertEqual(ack['projection']['status'], 'pending')
        self.assertTrue(ledger.apply(f.root, req, actor)['duplicate'])
        self.assertEqual(f.state()['source_change_review']['status'], 'applied')


if __name__ == '__main__': unittest.main()
