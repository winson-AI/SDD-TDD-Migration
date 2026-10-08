"""A run remembers what stopped it, and a project may keep its lessons where several workspaces read them."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import experience
import ledger
import openspec_projection
import progress_signals
import project_context as pc
from contracts import check_ref, digest, read_json
import test_decomposition
import test_ledger
import test_project_context


def kinds(lessons, kind):
    return [entry for entry in lessons['entries'] if entry['kind'] == kind]


class WhatStoppedTheRunTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def lessons(self, root=None):
        state = self.f.state()
        return openspec_projection.build_lessons(state, state['last_sequence'], root)

    def test_a_blocker_and_what_released_it_are_remembered(self):
        f = self.f
        f.call('suspend', {'kind': 'human', 'reason': 'need decision', 'root_cause': 'ambiguous input', 'owner': 'human'})
        pending, = kinds(self.lessons(), 'escalation')
        self.assertEqual((pending['status'], pending['module_id'], pending['blocker_kind'], pending['summary']),
                         ('pending', 'M001', 'human', 'need decision'))
        f.approve(f.state()['next_steps'][0]['approval_subject_sha256'], 'RESUME')
        f.call('resume', {'decision_id': 'RESUME'})
        m = f.state()['modules']['M001']
        self.assertIsNone(m['blocked'])
        resolved, = kinds(self.lessons(), 'escalation')
        self.assertEqual((resolved['status'], resolved['root_cause']), ('resolved', 'ambiguous input'))
        self.assertEqual(resolved['resolution_ref'], f.state()['decisions']['RESUME']['human_source_ref'])
        # the module that plans next reads it with its other history
        bound = read_json(check_ref(m['planning_lessons_ref']))['entries']
        self.assertEqual([entry['summary'] for entry in bound if entry['kind'] == 'escalation'], ['need decision'])

    def test_a_freeze_that_took_many_distinct_plans_is_remembered(self):
        f = self.f; f.global_plan()
        for round_ in range(3):
            plan = f.plan(); plan['decision_envelope']['acceptance'] = ['same result', 'draft ' + str(round_)]
            ref = f.ref('plan-%d.json' % round_, plan)
            f.call('plan', {'plan_ref': ref}, role='spec-designer')
            if round_ < 2:
                self.assertEqual(kinds(self.lessons(), 'planning-gap'), [])
        f.call('plan', {'plan_ref': ref}, role='spec-designer')  # the plan the Ledger already holds is not another round
        self.assertEqual(f.state()['modules']['M001']['plan_submissions'], 3)
        gap, = kinds(self.lessons(), 'planning-gap')
        self.assertEqual((gap['reason'], gap['submissions'], gap['module_id']), ('repeated-plan-submission', 3, 'M001'))
        f.approve(f.state()['modules']['M001']['plan_hash'], 'FREEZE')
        f.call('freeze', {'decision_id': 'FREEZE'})
        m = f.state()['modules']['M001']
        self.assertEqual((m['plan_rounds'], m.get('plan_submissions')), ([3], None))
        self.assertEqual(len(kinds(self.lessons(), 'planning-gap')), 1)  # kept after the freeze, counted once

    def test_a_refusal_met_again_and_again_is_remembered_with_the_run_directory(self):
        f = self.f
        for _ in range(3):
            progress_signals.record_rejection(f.root, {'operation': 'accept', 'module_id': 'M001'}, {'role': 'host'},
                                              'unit tests must pass before the static review')
        for _ in range(2):
            progress_signals.record_rejection(f.root, {'operation': 'freeze', 'module_id': 'M001'}, {'role': 'host'}, 'approved scope')
        for _ in range(4):
            progress_signals.record_rejection(f.root, {'operation': 'global-plan', 'module_id': None}, {'role': 'host'},
                                              'global coverage review required')
        self.assertEqual(kinds(self.lessons(), 'gate-rejection'), [])  # the journal alone does not hold refusals
        found = {entry['operation']: entry for entry in kinds(self.lessons(f.root), 'gate-rejection')}
        self.assertEqual(sorted(found), ['accept', 'global-plan'])  # twice is a retry, three times is a lesson
        self.assertEqual((found['accept']['module_id'], found['accept']['attempts'], found['accept']['summary']),
                         ('M001', 3, 'unit tests must pass before the static review'))
        self.assertEqual((found['global-plan'].get('module_id'), found['global-plan']['scope']), (None, 'global'))
        f.call('suspend', {'kind': 'human', 'reason': 'need decision', 'root_cause': 'ambiguous input', 'owner': 'human'})
        state = f.state()
        run = [entry['operation'] for entry in read_json(check_ref(state['lessons_ref']))['entries'] if entry['kind'] == 'gate-rejection']
        leaf = [entry['operation'] for entry in read_json(check_ref(state['modules']['M001']['planning_lessons_ref']))['entries']
                if entry['kind'] == 'gate-rejection']
        self.assertEqual((sorted(run), leaf), (['accept', 'global-plan'], ['accept']))  # a run-level refusal is not every leaf's reading


class SharedStoreTests(unittest.TestCase):
    def harvested(self, project_id, shared):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope()
        project = f.base / '.sdd-migration'; (project / 'runs').mkdir(parents=True, exist_ok=True)
        (project / 'runs/demo.json').write_text(json.dumps({'run_root': str(f.root.resolve()), 'project_id': project_id}))
        if shared:
            (project / 'project-context.json').write_text(json.dumps({'project_id': project_id, 'config': {'experience_root': str(shared)}}))
        return project, experience.harvest(project, f.root)

    def test_a_project_keeps_its_lessons_in_its_own_directory_unless_it_names_a_shared_one(self):
        project, receipt = self.harvested('P001', None)
        self.assertEqual(experience.store(project), (project / 'experience').resolve())
        self.assertEqual((receipt['run_id'], sorted(experience.load(project)['runs'])), ('demo', ['demo']))

    def test_projects_that_share_a_store_keep_their_runs_apart(self):
        first, receipt = self.harvested('P001', None)
        shared = first.parent / 'shared-experience'
        one, receipt_one = self.harvested('P001', shared)
        two, receipt_two = self.harvested('P002', shared)
        self.assertEqual((experience.store(one), experience.store(two)), (shared.resolve(), shared.resolve()))
        self.assertEqual((receipt_one['run_id'], receipt_two['run_id']), ('P001/demo', 'P002/demo'))  # the same run id twice
        self.assertEqual(sorted(experience.load(two)['runs']), ['P001/demo', 'P002/demo'])
        self.assertFalse((one / 'experience').exists())
        self.assertEqual(experience.main(['show', '--root', str(two), '--run-id', 'demo']), 0)
        self.assertEqual(sorted(experience.load(first)['runs']), ['demo'])  # the project without a shared store is untouched

    def test_prepare_reads_the_store_the_project_names(self):
        pj = test_project_context.ProjectContextTests(); pj.setUp(); self.addCleanup(pj.doCleanups)
        shared = pj.base / 'shared-experience'; shared.mkdir()
        (shared / 'lessons.json').write_text(json.dumps({'schema_version': 1, 'runs': {'P000/earlier': {'sequence': 4, 'entries': [
            {'kind': 'slicing-gap', 'summary': 'lesson from another workspace', 'applicability': 'shared providers',
             'root_cause': 'single consumer assumption', 'strategy': 'enumerate consumers', 'result': 'reviewed',
             'next_check': 'verify all owners', 'evidence_refs': [pj.initial['source_ref']]}]}}}))
        with self.assertRaisesRegex(ValueError, 'experience_root must be absolute'):
            pc.update(pj.root, pj.request('relative', 1, {'experience_root': 'shared-experience'}), pj.actor)
        pc.update(pj.root, pj.request('share', 1, {'experience_root': str(shared)}), pj.actor)
        snapshot = pc.verify_snapshot(pj.prepare()['project_context_ref'])
        index = read_json(check_ref(snapshot['source_refs']['experience_ref']))
        self.assertEqual(index['runs']['P000/earlier']['entries'][0]['summary'], 'lesson from another workspace')
        self.assertEqual(snapshot['source_paths']['experience_ref'], str(shared / 'lessons.json'))


if __name__ == '__main__':
    unittest.main()
