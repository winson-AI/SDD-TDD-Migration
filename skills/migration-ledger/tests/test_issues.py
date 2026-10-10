"""Problems are recorded and work goes on: an issue is addressed to the modules it concerns, shows on their steps until
each cites what settled it, and holds nothing unless it was raised as blocking - then only the freeze of its module."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_ledger
from contracts import Rejected, digest


class IssueTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()

    def raise_issue(self, iid='I1', role='module-orchestrator', **fields):
        payload = {'issue_id': iid, 'kind': 'defect', 'summary': 'the mask never reaches the renderer', 'applies_to': ['M001'], **fields}
        return self.f.call('issue', payload, role=role, module=None)

    def settle(self, iid='I1', mid='M001', role='spec-designer'):
        self.f.call('issue-resolve', {'issue_id': iid, 'module_id': mid, 'evidence_ref': self.f.ref('answer-' + iid + '.md', 'the plan names the keyboard type')},
                    role=role, module=None)

    def step(self):
        return ledger.status(self.f.root, 'step', 'M001')

    def test_an_issue_shows_on_the_step_of_the_module_it_is_addressed_to_until_that_module_settles_it(self):
        proof = self.f.ref('review.md', 'read the text field down to the rendering layer')
        self.raise_issue(evidence_refs=[proof])
        view = self.step()
        self.assertEqual(view['open_issues'], [{'issue_id': 'I1', 'kind': 'defect', 'summary': 'the mask never reaches the renderer',
                                                'blocks': False, 'evidence_refs': [proof], 'open_for': ['M001']}])
        self.assertEqual(ledger.status(self.f.root, 'cursor')['open_issues'], {'M001': 1})
        self.settle()
        self.assertEqual((self.step()['open_issues'], ledger.status(self.f.root, 'cursor')['open_issues']), ([], {}))
        resolved = self.f.state()['issues']['I1']['resolved']['M001']
        self.assertEqual(resolved['by'], {'role': 'spec-designer', 'instance_id': 'spec-designer'})  # who settled it, and with what

    def test_recording_an_issue_moves_no_revision_and_needs_none(self):
        before = self.f.state()
        self.f.call('issue', {'issue_id': 'I1', 'kind': 'need', 'summary': 'the consumer needs a result action', 'applies_to': ['M001']},
                    role='spec-designer', module=None, request={
                        'schema_version': 1, 'request_id': 'no-revision', 'run_id': 'demo', 'module_id': None, 'operation': 'issue',
                        'payload': {'issue_id': 'I1', 'kind': 'need', 'summary': 'the consumer needs a result action', 'applies_to': ['M001']}})
        after = self.f.state()
        self.assertEqual((after['revision'], after['modules']['M001']['revision']), (before['revision'], before['modules']['M001']['revision']))
        self.assertEqual(after['last_sequence'], before['last_sequence'] + 1)  # still an event of the journal
        plan = self.f.plan()  # a request prepared before the issue was recorded is still good
        self.f.call('plan', {'plan_ref': self.f.ref('plan.json', plan)}, role='spec-designer')

    def test_a_recorded_issue_holds_nothing_and_a_blocking_one_holds_the_freeze_of_its_module(self):
        plan = self.f.plan()
        self.f.call('plan', {'plan_ref': self.f.ref('plan.json', plan)}, role='spec-designer')
        self.f.approve(digest(plan), 'D1')
        self.raise_issue('NOTE')
        self.raise_issue('STOP', blocks=True, summary='as planned the password is shown in clear text')
        with self.assertRaisesRegex(Rejected, 'blocking issue open for this module: STOP'):
            self.f.call('freeze', {'decision_id': 'D1'})
        self.settle('STOP')
        self.f.call('freeze', {'decision_id': 'D1'})  # the recorded one is still open and goes on with the module
        self.assertEqual([row['issue_id'] for row in self.step()['open_issues']], ['NOTE'])

    def test_a_standing_rule_is_listed_for_its_modules_and_is_never_settled(self):
        self.raise_issue('RULE', role='host', kind='standing', summary='where a case disagrees with the legacy source, follow the source')
        view = self.step()
        self.assertEqual(([row['issue_id'] for row in view['standing_rules']], view['open_issues']), (['RULE'], []))
        with self.assertRaisesRegex(Rejected, 'not a standing rule'):
            self.settle('RULE')
        with self.assertRaisesRegex(Rejected, 'cannot block'):
            self.raise_issue('RULE2', kind='standing', blocks=True)

    def test_an_issue_addressed_to_several_modules_is_owed_by_each_and_reaches_the_report(self):
        import json
        import test_decomposition
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); f.split(); f.global_plan()
        f.call('issue', {'issue_id': 'MARGIN', 'kind': 'need', 'summary': 'who adds the page margin', 'applies_to': ['M001', 'M002', 'M010']},
               role='module-orchestrator', module=None)
        f.call('issue-resolve', {'issue_id': 'MARGIN', 'module_id': 'M001', 'evidence_ref': f.ref('margin.md', 'the screen adds it')},
               role='spec-designer', module=None)
        cursor = ledger.status(f.root, 'cursor')
        self.assertEqual(cursor['open_issues'], {'M002': 1, 'M010': 1})  # the parent is addressed like any module
        self.assertEqual(ledger.status(f.root, 'step', 'M001')['open_issues'], [])
        self.assertEqual(ledger.status(f.root, 'step', 'M002')['open_issues'][0]['open_for'], ['M002', 'M010'])
        self.assertEqual([row['issue_id'] for row in ledger.status(f.root, 'step')['open_issues']], ['MARGIN'])  # the global step sees all that is open
        state = f.state()
        report = json.loads(Path(state['migration_report']['json']).read_text())
        self.assertEqual([(row['issue_id'], row['open_for']) for row in report['open_issues']], [('MARGIN', ['M002', 'M010'])])
        self.assertIn('| MARGIN | need | M002, M010 | who adds the page margin |', Path(state['migration_report']['markdown']).read_text())

    def test_what_an_issue_must_say(self):
        for fields, message in (({'kind': 'opinion'}, 'issue kind is one of'), ({'summary': ' '}, 'summary required'),
                                ({'applies_to': []}, 'applies_to names'), ({'applies_to': ['M999']}, 'applies_to names'),
                                ({'evidence_refs': [{'path': '/missing', 'sha256': '0' * 64}]}, 'missing file|hash mismatch')):
            with self.subTest(fields=fields), self.assertRaisesRegex(Rejected, message):
                self.raise_issue(**fields)
        self.raise_issue()
        with self.assertRaisesRegex(Rejected, 'issue_id must be new'):
            self.raise_issue()
        with self.assertRaisesRegex(Rejected, 'not open for this module'):
            self.settle(mid='M777')
        self.settle()
        with self.assertRaisesRegex(Rejected, 'not open for this module'):
            self.settle()
        with self.assertRaisesRegex(Rejected, 'incorrect global/module scope'):
            self.f.call('issue', {'issue_id': 'I9', 'kind': 'fact', 'summary': 's', 'applies_to': ['M001']})  # addressed in the payload, not by the request


class CompletionTests(unittest.TestCase):
    """Recorded problems travel with the module through coding and testing; it is done when none is still open."""
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def test_an_open_issue_holds_completion_and_nothing_before_it(self):
        f = self.f
        f.global_plan()
        f.call('issue', {'issue_id': 'CURSOR', 'kind': 'gap', 'summary': 'the cursor size cannot be set', 'applies_to': ['M001']},
               role='implementer', module=None)
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'})
        f.implementation()
        a, result = f.make_test_result()
        f.submit(result, a); f.call('accept', {'assignment_id': 'TEST1'})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')  # planned, frozen, coded and tested with it open
        with self.assertRaisesRegex(Rejected, 'open issues of this module: CURSOR'):
            f.call('complete', {'dod_ref': f.ref('dod.md', 'reviewed')})
        self.assertFalse(f.state()['next_steps'][0]['ready'])
        f.call('issue-resolve', {'issue_id': 'CURSOR', 'module_id': 'M001',
                                 'evidence_ref': f.ref('decision.md', 'the user accepts the system cursor size')}, role='host', module=None)
        f.call('complete', {'dod_ref': f.ref('dod.md', 'reviewed')})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'completed')


class OwedTests(unittest.TestCase):
    """What a plan still owes to fidelity does not stop its leaf: the Ledger records the gap as an issue of that leaf and
    a later plan that answers it settles it. The same check still refuses wherever nothing can carry it."""
    def setUp(self):
        import test_reuse
        self.r = r = test_reuse.ReuseTests(); r.setUp(); self.addCleanup(r.doCleanups)
        r.global_plan()

    def plan(self, covered):
        plan, review, _, _ = self.r.selected_plan()
        plan['paths'].append({'path_id': 'P2', 'name': 'again', 'case_id': 'C1', 'requirement_id': 'R1',
                              'expected_assertions': [{'assertion_id': 'A2', 'expected': 2}]})
        plan['tasks'][0]['path_ids'].append('P2')
        mapping = review['mappings'][0]
        mapping['path_ids'] = ['P1', 'P2']
        if covered:
            mapping['fidelity']['scenarios'].append({**mapping['fidelity']['scenarios'][0], 'scenario_id': 'FID2', 'path_id': 'P2', 'assertion_ids': ['A2']})
        self.r.save_review(plan, review)
        return plan

    def submit(self, covered):
        self.r.call('plan', {'plan_ref': self.r.ref('plan-%s-%d.json' % (covered, self.r.n), self.plan(covered))}, role='spec-designer')

    def open(self):
        return ledger.status(self.r.root, 'step', 'M001')['open_issues']

    def test_a_plan_that_owes_fidelity_coverage_is_accepted_frozen_and_the_gap_is_recorded_once(self):
        r = self.r
        import reuse
        state = r.state()
        with self.assertRaisesRegex(Rejected, 'fidelity must cover every mapped path'):  # a rehearsal outside the Ledger still refuses
            reuse.validate_plan(self.plan(False), state['modules']['M001'], reuse.sources(state), state['modules'], state['legacy_root'])
        self.submit(False)
        gap, = self.open()
        self.assertEqual((gap['kind'], gap['summary'], gap['blocks'], gap['open_for']), ('gap', 'fidelity must cover every mapped path', False, ['M001']))
        self.assertRegex(gap['issue_id'], '^OWED-M001-[0-9a-f]{8}$')
        self.assertEqual(r.state()['issues'][gap['issue_id']]['raised_by'], {'role': 'ledger', 'instance_id': 'ledger'})
        with self.assertRaisesRegex(Rejected, 'settled by a plan that no longer owes it'):
            r.call('issue-resolve', {'issue_id': gap['issue_id'], 'module_id': 'M001', 'evidence_ref': r.ref('note.md', 'later')},
                   role='spec-designer', module=None)
        r.approve(r.state()['modules']['M001']['plan_hash'], 'D1'); r.call('freeze', {'decision_id': 'D1'})
        self.assertEqual(r.state()['modules']['M001']['phase'], 'frozen')
        self.assertEqual([row['issue_id'] for row in self.open()], [gap['issue_id']])  # judged again at freeze, recorded once
        r.assign('implementer', 'I1')  # and the leaf is coded with it owed
        self.assertEqual(r.state()['modules']['M001']['phase'], 'implementing')

    def test_a_later_plan_that_answers_the_gap_settles_it_and_one_that_owes_it_again_reopens_it(self):
        r = self.r
        self.submit(False)
        iid = self.open()[0]['issue_id']
        self.submit(True)
        self.assertEqual(self.open(), [])
        settled = r.state()['issues'][iid]['resolved']['M001']
        self.assertEqual((settled['by']['role'], settled['plan_hash']), ('ledger', r.state()['modules']['M001']['plan_hash']))
        self.submit(False)
        self.assertEqual([row['issue_id'] for row in self.open()], [iid])

    def test_the_collector_is_the_requests_own(self):
        import contracts
        with self.assertRaisesRegex(Rejected, 'owed'):
            contracts.owed(False, 'owed')
        with contracts.carrying() as outer:
            contracts.owed(False, 'first')
            with contracts.carrying(False):  # a request that allocates: refused, not carried
                with self.assertRaisesRegex(Rejected, 'second'):
                    contracts.owed(False, 'second')
            with contracts.carrying() as inner:
                contracts.owed(False, 'third'); contracts.owed(True, 'met')
            self.assertEqual((outer, inner), (['first'], ['third']))
            import threading
            seen = []
            def elsewhere():
                try:
                    contracts.owed(False, 'another thread')
                except Rejected as exc:
                    seen.append(str(exc))
            thread = threading.Thread(target=elsewhere); thread.start(); thread.join()
            self.assertEqual(seen, ['another thread'])  # nothing carries it there
        with self.assertRaisesRegex(Rejected, 'owed'):
            contracts.owed(False, 'owed')


if __name__ == '__main__':
    unittest.main()
