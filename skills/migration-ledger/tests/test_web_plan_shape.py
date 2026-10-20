"""A web PATH is frozen in the shape the built-in web Main runs: a step or predicate it could not perform is refused when
the plan is submitted, not discovered when the test is dispatched."""
import copy
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected
import test_validation as tv
import test_spec_closure

STEPS = [{'action': 'goto', 'url': 'http://127.0.0.1:1/index.html'}, {'action': 'fill', 'selector': '#user', 'text': 'ann'}, {'action': 'click', 'selector': '#submit'}]
ASSERTION = {'assertion_id': 'A1', 'expected': True, 'description': 'the list heading reads Items', 'matcher': 'exact', 'verification': 'dom', 'after_step': 3,
             'predicate': {'kind': 'text', 'selector': '#heading', 'equals': 'Items'}}


class WebPlanShapeTests(unittest.TestCase):
    def setUp(self):
        t = test_spec_closure.SpecClosureTests(); t.setUp(); self.addCleanup(t.doCleanups)  # a split-testing plan: build, unit, static and the case path
        self.f = t.f; self.plan = self.f.plan()
        self.web = next(p for p in self.plan['paths'] if p['path_id'] == 'P1')
        self.web.pop('command', None); self.web.pop('unit_report', None)
        self.web.update(platform='web', task_type='test', steps=copy.deepcopy(STEPS), expected_assertions=[copy.deepcopy(ASSERTION)])

    def test_a_well_formed_web_path_passes_and_a_malformed_one_is_refused_at_plan_time(self):
        tv.plan_check(self.plan, str(self.f.target))
        for change, message in ((lambda p: p['steps'].append({'action': 'scroll', 'dy': 300}), 'step 4: a web step is an object whose action is one of'),
                                (lambda p: p['steps'].insert(0, {'action': 'wait', 'ms': 100}), 'the first step opens the page: goto'),
                                (lambda p: p['expected_assertions'][0].update(after_step=9), 'A1: after_step must reference a frozen step'),
                                (lambda p: p['expected_assertions'][0].update(matcher='semantic'), 'A1: the web Main matches exactly'),
                                (lambda p: p['expected_assertions'][0]['predicate'].pop('equals'), 'A1: one of equals, contains, matches'),
                                (lambda p: p['expected_assertions'][0].update(verification='one_image_assert'), 'A1: verification is dom')):
            plan = copy.deepcopy(self.plan); change(next(p for p in plan['paths'] if p['path_id'] == 'P1'))
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, 'web PATH P1: ' + message):
                tv.plan_check(plan, str(self.f.target))

    def test_a_web_path_that_froze_a_command_is_an_in_process_path_and_is_left_to_its_command(self):
        self.web['command'] = {'argv': ['/usr/bin/true'], 'cwd': str(self.f.target), 'timeout_seconds': 10, 'selection_ref': self.f.ref('sel.md', 'x')}
        self.web['steps'] = ['free text']  # not the Main's shape, and not the Main's business
        tv.plan_check(self.plan, str(self.f.target))


if __name__ == '__main__':
    unittest.main()
