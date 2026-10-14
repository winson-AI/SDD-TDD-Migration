"""A fact is kept for the trace and owed to nobody; a step lists a few open issues; standing rules are delivered once."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import issues
import ledger
from contracts import Rejected
import test_issues


class IssueHygieneTests(unittest.TestCase):
    def setUp(self):
        self.t = test_issues.IssueTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def test_a_fact_is_recorded_and_settled_at_once(self):
        t = self.t
        t.raise_issue('F1', kind='fact', summary='the legacy timer is owned by the phone screen')
        issue = self.f.state()['issues']['F1']
        self.assertEqual(issue['resolved']['M001']['recorded'], True)
        self.assertEqual(t.step()['open_issues'], [])
        issues.settled(self.f.state(), 'M001')  # nothing is owed
        with self.assertRaisesRegex(Rejected, 'not open for this module'):
            t.settle('F1')
        with self.assertRaisesRegex(Rejected, 'cannot block'):
            t.raise_issue('F2', kind='fact', blocks=True)

    def test_a_step_lists_the_blocking_issues_first_then_the_newest_ten(self):
        t = self.t
        for n in range(12):
            t.raise_issue(f'N{n:02d}', kind='need')
        t.raise_issue('STOP', kind='defect', blocks=True, summary='the build cannot pass as planned')
        view = t.step()
        self.assertEqual(view['open_issue_count'], 13)
        listed = [row['issue_id'] for row in view['open_issues']]
        self.assertEqual(listed, ['STOP'] + [f'N{n:02d}' for n in range(11, 2, -1)])
        self.assertEqual(ledger.status(self.f.root, 'cursor')['open_issues'], {'M001': 13})

    def test_standing_rules_ride_a_step_once(self):
        t = self.t
        t.raise_issue('RULE', role='host', kind='standing', summary='where a case disagrees with the legacy source, follow the source')
        at_rule = self.f.state()['last_sequence']
        t.raise_issue('N1', kind='need')
        self.assertEqual([row['issue_id'] for row in t.step()['standing_rules']], ['RULE'])  # a first read
        self.assertEqual([row['issue_id'] for row in ledger.status(self.f.root, 'step', 'M001', since=at_rule - 1)['standing_rules']], ['RULE'])
        compact = ledger.status(self.f.root, 'step', 'M001', since=at_rule)['standing_rules']
        self.assertEqual((compact['count'], len(compact['sha256'])), (1, 64))


if __name__ == '__main__':
    unittest.main()
