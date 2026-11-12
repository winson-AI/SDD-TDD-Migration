"""What the unified audit finds wrong in a SPEC or in how the scope was cut is traced back to the slices and parents that
revise it, bottom-up and without a human release; what was built is kept and brought to the revised SPEC."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_ledger
import test_audit_closure
import test_decomposition
from contracts import Rejected


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.c = c = test_audit_closure.ClosureTests(); c.setUp(); self.addCleanup(c.doCleanups)
        c.cross_module_failure()
        test_ledger.code_review(c)
        c.call('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)

    def route(self, action='trace', owners=('M001',), **extra):
        return {'source_module_id': 'M002', 'owner_module_ids': list(owners), 'action': action,
                'root_cause': {'category': 'planning-gap', 'summary': 'the provider SPEC never stated the shared value', 'confidence': 'confirmed',
                               'owner': 'M001', 'next_action': 'revise-spec'},
                'analysis_ref': self.c.ref('trace-analysis.md', 'SPEC, tasks and the split reviewed bottom-up'), **extra}

    def plan(self, *routes):
        c = self.c
        c.call('audit-plan', {'plan_ref': c.ref('routes-%d.json' % c.n, {'routes': list(routes)})}, role='auditor', module=None)
        c.call('audit-route-batch', {'review_ref': c.ref('route-review.md', 'Global confirmed who revises')}, role='global-orchestrator', module=None)

    def test_a_finding_traced_back_is_recorded_for_its_slice_and_the_batch_is_released_without_a_human(self):
        c = self.c
        self.plan(self.route())
        state = c.state()
        self.assertEqual((state['audit_batch']['status'], state['audit_batch']['released_for']), ('released', 'traceback'))
        issue_id, issue = next(iter(state['issues'].items()))
        self.assertRegex(issue_id, '^TRACE-B1-F-M002-')
        self.assertEqual((issue['kind'], issue['applies_to'], issue['blocks'], issue['summary']),
                         ('defect', ['M001'], False, 'the provider SPEC never stated the shared value'))
        step = next(x for x in state['next_steps'] if x['module_id'] == 'M001')
        self.assertEqual((step['operation'], step['reason'], step['issue_ids'], step['mechanical']), ('change', 'audit-traceback', [issue_id], True))
        self.assertEqual(step['payload']['resolves'], [issue_id])  # the revision answers what was traced back: a confirmed cause opens it by itself
        with self.assertRaisesRegex(Rejected, 'open-issues'):  # the audit collects again once what it sent back is revised
            c.call('audit-collect', {'batch_id': 'B2', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        baseline = state['modules']['M001']['code_baseline']
        c.call('change', step['payload'], module='M001')
        revising = c.state(); module = revising['modules']['M001']
        self.assertEqual((module['phase'], module['code_baseline']), ('change-review', baseline))  # its SPEC is reopened, its code stays
        self.assertNotIn('M001', revising['issues'][issue_id]['resolved'])
        p = c.plan()
        next(d for d in p['definitions'] if d['kind'] == 'design').update(c.ref('updated-design.md', 'The shared value is 2.'))
        c.call('plan', {'plan_ref': c.ref('revised-provider.json', p)}, role='spec-designer', module='M001')
        self.assertNotIn('M001', c.state()['issues'][issue_id]['resolved'])
        revised = c.state()['modules']['M001']
        c.approve(revised['plan_hash'], 'TRACE-DECISION')
        c.call('freeze', {'decision_id': 'TRACE-DECISION'}, module='M001')
        self.assertEqual(c.state()['issues'][issue_id]['resolved']['M001']['evidence_ref'], revised['plan_ref'])

    def test_a_finding_that_needs_a_human_keeps_the_batch_for_the_human(self):
        import audit_closure
        mixed = {'batch_id': 'B9', 'status': 'repairing', 'routes': {'F1': {**self.route(), 'finding_id': 'F1'},
                                                                      'F2': {**self.route('human', owners=()), 'finding_id': 'F2'}}}
        state = {'audit_batch': mixed, 'modules': {}}
        audit_closure.trace_back(state, mixed, {'role': 'global-orchestrator', 'instance_id': 'go'})
        self.assertEqual((mixed['status'], list(state['issues'])), ('repairing', ['TRACE-B9-F1']))  # recorded, and the human decides the rest first
        c = self.c
        self.plan(self.route('human', owners=()))
        self.assertNotEqual(c.state()['audit_batch']['status'], 'released')
        self.assertNotIn('issues', c.state())

    def test_who_revises_is_named(self):
        for route, message in ((self.route(owners=()), 'only fix and trace routes specify owners'),
                               (self.route(owners=('M999',)), 'unknown/duplicate repair owner'),
                               (self.route('verify', owners=('M001',)), 'only fix and trace routes specify owners')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.c.call('audit-plan', {'plan_ref': self.c.ref('bad-routes.json', {'routes': [route]})}, role='auditor', module=None)


class ParentTests(unittest.TestCase):
    def test_scope_and_spec_trace_take_distinct_routes_and_only_scope_closes_on_reallocation(self):
        import audit_closure, decomposition, issues

        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); proposal = f.proposal(); f.split(proposal); f.global_plan()
        state = f.state(); mid = 'M002'
        module = state['modules'][mid]
        go = {'role': 'global-orchestrator', 'instance_id': 'go'}
        mo = {'role': 'module-orchestrator', 'instance_id': 'mo'}
        ref = f.ref('audit-trace.md', 'Scope and SPEC reviewed separately')
        batch = {'batch_id': 'B1', 'status': 'repairing',
                 'routes': {fid: {'action': 'trace', 'owner_module_ids': [mid], 'source_module_id': mid,
                                  'analysis_ref': ref, 'root_cause': {'category': cause, 'confidence': 'confirmed'}}
                            for fid, cause in [('SCOPE', 'scope-insufficient'), ('SPEC', 'planning-gap')]}}
        audit_closure.trace_back(state, batch, go)
        def route():
            return ledger.traced_revision(state, module, [row['issue_id'] for row in issues.of_module(state, mid)[0]])
        local = route()
        self.assertEqual((local['operation'], local['issue_ids']), ('change', ['TRACE-B1-SPEC']))
        with self.assertRaisesRegex(Rejected, 'in-scope trace requires'):
            decomposition.handle(state, {'module_id': mid, 'operation': 'realloc-request',
                'payload': {'reason': 'Both issues', 'evidence_refs': [ref], 'resolves': local['issue_ids']}}, mo, f.root)
        issues.cite(state, mid, local['issue_ids'], ref, mo)  # simulate the accepted SPEC revision
        upstream = route()
        self.assertEqual((upstream['operation'], upstream['issue_ids']), ('realloc-request', ['TRACE-B1-SCOPE']))
        decomposition.handle(state, {'module_id': mid, 'operation': 'realloc-request', 'payload': upstream['payload']}, mo, f.root)
        self.assertEqual([row['issue_id'] for row in issues.of_module(state, mid)[0]], upstream['issue_ids'])
        decomposition.handle(state, {'module_id': 'M010', 'operation': 'redecompose',
                                      'payload': {'plan_ref': f.ref('same-split.json', proposal)}}, mo, f.root)
        review = f.ref('allocation-review.md', 'Review confirmed the current allocation addresses the scope concern')
        decomposition.handle(state, {'module_id': 'M010', 'operation': 'redecompose-accept',
                                      'payload': {'review_ref': review}}, go, f.root)
        self.assertEqual(state['issues']['TRACE-B1-SCOPE']['resolved'][mid]['evidence_ref'], review)
        self.assertEqual(state['issues']['TRACE-B1-SPEC']['resolved'][mid]['evidence_ref'], ref)

    def test_an_issue_recorded_for_a_parent_offers_it_a_re_split(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); f.split(); f.global_plan()
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M010')
        self.assertIsNone(step['operation'])
        f.call('issue', {'issue_id': 'CUT', 'kind': 'defect', 'summary': 'two slices write the same screen', 'applies_to': ['M010']},
               role='auditor', module=None)
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M010')
        self.assertEqual((step['operation'], step['ready'], step['reason'], step['issue_ids']), ('redecompose', True, 'open-issues', ['CUT']))
        f.call('issue-resolve', {'issue_id': 'CUT', 'module_id': 'M010', 'evidence_ref': f.ref('split-review.md', 'the split stands: one writer per file')},
               role='module-orchestrator', module=None)
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M010')
        self.assertIsNone(step['operation'])


class KeptCodeTests(unittest.TestCase):
    def test_trace_only_change_leaves_consumer_runnable_until_provider_evidence_drifts(self):
        import context_readiness
        import issues
        from contracts import check_ref, digest

        f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M001'],
                            'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        f.prepare(); f.implement('M001', 'I1', shared=2); f.verify_module('M001', 'T1')
        plan = f.plan()
        plan['module_id'] = 'M002'; plan['paths'][0]['path_id'] = 'P2'; plan['tasks'][0]['path_ids'] = ['P2']
        f.call('plan', {'plan_ref': f.ref('p2.json', plan)}, role='spec-designer', module='M002')
        f.call('decision', {'decision_id': 'D2', 'decision': 'approved', 'module_id': 'M002',
                            'subject_sha256': digest(plan), 'human_source_ref': f.ref('d2.md', 'Approve the consumer')},
               role='host', module=None)
        f.call('freeze', {'decision_id': 'D2'}, module='M002')
        f.implement('M002', 'I2')
        state, events = ledger.read_events(f.root)
        consumer = state['modules']['M002']
        provider = state['modules']['M001']
        previous = copy.deepcopy(consumer)
        preflight = context_readiness.subject(state, 'M002', 'testing')
        issues.owe(state, 'M001', ['OpenSpec spec missing dimension item IDs: Logic-1'])
        ref = f.ref('trace-change.md', 'Append the missing four-dimension ID')
        ledger.mutate(state, {'module_id': 'M001', 'operation': 'change', 'payload': {'request_ref': ref, 'impact_ref': ref}},
                      {'role': 'module-orchestrator', 'instance_id': 'mo'}, events, f.root)
        self.assertEqual(consumer, previous)
        self.assertEqual(context_readiness.subject(state, 'M002', 'testing'), preflight)
        self.assertEqual(provider['phase'], 'change-review')
        self.assertEqual(ledger.dependency_provider(provider)['code_baseline'], provider['code_baseline'])
        ledger.dispatch_guard(state, consumer, 'test-runner')
        code = check_ref(provider['code_files'][0])
        code.write_text('shared = 9\n')
        with self.assertRaises(Rejected):
            ledger.dispatch_guard(state, consumer, 'test-runner')
        ledger.invalidate_dependents(state, 'M001')
        self.assertNotIn('trace_dependency_baseline', provider)
        self.assertEqual((consumer['phase'], consumer['stale']), ('waiting-dependency', True))

    def test_provider_revision_cannot_replace_or_release_a_consumers_human_blocker(self):
        from contracts import digest

        f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M001'],
                            'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        f.prepare(); f.implement('M001', 'I1', shared=2); f.verify_module('M001', 'T1'); f.complete('M001')
        provider_plan = copy.deepcopy(f.state()['modules']['M001']['plan'])
        consumer_plan = f.plan()
        consumer_plan['module_id'] = 'M002'
        consumer_plan['paths'][0]['path_id'] = 'P2'
        consumer_plan['tasks'][0]['path_ids'] = ['P2']
        f.call('plan', {'plan_ref': f.ref('consumer-plan.json', consumer_plan)}, role='spec-designer', module='M002')
        f.call('decision', {'decision_id': 'D2', 'decision': 'approved', 'module_id': 'M002',
                            'subject_sha256': digest(consumer_plan), 'human_source_ref': f.ref('d2.md', 'Approve consumer plan')},
               role='host', module=None)
        f.call('freeze', {'decision_id': 'D2'}, module='M002')
        f.implement('M002', 'I2')
        accepted = f.verify_module('M002', 'T2', consume=True)['paths'][0]
        f.call('suspend', {'kind': 'human', 'reason': 'Decide consumer-only behavior', 'owner': 'human',
                           'root_cause': {'category': 'spec', 'summary': 'consumer assumption', 'confidence': 'confirmed',
                                          'owner': 'human', 'next_action': 'ask'}}, module='M002')
        blocker = copy.deepcopy(f.state()['modules']['M002']['blocked'])
        ref = f.ref('provider-change.md', 'Update provider implementation guidance')
        f.call('change', {'request_ref': ref, 'impact_ref': ref}, module='M001')
        self.assertEqual(f.state()['modules']['M002']['blocked'], blocker)
        self.assertEqual(f.state()['modules']['M002']['phase'], 'waiting-human')
        f.call('decision', {'decision_id': 'CONSUMER', 'decision': 'approved', 'module_id': 'M002',
                            'subject_sha256': digest(blocker), 'human_source_ref': f.ref('consumer.md', 'Decide consumer behavior')},
               role='host', module=None)
        with self.assertRaisesRegex(Rejected, 'dependencies not complete'):
            f.call('resume', {'decision_id': 'CONSUMER'}, module='M002')
        self.assertFalse(f.state()['decisions']['CONSUMER']['consumed'])

        design = next(d for d in provider_plan['definitions'] if d['kind'] == 'design')
        design.update(f.ref('provider-design.md', 'Updated implementation guidance'))
        f.call('plan', {'plan_ref': f.ref('provider-plan.json', provider_plan)}, role='spec-designer', module='M001')
        f.approve(f.state()['modules']['M001']['plan_hash'], 'D3'); f.call('freeze', {'decision_id': 'D3'}, module='M001')
        f.implement('M001', 'I3', shared=2); f.verify_module('M001', 'T3'); f.complete('M001')
        with self.assertRaisesRegex(Rejected, 'current blocker decision'):
            f.call('resume', {}, module='M002')
        self.assertEqual(f.state()['modules']['M002']['blocked'], blocker)
        f.call('resume', {'decision_id': 'CONSUMER'}, module='M002')
        consumer = f.state()['modules']['M002']
        self.assertEqual((consumer['phase'], consumer['blocked']), ('testing', None))
        self.assertNotIn('dependency_revalidation_pending', consumer)
        self.assertTrue(consumer['results']['P2']['stale'])
        self.assertEqual(consumer['results']['P2']['test_run_id'], accepted['test_run_id'])
        retested = f.verify_module('M002', 'T4', consume=True)['paths'][0]
        self.assertEqual(retested['retest_of'], accepted['test_run_id'])
        self.assertEqual(f.state()['modules']['M002']['phase'], 'dod')

    def test_provider_recovery_restarts_at_the_build_and_keeps_identical_inputs(self):
        from test_validation import all_green, next_scope

        provider = {'phase': 'completed', 'freeze_id': 'F1', 'code_baseline': 'provider', 'build_artifacts': []}
        consumer = {'dependencies': ['M001'], 'code_baseline': 'consumer', 'build_baseline': 'consumer',
                    'build_artifacts': [{'path': '/accepted.apk'}],
                    'plan': {'paths': [{'path_id': k, 'kind': k} for k in ('build', 'unit', 'static', 'automation', 'visual')]}}
        s = {'modules': {'M001': provider, 'M002': consumer}}
        inputs = ledger.dependency_validation_inputs(s, consumer)
        consumer['results'] = {p['path_id']: {'quality': 'green-passed', 'code_baseline': 'consumer', 'dependency_inputs': inputs}
                               for p in consumer['plan']['paths']}
        ledger.revalidate_provider_results(s, consumer)
        self.assertTrue(all_green(consumer))
        self.assertEqual(consumer['build_baseline'], 'consumer')
        provider['code_baseline'] = 'updated'
        ledger.revalidate_provider_results(s, consumer)
        self.assertFalse(all_green(consumer))
        self.assertEqual(next_scope(consumer), 'build')
        self.assertEqual(consumer['build_artifacts'], [])
        self.assertTrue(all(row['stale'] for row in consumer['results'].values()))

    def test_code_written_under_a_plan_that_is_given_up_is_carried_to_the_next_one(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        written = f.state()['modules']['M001']['code_files']
        f.call('invalidate', {'reason': 'the split behind this plan was revised'})
        module = f.state()['modules']['M001']
        self.assertEqual((module['phase'], module['code_files'], module['code_baseline'], module['carried_files']), ('specifying', [], None, written))
        self.assertEqual(ledger.status(f.root, 'step', 'M001')['module']['carried_files'], written)  # its planner sees what exists
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('next-plan.json', plan)}, role='spec-designer')
        f.approve(f.state()['modules']['M001']['plan_hash'], 'D2'); f.call('freeze', {'decision_id': 'D2'})
        step = f.state()['next_steps'][0]
        self.assertEqual((step['worker_role'], step['carried_files']), ('implementer', [ref['path'] for ref in written]))  # adjust them, do not start over
        f.implementation(aid='I2')
        self.assertNotIn('carried_files', f.state()['modules']['M001'])  # written again under the new plan: nothing is left over

    def test_a_leaf_that_waited_for_its_provider_goes_on_where_it_was(self):
        revising = {'phase': 'change-review', 'freeze_id': 'F1', 'change_request': {'request_ref': {}}}
        self.assertEqual(ledger.resume_after_provider(revising), 'change-review')  # in the revision of its own SPEC
        self.assertEqual(ledger.resume_after_provider({**revising, 'phase': 'clarifying'}), 'clarifying')
        self.assertEqual(ledger.resume_after_provider({'phase': 'testing', 'freeze_id': 'F1'}), 'frozen')
        written = {'phase': 'testing', 'freeze_id': 'F1', 'plan': {'tasks': [{'task_id': 'T1'}, {'task_id': 'T2'}]}}
        self.assertEqual(ledger.resume_after_provider({**written, 'accepted_task_ids': ['T1', 'T2']}), 'testing')  # every TASK accepted: it tests again
        self.assertEqual(ledger.resume_after_provider({**written, 'phase': 'frozen', 'accepted_task_ids': ['T1']}), 'frozen')  # a TASK still to write
        self.assertEqual(ledger.resume_after_provider({'phase': 'specifying', 'freeze_id': None}), 'specifying')
        self.assertEqual(ledger.resume_after_provider({'phase': 'waiting-human', 'freeze_id': None, 'blocked': {'resume_phase': 'clarifying'}}), 'clarifying')
        module = {**copy.deepcopy(revising), 'revision': 3}
        ledger.await_provider(module)
        self.assertEqual((module['phase'], module['blocked']['resume_phase']), ('waiting-dependency', 'change-review'))


class LessonTests(unittest.TestCase):
    def test_what_an_audit_sent_back_is_a_lesson_about_the_split(self):
        from openspec_projection import build_lessons
        issue = {'kind': 'defect', 'summary': 'two slices write the same screen', 'applies_to': ['M010', 'M001'], 'blocks': False,
                 'evidence_refs': [], 'raised_by': {'role': 'global-orchestrator'}, 'resolved': {'M001': {}},
                 'traced_from': {'batch_id': 'B1', 'finding_id': 'F1', 'source_module_id': 'M002'}}
        state = {'run_id': 'demo', 'modules': {}, 'issues': {'TRACE-B1-F1': issue, 'NOTE': {**issue, 'traced_from': None}}}
        entry, = [row for row in build_lessons(state, 7)['entries'] if row['kind'] == 'boundary-conflict']
        self.assertEqual((entry['status'], entry['module_id'], entry['affected_modules'], entry['summary']),
                         ('pending', 'M002', ['M010', 'M001'], 'two slices write the same screen'))
        issue['resolved']['M010'] = {}
        self.assertEqual([row['status'] for row in build_lessons(state, 8)['entries'] if row['kind'] == 'boundary-conflict'], ['resolved'])

    def test_a_revised_split_is_harvested_when_it_happens(self):
        self.assertEqual(ledger.RESLICED, ('redecompose-accept', 'revise-run', 'audit-route-batch'))
        calls = []
        import experience
        original = experience.auto_harvest
        experience.auto_harvest = lambda root, force=False: calls.append(force) or {'entries': 0}
        self.addCleanup(setattr, experience, 'auto_harvest', original)
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); f.split(); f.global_plan()
        self.assertEqual(calls, [])  # a first split is not a lesson yet
        f.call('realloc-request', {'reason': 'the slice needs another write path', 'evidence_refs': [f.ref('need.md', 'read the source')]}, module='M001')
        f.call('redecompose', {'plan_ref': f.ref('resplit.json', f.proposal())}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('resplit-review.md', 'reviewed')}, role='global-orchestrator', module='M010')
        self.assertEqual(calls, [True])  # harvested at once, whether or not the run ever settles


if __name__ == '__main__':
    unittest.main()
