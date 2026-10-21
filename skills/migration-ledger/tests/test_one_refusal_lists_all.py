"""A refused request lists the request's other problems with its first, and any request can be previewed read-only, so
an author fixes them in one round instead of meeting them one refusal at a time."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_ledger
from contracts import Rejected, require, surveying

GO = {'role': 'global-orchestrator', 'instance_id': 'global-orchestrator'}


class OneRefusalListsAllTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(methodName='runTest'); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def request(self, payload):
        s = ledger.read_events(self.f.root)[0]
        return {'schema_version': 1, 'request_id': 'r-many', 'run_id': 'demo', 'module_id': None,
                'expected_revision': s['revision'], 'operation': 'register', 'payload': payload}

    def test_a_refusal_carries_the_other_problems_of_the_same_request(self):
        payload = {'module_id': 'M002', 'case_ids': ['C9'], 'dependencies': ['M999'], 'write_paths': ['/elsewhere/m2']}
        events = len(ledger.read_events(self.f.root)[1])
        with self.assertRaisesRegex(Rejected, 'register dependencies first') as caught:
            ledger.apply(self.f.root, self.request(payload), GO)
        self.assertEqual(caught.exception.further, ['unknown global case', 'write scope outside target'])
        record = json.loads((self.f.root / 'reports/rejected-operation.json').read_text())
        self.assertEqual([row['reason'] for row in record['further']], caught.exception.further)
        self.assertEqual(len(ledger.read_events(self.f.root)[1]), events)  # the survey keeps nothing
        self.assertNotIn('M002', ledger.read_events(self.f.root)[0]['modules'])

    def test_any_request_can_be_previewed_and_a_sound_one_previews_clean(self):
        events = len(ledger.read_events(self.f.root)[1])
        bad = ledger.preview_request(self.f.root, self.request({'module_id': 'M002', 'case_ids': ['C9'], 'dependencies': [],
                                                                 'write_paths': ['/elsewhere/m2']}), GO)
        self.assertEqual((bad['refused']['reason'], [row['reason'] for row in bad['further']]),
                         ('unknown global case', ['write scope outside target']))
        good = ledger.preview_request(self.f.root, self.request({'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': [],
                                                                  'write_paths': [str(self.f.target / 'm2')]}), GO)
        self.assertEqual((good['refused'], good['further']), (None, []))
        self.assertEqual(len(ledger.read_events(self.f.root)[1]), events)

    def test_outside_a_survey_a_check_still_refuses(self):
        with self.assertRaisesRegex(Rejected, 'first'):
            require(False, 'first')
        with surveying() as found:
            require(False, 'first'); require(False, 'second'); require(False, 'first')
        self.assertEqual(found, ['first', 'second'])


if __name__ == '__main__':
    unittest.main()
