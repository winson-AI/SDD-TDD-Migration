"""Cross-run experience harvesting, querying, and preparation injection."""
import json
from pathlib import Path
import unittest

import test_ledger
import test_decomposition
import test_project_context
import test_source_changes
import ledger
import experience
import openspec_projection
import project_context
import decomposition as dc
from contracts import check_ref, file_ref, read_json


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.flow = test_ledger.FlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)

    def test_build_lessons_captures_all_four_lesson_kinds(self):
        root = self.flow.base / 'test-lessons'
        root.mkdir(parents=True)
        note_file = root / 'fix-note.json'
        note_file.write_text(json.dumps({
            'root_cause': {'category': 'boundary-leak', 'summary': 'missing nil check'},
            'strategy': 'inject guard clause',
            'applicability': 'all repository adapters',
            'risks': 'none'
        }))
        note_ref = file_ref(note_file)

        verdict_file = root / 'verdict.json'
        verdict_file.write_text(json.dumps({'quality': 'green-passed'}))
        verdict_ref = file_ref(verdict_file)

        state = {
            'run_id': 'demo-run',
            'redecomposition_history': [{
                'parent_module_id': 'M010',
                'affected_modules': ['M001', 'M002'],
                'retired_modules': ['M003'],
                'plan_ref': {'path': '/plan.json', 'sha256': 'abc'},
                'review_ref': {'path': '/review.json', 'sha256': 'def'},
                'triggering_requests': [{
                    'module_id': 'M002',
                    'reason': 'Boundary overlap with M001',
                    'evidence_refs': [{'path': '/ev.json', 'sha256': '123'}]
                }]
            }],
            'modules': {
                'M001': {
                    'parent_module_id': 'M010',
                    'realloc_request': {
                        'reason': 'Need shared DB access',
                        'evidence_refs': [{'path': '/db-ev.json', 'sha256': '456'}]
                    },
                    'planning_history': [{
                        'reason': 'scope-invalidated',
                        'plan_hash': 'h123'
                    }],
                    'fix_memory': [{
                        'reusable': True,
                        'fix_note_ref': note_ref,
                        'audit_verdict_ref': verdict_ref
                    }]
                }
            }
        }

        lessons = openspec_projection.build_lessons(state, sequence=42)
        self.assertEqual(lessons['run_id'], 'demo-run')
        self.assertEqual(lessons['sequence'], 42)

        kinds = {e['kind'] for e in lessons['entries']}
        self.assertEqual(kinds, {'slicing-gap', 'boundary-conflict', 'planning-gap', 'fix-pattern'})

        # Check resolved boundary conflict from triggering requests
        resolved = next(e for e in lessons['entries'] if e['kind'] == 'boundary-conflict' and e['status'] == 'resolved')
        self.assertEqual(resolved['module_id'], 'M002')
        self.assertEqual(resolved['summary'], 'Boundary overlap with M001')
        self.assertEqual(resolved['resolution_ref']['path'], '/review.json')

        # Check pending boundary conflict from active module request
        pending = next(e for e in lessons['entries'] if e['kind'] == 'boundary-conflict' and e['status'] == 'pending')
        self.assertEqual(pending['module_id'], 'M001')
        self.assertEqual(pending['summary'], 'Need shared DB access')

        # Check fix pattern extracted from note
        pattern = next(e for e in lessons['entries'] if e['kind'] == 'fix-pattern')
        self.assertEqual(pattern['strategy'], 'inject guard clause')
        self.assertEqual(pattern['applicability'], 'all repository adapters')
        self.assertIn(note_ref, pattern['evidence_refs'])

    def test_harvest_requires_registered_run_and_is_idempotent(self):
        f = test_decomposition.DecompositionTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.root_scope()

        # Project store root
        proj_root = f.base / '.sdd-migration'
        proj_root.mkdir(parents=True, exist_ok=True)
        (proj_root / 'runs').mkdir(exist_ok=True)

        run_root = f.root
        s, events = ledger.read_events(run_root)

        # Unregistered run must fail
        with self.assertRaisesRegex(ValueError, 'not registered'):
            experience.harvest(proj_root, run_root)

        # Register run in project store
        (proj_root / 'runs/demo.json').write_text(json.dumps({
            'run_root': str(run_root.resolve()),
            'project_id': 'P001'
        }))

        # First harvest succeeds
        receipt1 = experience.harvest(proj_root, run_root)
        self.assertEqual(receipt1['run_id'], 'demo')
        self.assertFalse(receipt1['duplicate'])

        # Store files exist
        store = proj_root / 'experience'
        self.assertTrue((store / 'lessons.json').is_file())
        self.assertTrue((store / 'retrospect.jsonl').is_file())

        # Duplicate harvest of same sequence
        receipt2 = experience.harvest(proj_root, run_root)
        self.assertTrue(receipt2['duplicate'])

        # List and show CLI functions
        all_entries = experience.entries(proj_root)
        self.assertIsInstance(all_entries, list)

        filtered = experience.entries(proj_root, kind='slicing-gap')
        self.assertTrue(all(e['kind'] == 'slicing-gap' for e in filtered))

        # Test CLI main
        self.assertEqual(experience.main(['list', '--root', str(proj_root)]), 0)
        self.assertEqual(experience.main(['show', '--root', str(proj_root), '--run-id', 'demo']), 0)

    def test_prepare_freezes_experience_lessons_into_snapshot(self):
        pj = test_project_context.ProjectContextTests()
        pj.setUp()
        self.addCleanup(pj.doCleanups)

        proj_root = pj.root
        exp_dir = proj_root / 'experience'
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / 'lessons.json').write_text(json.dumps({
            'schema_version': 1,
            'runs': {
                'demo-prev': {
                    'sequence': 10,
                    'entries': [{'kind': 'slicing-gap', 'summary': 'previous lesson',
                        'applicability': 'shared providers', 'root_cause': 'single consumer assumption',
                        'strategy': 'enumerate consumers', 'result': 'reviewed', 'next_check': 'verify all owners',
                        'evidence_refs': [file_ref(pj.source)]}]
                }
            }
        }))

        res = pj.prepare()
        ref = res['project_context_ref']
        snap = project_context.verify_snapshot(ref)

        self.assertIn('experience_ref', snap['source_refs'])
        exp_snapshot = Path(snap['source_refs']['experience_ref']['path'])
        self.assertTrue(exp_snapshot.is_file())
        self.assertIn('previous lesson', exp_snapshot.read_text())
        index = json.loads(exp_snapshot.read_text())
        self.assertEqual(index['view'], 'index')
        row = index['runs']['demo-prev']['entries'][0]
        self.assertNotIn('strategy', row)
        self.assertEqual(json.loads(Path(row['lesson_ref']['path']).read_text())['strategy'], 'enumerate consumers')

    def test_planning_view_excludes_observations_without_inventing_causes(self):
        abstract = {'kind': 'planning-gap', 'summary': 'Review consumers', 'applicability': 'shared providers',
            'root_cause': 'assumed one consumer', 'strategy': 'enumerate consumers', 'result': 'unverified',
            'next_check': 'inspect current bindings', 'evidence_refs': [self.flow.ref('lesson-evidence.md', 'Review')]}
        view = experience.planning_view({'runs': {'old': {'sequence': 1, 'entries': [abstract,
            {'kind': 'planning-gap', 'summary': 'Module replanned'}]}}})
        self.assertEqual(view['runs']['old']['entries'], [abstract])
        self.assertEqual(view['observations_omitted'], 1)


