"""A project's slicing experience becomes a skill: generated from its store, frozen into the next run, loaded where
slicing is decided, and regenerated whenever a run adds to the store."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import context_readiness as cr
import experience
import project_context as pc
from contracts import check_ref, file_ref
from test_behavior_contract import review as behavior_review
import test_context_readiness
import test_decomposition
import test_dimensions
import test_project_context


def lesson(summary, applicability='a provider consumed by several slices', strategy='split by the behaviour a user observes', **over):
    return {'kind': 'slicing-gap', 'summary': summary, 'applicability': applicability, 'root_cause': 'slices were cut by layer',
            'strategy': strategy, 'result': 'one re-split fewer', 'next_check': 'every slice accepts a case',
            'evidence_refs': [{'path': '/evidence/review.md', 'sha256': 'a' * 64}], **over}


def store(**runs):
    return {'schema_version': 1, 'runs': {rid: {'sequence': 1, 'harvested_at': '2000-01-0%d' % number, **block}
                                         for number, (rid, block) in enumerate(runs.items(), 1)}}


SPLIT = {'roots': 1, 'leaves': 3, 'resplits': 2, 'run_revisions': 0,
         'splits': [{'parent_module_id': 'M010', 'slices': 3, 'supporting': ['M001'], 'shared_cases': ['C2'], 'chain_depth': 3, 'waiting': 2}]}


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name).resolve() / 'experience'

    def test_a_store_with_nothing_about_slicing_gives_no_skill(self):
        data = store(first={'entries': [{'kind': 'fix-pattern', 'summary': 'guard the nil case'}], 'slicing': {'splits': [], 'resplits': 0, 'run_revisions': 0}})
        self.assertIsNone(experience.skill_body(data))
        self.assertIsNone(experience.write_skill(self.directory, data))
        self.assertFalse(self.directory.exists())
        self.assertNotIn('skill', data)

    def test_a_lesson_several_runs_arrived_at_is_merged_and_comes_first(self):
        data = store(first={'entries': [lesson('cut by behaviour, not by layer'), lesson('keep the fixture with its consumer', applicability='a fixture one slice owns', strategy='leave it in that slice')]},
                     second={'entries': [lesson('Cut by behaviour', applicability='A provider consumed  by several slices', result='no re-split'),
                                         {'kind': 'fix-pattern', 'summary': 'guard the nil case', 'applicability': 'adapters', 'root_cause': 'nil',
                                          'strategy': 'guard', 'result': 'verified', 'next_check': 'rerun', 'evidence_refs': [{}]}]})
        body = experience.skill_body(data)
        self.assertIn('## 已抽象的经验（2 条）', body)
        self.assertLess(body.index('### 1. Cut by behaviour'), body.index('### 2. keep the fixture with its consumer'))  # latest wording, most runs
        self.assertIn('印证：2 个 run（first、second）', body)
        self.assertIn('- 结果：no re-split', body)
        self.assertNotIn('guard the nil case', body)  # a fix pattern is not slicing experience

    def test_earlier_splits_and_unabstracted_observations_are_recorded_as_they_were(self):
        data = store(first={'entries': [{'kind': 'boundary-conflict', 'summary': 'the child scope left out the navigation handler', 'module_id': 'M002'}],
                            'slicing': SPLIT})
        body = experience.skill_body(data)
        self.assertIn('| first | 1 / 3 | M010 | 3 | M001 | 1 条（C2） | 3 | 2 | 2 | 0 |', body)
        many = copy.deepcopy(SPLIT); many['splits'][0]['shared_cases'] = ['C%d' % n for n in range(1, 18)]
        self.assertIn('| 17 条（C1、C2、C3 等） |', experience.skill_body(store(first={'entries': [], 'slicing': many})))  # a count, not seventeen ids
        self.assertIn('## 尚未抽象的观察（共 1 条，列最近 1 条）', body)
        self.assertIn('- first · boundary-conflict：the child scope left out the navigation handler', body)
        self.assertIn('## 已抽象的经验（0 条）', body)

    def test_the_revision_moves_only_when_what_the_skill_says_changes(self):
        data = store(first={'entries': [lesson('cut by behaviour')], 'slicing': SPLIT})
        written = experience.write_skill(self.directory, data)
        path = self.directory / 'skills/migration-slicing-experience/SKILL.md'
        self.assertEqual(written, {'path': str(path), 'revision': 1})
        text = path.read_text()
        self.assertTrue(text.startswith('---\nname: migration-slicing-experience\ndescription: '))
        self.assertIn('第 1 版，来自 1 个 run', text.split('---')[1])
        self.assertEqual(experience.write_skill(self.directory, data)['revision'], 1)  # nothing new: the same skill
        self.assertEqual(path.read_text(), text)
        data['runs']['second'] = {'sequence': 1, 'harvested_at': '2000-01-09', 'entries': [lesson('one accepting slice per case', applicability='cases shared by slices', strategy='name the accepting slice')]}
        self.assertEqual(experience.write_skill(self.directory, data)['revision'], 2)  # the next run refined it
        self.assertIn('第 2 版，来自 2 个 run', path.read_text())
        self.assertIn('one accepting slice per case', path.read_text())


class CardTests(unittest.TestCase):
    def test_the_card_a_host_hands_over_carries_the_skill_the_step_names(self):
        import reading
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        experience.write_skill(base / 'experience', store(first={'entries': [lesson('cut by behaviour')]}))
        skill = {'name': experience.SKILL, 'ref': file_ref(base / 'experience/skills' / experience.SKILL / 'SKILL.md')}
        rows = [{'ref': 'AGENTS.md', 'section': '四条红线', 'bytes': 1, 'sha256': 'x'}]
        plain = Path(reading.render(rows, base / 'cards')['path']).read_text()
        self.assertNotIn('cut by behaviour', plain)
        loaded = Path(reading.render(rows, base / 'cards', (), skill)['path']).read_text()
        self.assertIn('<!-- 技能 migration-slicing-experience -->', loaded)
        self.assertIn('cut by behaviour', loaded)


class HarvestTests(unittest.TestCase):
    def test_a_run_that_split_a_parent_leaves_the_skill_in_the_store(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); f.split()
        project = f.base / '.sdd-migration'; (project / 'runs').mkdir(parents=True, exist_ok=True)
        (project / 'runs/demo.json').write_text(json.dumps({'run_root': str(f.root.resolve()), 'project_id': 'P001'}))
        receipt = experience.harvest(project, f.root)
        path = experience.skill_path(project)
        self.assertEqual(receipt['slicing_skill'], {'path': str(path), 'revision': 1})
        self.assertIn('| demo | ', path.read_text())
        block = experience.load(project)['runs']['demo']
        self.assertEqual(block['slicing']['splits'][0]['parent_module_id'], 'M010')
        self.assertEqual(experience.load(project)['skill']['revision'], 1)


class NextRunTests(unittest.TestCase):
    def test_prepare_freezes_the_skill_into_the_run(self):
        first = test_project_context.ProjectContextTests(); first.setUp(); self.addCleanup(first.doCleanups)
        self.assertNotIn('slicing_skill_ref', pc.verify_snapshot(first.prepare()['project_context_ref'])['source_refs'])  # a first run has none
        pj = test_project_context.ProjectContextTests(); pj.setUp(); self.addCleanup(pj.doCleanups)
        experience.write_skill(experience.store(pj.root), store(first={'entries': [lesson('cut by behaviour')]}))
        snapshot = pc.verify_snapshot(pj.prepare()['project_context_ref'])
        frozen = check_ref(snapshot['source_refs']['slicing_skill_ref'])
        self.assertIn('cut by behaviour', frozen.read_text())
        self.assertTrue(frozen.is_relative_to(Path(snapshot['run_root'])))  # the run reads its own copy, not the moving store
        self.assertEqual(snapshot['source_paths']['slicing_skill_ref'], str(experience.skill_path(pj.root)))

    def run_with_skill(self):
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        old = f.state(); f.root = (f.base / '.sdd-runs/demo').resolve()
        actor, project = {'role': 'host', 'instance_id': 'host'}, f.base / '.sdd-migration'
        pc.update(project, {'schema_version': 1, 'project_id': 'demo', 'request_id': 'config', 'expected_revision': 0,
                  'patch': {'legacy_root': str(f.legacy), 'target_root': str(f.target), 'architecture_path': old['new_architecture']['path']},
                  'source_ref': f.ref('user-config.md', 'Use these roots')}, actor, True)
        experience.write_skill(experience.store(project), store(earlier={'entries': [lesson('cut by behaviour')], 'slicing': SPLIT}))
        prepared = pc.prepare(project, f.root, {'schema_version': 1, 'project_id': 'demo', 'request_id': 'prepare', 'run_id': 'demo',
                              'source_ref': f.ref('user-run.md', 'Migrate fixture')}, actor)
        f.call('init', {**{k: old[k] for k in ('target_root', 'legacy_root', 'global_spec', 'case_ids', 'requirement_ids')},
               'new_architecture': prepared['input']['new_architecture'], 'project_context_ref': prepared['project_context_ref'],
               'global_paths': []}, role='host')
        d = test_dimensions.DimensionTests(); d.f = f
        analysis = d.analysis()
        d.root_ref = f.ref('root-dimensions.json', analysis)
        parent = {'module_id': 'M010', 'case_ids': ['C1'], 'write_paths': [str(f.target)], 'scope': analysis['scope'],
                  'context_refs': [f.ref('root-context.md', 'Parent scope')], 'dimension_analysis_ref': d.root_ref, 'decomposition_required': True}
        parent['behavior_review'] = behavior_review(f, parent)
        f.call('register', parent, role='global-orchestrator', module=None)
        return f, d, pc.verify_snapshot(prepared['project_context_ref'])['source_refs']['slicing_skill_ref']

    def test_the_orchestrators_load_it_where_slicing_is_decided_and_nobody_else_does(self):
        f, d, skill = self.run_with_skill()
        expected = {'name': 'migration-slicing-experience', 'ref': skill}
        split, = [step for step in f.state()['next_steps'] if step.get('operation') == 'decompose']
        self.assertEqual((split['role'], split['slicing_skill']), ('module-orchestrator', expected))
        f.split(d.proposal(ids=('M001', 'M002')))
        state = f.state()
        self.assertEqual((state['global_next_step']['operation'], state['global_next_step']['slicing_skill']), ('global-plan', expected))
        f.global_plan()
        plan, = [step for step in f.state()['next_steps'] if step.get('module_id') == 'M001']
        self.assertEqual(plan['operation'], 'plan')
        self.assertNotIn('slicing_skill', plan)  # a Spec-Designer plans inside the slice it was given
        paths = lambda mid, stage: {ref['path'] for ref in cr.input_refs(f.state(), mid, stage)}
        self.assertIn(skill['path'], paths(None, 'global-planning'))
        self.assertIn(skill['path'], paths('M010', 'decomposition'))
        for stage in ('planning', 'coding', 'testing'):
            self.assertNotIn(skill['path'], paths('M001', stage), stage)


if __name__ == '__main__':
    unittest.main()
