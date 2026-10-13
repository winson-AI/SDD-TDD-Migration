"""A role that has several issues to record says them in one event, settles several in one event, and what a plan, a
review or a result answers is settled with it: no separate resolution, no resubmission to bind it."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_issues
from contracts import Rejected, digest


class IssueBatchTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_issues.IssueTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = t.f

    def entry(self, iid, kind='need', applies=('M001',)):
        return {'issue_id': iid, 'kind': kind, 'summary': 'what ' + iid + ' asks', 'applies_to': list(applies)}

    def test_one_request_records_several_issues_or_none(self):
        f = self.f
        events = len(ledger.read_events(f.root)[1])
        f.call('issue', {'issues': [self.entry('N1'), self.entry('N2', 'gap'), self.entry('F1', 'fact')]}, role='spec-designer', module=None)
        self.assertEqual(len(ledger.read_events(f.root)[1]), events + 1)  # one event
        self.assertEqual(sorted(f.state()['issues']), ['F1', 'N1', 'N2'])
        with self.assertRaisesRegex(Rejected, 'issue_id must be new'):
            f.call('issue', {'issues': [self.entry('N3'), self.entry('N1')]}, role='spec-designer', module=None)
        self.assertNotIn('N3', f.state()['issues'])  # nothing recorded unless all of them stand

    def test_one_request_settles_several_issues(self):
        f = self.f
        f.call('issue', {'issues': [self.entry('N1'), self.entry('N2')]}, role='spec-designer', module=None)
        answer = f.ref('answers.md', 'the plan answers both')
        f.call('issue-resolve', {'evidence_ref': answer, 'module_id': 'M001', 'resolutions': [{'issue_id': 'N1'}, {'issue_id': 'N2'}]}, role='spec-designer', module=None)
        self.assertEqual([i for i, it in f.state()['issues'].items() if 'M001' in it['resolved']], ['N1', 'N2'])
        with self.assertRaisesRegex(Rejected, 'not open'):
            f.call('issue-resolve', {'evidence_ref': answer, 'module_id': 'M001', 'resolutions': [{'issue_id': 'N1'}]}, role='spec-designer', module=None)

    def test_a_plan_settles_what_it_cites_and_a_review_too(self):
        f = self.f
        f.call('issue', {'issues': [self.entry('N1'), self.entry('N2'), self.entry('S1', 'standing')]}, role='module-orchestrator', module=None)
        plan = f.plan(); ref = f.ref('plan.json', plan)
        with self.assertRaisesRegex(Rejected, 'neither a standing rule'):
            f.call('plan', {'plan_ref': ref, 'resolves': ['S1']}, role='spec-designer')
        f.call('plan', {'plan_ref': ref, 'resolves': ['N1']}, role='spec-designer')
        resolved = f.state()['issues']['N1']['resolved']['M001']
        self.assertEqual((resolved['evidence_ref'], resolved['by']['role']), (ref, 'spec-designer'))  # the plan itself is the evidence
        self.assertEqual([g['issue_id'] for g in ledger.status(f.root, 'step', 'M001')['open_issues']], ['N2'])
        f.approve(digest(plan), 'D1')
        review = f.ref('review.json', {'schema_version': 1, 'plan_hash': f.state()['modules']['M001']['plan_hash'], 'reviewer_instance_id': 'module-orchestrator',
                                       'semantic_change': False, 'authorization_change': False, 'unresolved_questions': [], 'recorded_issue_ids': [],
                                       'reason': 'reviewed; N2 is answered by the plan', 'evidence_refs': [f.ref('review.md', 'checked against the source')]})
        f.call('plan-review', {'review_ref': review, 'resolves': ['N2']}, role='module-orchestrator')
        self.assertEqual(f.state()['issues']['N2']['resolved']['M001']['evidence_ref'], review)
        self.assertEqual(ledger.status(f.root, 'step', 'M001')['open_issues'], [])


if __name__ == '__main__':
    unittest.main()
