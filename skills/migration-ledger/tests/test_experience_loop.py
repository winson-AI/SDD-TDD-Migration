"""What a run learns reaches the next one: a refusal a role met again and again is abstracted by the Ledger from its record
and the journal, harvested with the run, and offered to the step that submits that operation as that role in the next run
of the project, ahead of other lessons; a lesson whose rule the package no longer has is not offered."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import experience
import ledger
import project_context as pc
import test_continuous_run
from contracts import Rejected, check_ref, read_json


class RefusedThenLearned(test_continuous_run.ContinuousWalk):
    """A run whose first planner submits a plan with a mark left in it three times before the plan it meant."""
    refused = 0

    def model_turn(self, step):
        f = self.f
        if step.get('operation') == 'plan' and step.get('module_id') == 'M011' and not self.refused:
            for _ in range(3):
                with self.assertRaises(Rejected):
                    f.call('plan', {'plan_ref': f.ref('half-plan.json', {'tasks': '[[待写：任务]]'})}, role='spec-designer', module='M011')
            self.refused = 3
        super().model_turn(step)

    def next_run(self):
        """The project's next task, prepared: what the first one learned is in its snapshot."""
        prepared = pc.prepare(self.t.config_root, (self.f.base / '.sdd-runs/demo2').resolve(), {'schema_version': 1, 'project_id': 'demo',
                              'request_id': 'prepare-2', 'run_id': 'demo2', 'source_ref': self.f.ref('user-run-2.md', 'Second task')},
                              {'role': 'host', 'instance_id': 'host'})
        ref = pc.verify_snapshot(prepared['project_context_ref'])['source_refs']['experience_ref']
        return read_json(check_ref(ref))


class ExperienceLoopTests(RefusedThenLearned):
    def test_a_refusal_met_three_times_reaches_the_same_step_of_the_next_run_with_every_field_the_ledger_could_fill(self):
        taken, st = self.walk(80)
        self.assertEqual(st['quality'], 'green-passed')
        index = self.next_run()
        module = self.f.state()['modules']['M011']
        offered = experience.candidates(index, module, step=('plan', 'spec-designer'))
        gate = offered[0]
        self.assertEqual((gate['kind'], gate['runs']), ('gate-rejection', 1))  # first, ahead of the other lessons
        lesson = read_json(check_ref(gate['lesson_ref']))
        self.assertTrue(all(lesson.get(k) for k in experience.ABSTRACT_FIELDS))  # nothing left for a person to abstract
        self.assertEqual(lesson['result'], 'accepted after 3 refusals')
        self.assertIn('preview --request', lesson['strategy'])
        self.assertTrue(all('/experience/' in ref['path'] or '/.sdd-migration/' in ref['path'] for ref in lesson['evidence_refs']))  # kept by the store
        self.assertFalse([r for r in experience.candidates(index, module, step=('submit', 'implementer')) if r['kind'] == 'gate-rejection'])

    def test_a_lesson_whose_rule_left_the_package_is_not_offered(self):
        self.walk(80)
        index = self.next_run()
        stale = copy.deepcopy(index)
        for block in stale['runs'].values():
            for entry in block['entries']:
                if entry['kind'] == 'gate-rejection':
                    entry['read_hint'] = {'ref': entry['read_hint']['ref'], 'section': 'a section this package no longer has'}
        module = self.f.state()['modules']['M011']
        self.assertFalse([r for r in experience.candidates(stale, module, step=('plan', 'spec-designer')) if r['kind'] == 'gate-rejection'])


if __name__ == '__main__':
    unittest.main()
