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
    """A run whose first planner submits a plan with a mark left in it three times, each time from another file, before the
    plan it meant: one rule met three times."""
    refused = 0

    def model_turn(self, step):
        f = self.f
        if step.get('operation') == 'plan' and step.get('module_id') == 'M011' and not self.refused:
            for n in range(3):
                with self.assertRaises(Rejected):
                    f.call('plan', {'plan_ref': f.ref('half-plan-%d.json' % n, {'tasks': '[[待写：任务]]'})}, role='spec-designer', module='M011')
            self.refused = 3
            self.sibling = [s for s in f.state()['next_steps'] if s['module_id'] != 'M011' and s.get('operation') == 'plan']
        super().model_turn(step)

    def next_run(self):
        """The project's next task, prepared: what the first one learned is in its snapshot."""
        prepared = pc.prepare(self.t.config_root, (self.f.base / '.sdd-runs/demo2').resolve(), {'schema_version': 1, 'project_id': 'demo',
                              'request_id': 'prepare-2', 'run_id': 'demo2', 'source_ref': self.f.ref('user-run-2.md', 'Second task')},
                              {'role': 'host', 'instance_id': 'host'})
        ref = pc.verify_snapshot(prepared['project_context_ref'])['source_refs']['experience_ref']
        self.store = Path(pc.verify_snapshot(prepared['project_context_ref'])['source_paths']['experience_ref']).parent
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
        self.assertEqual(lesson['rule'], 'unfilled skeleton field left in <file>')
        self.assertEqual(lesson['root_cause'].count('half-plan-'), 3)  # each message it was met with
        self.assertIn('preview --request', lesson['strategy'])
        self.assertTrue(all('/experience/' in ref['path'] or '/.sdd-migration/' in ref['path'] for ref in lesson['evidence_refs']))  # kept by the store
        self.assertFalse([r for r in experience.candidates(index, module, step=('submit', 'implementer')) if r['kind'] == 'gate-rejection'])

    def test_a_rule_one_leaf_was_refused_by_reaches_the_leaf_planning_beside_it_in_the_same_run(self):
        self.walk(80)
        (step,) = self.sibling
        met = [r for r in step['lesson_candidates'] if r['kind'] == 'run-gate']
        self.assertEqual([r['summary'] for r in met], ['M011: unfilled skeleton field left in <file>'])  # one row for the rule, not one per file
        self.assertTrue(met[0]['applicability'].startswith('plan × spec-designer'))
        self.assertEqual(read_json(check_ref(met[0]['lesson_ref']))['attempts'], 3)

    def test_the_package_feedback_kept_beside_the_store_counts_what_the_run_holds(self):
        import workflow_cost
        self.walk(80)
        self.next_run()
        report = json.loads((self.store / 'package-feedback.json').read_text())
        (sha, runs), = report['packages'].items()
        (rid, row), = runs.items()
        run_root = Path(self.f.state()['run_root'])
        events = workflow_cost.journal(run_root)
        self.assertEqual(sha, self.f.state().get('package_sha') or 'unpinned')
        self.assertEqual(row['model_turns'], sum(map(workflow_cost.model_turn, events)))
        self.assertEqual([(k, n) for k, n in row['refusals'].items() if k.startswith('plan × spec-designer')][0][1], 3)
        self.assertEqual(row['max_card_bytes'], max(p.stat().st_size for p in (run_root / 'reports/reading').glob('*.md')))
        self.assertEqual(row['slicing']['leaves'], len(self.f.state()['modules']))
        self.assertIn(rid, (self.store / 'package-feedback.md').read_text())
        self.assertNotIn('feedback', json.dumps(self.next_run()['runs']))  # the planners' index does not carry it

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


class RuleTests(unittest.TestCase):
    def test_one_rule_reads_the_same_whatever_ids_and_paths_its_message_names(self):
        from progress_signals import rule
        self.assertEqual(rule('missing file: /work/runs/r1/staging/plan.json'), rule('missing file: /other/runs/r2/staging/plan.json'))
        self.assertEqual(rule('unknown reference id C003; the document lists C001, C002'), 'unknown reference id <id>; the document lists <id>…')
        self.assertNotEqual(rule('missing file: /a/plan.json'), rule('principal role denied'))
        one = {'operation': 'plan', 'actor_role': 'spec-designer', 'root_cause': 'missing file: /work/r1/plan.json'}
        self.assertEqual(experience.gate_key(one), experience.gate_key({**one, 'root_cause': 'missing file: /work/r2/plan.json'}))


class EffectivenessTests(unittest.TestCase):
    """A lesson's place among the offered ones follows what happened after it was offered."""
    def setUp(self):
        import tempfile, shutil
        self.run = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.run, True)

    def lesson(self, name, reason):
        body = {'kind': 'gate-rejection', 'operation': 'plan', 'actor_role': 'spec-designer', 'root_cause': reason,
                'summary': 'plan by spec-designer refused 3 times: ' + reason}
        path = self.run / (name + '.json'); path.write_text(json.dumps(body))
        from contracts import file_ref
        return body, {'kind': 'gate-rejection', 'summary': body['summary'], 'applicability': 'plan × spec-designer × x', 'lesson_ref': file_ref(path)}

    def test_a_card_handed_with_lessons_records_them_and_the_harvest_tells_which_refusal_came_back(self):
        import reading
        back, row_back = self.lesson('back', 'unfilled skeleton field left in plan.json')
        gone, row_gone = self.lesson('gone', 'the plan names no test paths')
        reading.render([], self.run / 'reports/reading', lessons=[row_back, row_gone])
        self.assertEqual(len(json.loads((self.run / 'reports/lessons-offered.json').read_text())), 2)
        (self.run / 'reports/rejections').mkdir(parents=True)
        (self.run / 'reports/rejections/r.json').write_text(json.dumps({'operation': 'plan', 'actor_role': 'spec-designer', 'reason': back['root_cause'], 'attempts': 1}))
        self.assertEqual(experience.effects(self.run), {experience.gate_key(back): True, experience.gate_key(gone): False})

    def test_a_lesson_met_again_in_two_runs_goes_last_and_one_that_held_goes_first(self):
        back, row_back = self.lesson('back', 'unfilled skeleton field left in plan.json')
        held, row_held = self.lesson('held', 'the plan names no test paths')
        entries = [{**row_back, **{k: back[k] for k in ('operation', 'actor_role', 'root_cause')}},
                   {**row_held, **{k: held[k] for k in ('operation', 'actor_role', 'root_cause')}}]
        index = {'runs': {'r1': {'entries': entries}, 'r2': {'entries': entries}},
                 'effect': {experience.gate_key(back): {'offered': 2, 'recurred': 2}, experience.gate_key(held): {'offered': 2, 'recurred': 0}}}
        rows = experience.gate_rows(index, ('plan', 'spec-designer'))
        self.assertEqual([r['summary'] for r in rows], [held['summary'], back['summary']])
        self.assertEqual(rows[-1]['effect'], {'offered': 2, 'recurred': 2})  # kept and shown, never deleted
        store = {'runs': {}, 'effect': {experience.gate_key(back): {'runs': {'r1': True, 'r2': True}}}}
        self.assertEqual(experience.planning_view(store)['effect'][experience.gate_key(back)], {'offered': 2, 'recurred': 2})


if __name__ == '__main__':
    unittest.main()
