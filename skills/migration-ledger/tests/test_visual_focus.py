"""A visual-only diagnosis names at most two actionable issues, so a bounded repair round stays focused."""
import unittest

import test_ledger  # sets the scripts path
import ledger
from contracts import Rejected


def module(*kinds):
    paths = [{'path_id': f'P{i}', 'kind': kind} for i, kind in enumerate(kinds)]
    return {'stale': False, 'plan': {'paths': paths},
            'results': {p['path_id']: {'quality': 'red-bug'} for p in paths}}


def issue(**over):
    return {'area': 'bottom bar', 'problem': 'anchored 24dp too high', 'severity': 'high',
            'evidence_ref': 'side-by-side.png', **over}


class VisualFocusTests(unittest.TestCase):
    def test_visual_only_failures_need_one_or_two_structured_issues(self):
        m = module('visual')
        for bad in ({}, {'visual_issues': []}, {'visual_issues': [issue(), issue(area='header'), issue(area='list')]},
                    {'visual_issues': [issue(severity='blocker')]}, {'visual_issues': [{'area': 'header'}]}):
            with self.subTest(bad=bad), self.assertRaisesRegex(Rejected, 'visual'):
                ledger.diagnosis_focus(m, bad)
        ledger.diagnosis_focus(m, {'visual_issues': [issue(), issue(area='header', severity='medium')]})

    def test_functional_or_mixed_failures_keep_the_plain_diagnosis(self):
        ledger.diagnosis_focus(module('automation'), {})
        ledger.diagnosis_focus(module('visual', 'automation'), {})  # behaviour first: not a visual-only round
        green = module('visual'); green['results']['P0']['quality'] = 'green-passed'
        ledger.diagnosis_focus(green, {})


if __name__ == '__main__':
    unittest.main()
