"""A file of the workflow package is not evidence of a run: its rules reach a role by card section, its hash changes with the package."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reading
from contracts import Rejected, file_ref
import test_issues


class PackageNotEvidenceTests(unittest.TestCase):
    def test_a_package_file_cited_as_evidence_is_refused(self):
        t = test_issues.IssueTests(); t.setUp(); self.addCleanup(t.doCleanups)
        rule = file_ref(reading.PACKAGE / 'AGENTS.md')
        with self.assertRaisesRegex(Rejected, 'package file is not evidence'):
            t.raise_issue(evidence_refs=[rule])
        self.assertNotIn('I1', t.f.state().get('issues', {}))
        self.assertEqual(reading.read_hint('a package file is not evidence: the card names the rule by its section')['section'], '总则')


if __name__ == '__main__':
    unittest.main()
