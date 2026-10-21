"""A build follows the platforms its PATHs verify, and a failure of the target project's own baseline goes to the
Auditor with its evidence instead of a repair round, a person or a round trip to the GO."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_validation as tv
import workflow


def plan(argv, *platforms):
    paths = [{'path_id': 'UNIT-1', 'kind': 'unit', 'command': {'argv': argv}}]
    paths += [{'path_id': f'P{i}', 'kind': 'automation', **({'platform': pf} if pf else {})} for i, pf in enumerate(platforms)]
    return {'paths': paths}


class BuildScopeTests(unittest.TestCase):
    def test_an_aggregate_task_is_owed_only_when_no_path_verifies_a_native_target(self):
        unit = lambda p: next(row for row in p['paths'] if row['kind'] == 'unit')
        every = plan(['/t/gradlew', ':demo:allTests'], None, 'android')
        self.assertEqual(tv.aggregate_task(unit(every), every), ':demo:allTests')
        self.assertEqual(tv.verified_platforms(every), {'jvm', 'android'})
        own = plan(['/t/gradlew', ':demo:testDebugUnitTest'], None)
        self.assertIsNone(tv.aggregate_task(unit(own), own))
        ios = plan(['/t/gradlew', ':demo:allTests'], 'ios')
        self.assertIsNone(tv.aggregate_task(unit(ios), ios))  # a PATH runs on iOS: linking it is the leaf's business
        other = plan(['/usr/bin/make', 'test'], None)
        self.assertIsNone(tv.aggregate_task(unit(other), other))  # only Gradle tasks are known to fan out over targets

    def test_a_confirmed_target_baseline_failure_defers_to_the_auditor(self):
        m = {'diagnosis': {'root_cause': {'category': 'target-baseline', 'confidence': 'confirmed',
                                          'summary': 'iOS link symbol missing in the target framework'}}, 'results': {}}
        self.assertEqual(workflow.defer_reason(m)['category'], 'target-baseline')
        m['diagnosis']['root_cause']['category'] = 'code'
        self.assertIsNone(workflow.defer_reason(m))


if __name__ == '__main__':
    unittest.main()
