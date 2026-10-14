"""A role's drafts, probes and logs stay in its scratch/: the Ledger neither archives nor accepts them as evidence, and the
closing report says how much of staging no event cites."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import migration_report
import workflow_cost
from contracts import Rejected, file_ref
import test_issues


class ScratchTests(unittest.TestCase):
    def setUp(self):
        self.t = test_issues.IssueTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def staged(self, rel, text):
        p = self.f.root / 'staging/spec-designer/REQ' / rel
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        return p

    def test_a_scratch_file_is_not_evidence(self):
        probe = self.staged('scratch/probe.log', 'x' * 50)
        with self.assertRaisesRegex(Rejected, 'scratch file is not evidence'):
            self.t.raise_issue(evidence_refs=[file_ref(probe)])
        self.assertNotIn('I1', self.f.state().get('issues', {}))
        self.assertFalse(any(p.is_file() and p.read_bytes() == b'x' * 50 for p in (self.f.root / 'artifacts').glob('*')))

    def test_the_report_counts_what_staging_holds_against_what_events_cite(self):
        cited = self.staged('review.md', 'c' * 300)
        self.staged('draft-notes.md', 'l' * 100); self.staged('scratch/probe.log', 's' * 600)
        self.t.raise_issue(evidence_refs=[file_ref(cited)])
        usage = workflow_cost.staging_usage(self.f.root, workflow_cost.journal(self.f.root))
        self.assertEqual(usage, {'bytes': 400, 'cited_bytes': 300, 'uncited_share': 0.25, 'scratch_bytes': 600})
        report = migration_report.build(self.f.root, self.f.state(), 1)
        self.assertEqual(report['staging_usage'], usage)
        self.assertIn('未被任何事件引用 25%', migration_report.render(report))


if __name__ == '__main__':
    unittest.main()