if __name__ == '__main__':
    unittest.main()


class RetrospectiveTests(unittest.TestCase):
    def setUp(self):
        self.source = test_source_changes.SourceChangeTests(); self.source.setUp(); self.addCleanup(self.source.doCleanups)
        self.f = self.source.f

    def test_retrospect_commits_abstract_lessons_and_harvests_automatically(self):
        f = self.f; before = f.state()
        proof = f.ref('retrospective-proof.md', 'Committed boundary review')
        f.call('retrospect', {'lessons_ref': f.ref('retrospective.json', {'schema_version': 1, 'entries': [{
            'kind': 'planning-gap', 'module_id': 'M001', 'summary': 'Inspect provider ownership before task split',
            'applicability': 'shared repository consumers', 'root_cause': 'assuming a single consumer',
            'strategy': 'enumerate all production consumers', 'result': 'reviewed boundary correction',
            'next_check': 'compare consumers against write owners', 'evidence_refs': [proof]}]})}, role='host', module=None)
        state = f.state()
        self.assertEqual(state['modules']['M001']['phase'], before['modules']['M001']['phase'])
        self.assertIsNone(state['modules']['M001']['freeze_id'])
        data = experience.load(self.source.config_root)
        self.assertTrue(data['runs']['demo']['entries'])
        view = ledger.status(f.root, view='step', module_id='M001')
        self.assertTrue(read_json(check_ref(view['history_refs']['lessons']))['entries'])
        self.assertIn(state['modules']['M001']['planning_lessons_ref'],
                      __import__('context_readiness').input_refs(state, 'M001', 'planning'))

    def test_failed_fix_strategy_is_retained_as_unverified_experience(self):
        f = self.f
        note = f.ref('failed-strategy.json', {'root_cause': 'wrong assumption', 'strategy': 'duplicate provider',
                                              'applicability': 'shared behavior', 'risks': 'conflicting owners'})
        lessons = openspec_projection.build_lessons({'run_id': 'demo', 'modules': {
            'M001': {'fix_memory': [{'status': 'failed', 'reusable': False, 'fix_note_ref': note}]}}}, 1)
        self.assertEqual(lessons['entries'][0]['kind'], 'failed-strategy')
        self.assertEqual(lessons['entries'][0]['result'], 'failed')
        self.assertTrue(lessons['entries'][0]['next_check'])

    def test_unscoped_abstract_lesson_reaches_every_leaf_preflight(self):
        f = self.f
        entry = {'kind': 'planning-gap', 'summary': 'Inspect shared provider consumers',
            'applicability': 'shared repository consumers', 'root_cause': 'assuming a single consumer',
            'strategy': 'enumerate production consumers', 'result': 'reviewed boundary correction',
            'next_check': 'compare consumers against owners', 'evidence_refs': [f.ref('shared-proof.md', 'Reviewed consumers')]}
        f.call('retrospect', {'lessons_ref': f.ref('shared-lessons.json', {'schema_version': 1, 'entries': [entry]})}, role='host', module=None)
        state = f.state()
        for mid, module in state['modules'].items():
            ref = module['planning_lessons_ref']
            self.assertIn(entry, read_json(check_ref(ref))['entries'])
            self.assertIn(ref, __import__('context_readiness').input_refs(state, mid, 'planning'))
