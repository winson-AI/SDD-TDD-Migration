"""A step is handed what it has to write and nothing it already read or the Ledger does for it."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import context_readiness as cr
import ledger
import reading
from contracts import file_ref
import test_source_changes

CR = reading.P + 'context-readiness.md'


def dispatch(role, **over):
    return {'role': 'module-orchestrator', 'operation': 'assign', 'worker_role': role, **over}


class TestRunnerStagesTests(unittest.TestCase):
    """Build and automation stay two dispatches, run one after the other; what the first read is not handed again."""
    def cards(self):
        return (reading.card({}, None, dispatch('test-runner', test_scope='build')),
                reading.card({}, None, dispatch('test-runner', test_scope='automation')))

    def test_the_second_stage_adds_only_what_that_stage_needs(self):
        build, automation = self.cards()
        m = {}
        ledger.deliver(m, build, 'runner')
        new = reading.fresh(automation, m['delivered_cards']['runner'])
        self.assertNotIn('Agents/test-runner.md', [row['ref'] for row in new])  # the role text of both stages was in the first card
        self.assertLess(sum(row['bytes'] for row in new), sum(row['bytes'] for row in automation) / 2)
        self.assertTrue(any(row['ref'].endswith('build-automation.md') or row['ref'].endswith('testing.md') for row in new))

    def test_a_stage_that_comes_round_again_brings_only_the_red_lines(self):
        build, automation = self.cards()
        m = {}
        for rows in (build, automation):
            ledger.deliver(m, rows, 'runner')
        held = m['delivered_cards']['runner']
        for rows in (build, automation):  # the retest after a repair
            self.assertEqual({row['ref'] for row in reading.fresh(rows, held)}, {'AGENTS.md'})
        self.assertTrue(all(isinstance(digests, list) for digests in held.values()))  # every text of a section it was handed

    def test_a_session_recorded_with_one_digest_per_section_still_reads(self):
        build, _ = self.cards()
        held = reading.delivered(build)  # the shape earlier events recorded
        self.assertEqual({row['ref'] for row in reading.fresh(build, held)}, {'AGENTS.md'})


class ExecutorReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def module(self, *decisions, frozen=True):
        path = Path(self.tmp.name).resolve() / 'reuse-plan.json'
        path.write_text(json.dumps({'mappings': [{'mapping_id': 'MAP-%d' % n, 'decision': d} for n, d in enumerate(decisions)]}))
        return {'plan': {'reuse_plan_ref': file_ref(path)}, 'freeze_id': 'frozen' if frozen else None}

    def test_an_executor_follows_the_reuse_protocol_only_when_its_plan_takes_from_a_provider(self):
        s = {'reuse_required': True}
        self.assertFalse(reading.reuse_applies(s, self.module('new', 'new'), 'implementer'))
        self.assertTrue(reading.reuse_applies(s, self.module('new', 'adapt'), 'implementer'))
        self.assertTrue(reading.reuse_applies(s, self.module('new'), 'spec-designer'))          # a planner still weighs reuse
        self.assertTrue(reading.reuse_applies(s, self.module('new', frozen=False), 'implementer'))  # not decided until frozen
        refs = lambda m: {row['ref'].split('/')[-1] for row in reading.card(s, m, dispatch('implementer'))}
        self.assertNotIn('reuse-dependencies.md', refs(self.module('new')))
        self.assertIn('reuse-dependencies.md', refs(self.module('reuse')))


class TemplateTests(unittest.TestCase):
    def names(self, m, role='spec-designer', **step):
        step = {'role': role, 'operation': 'plan', **step} if role == 'spec-designer' else dispatch(role)
        return {name.split('/')[-1] for name in reading.templates({'context_readiness_required': True}, m, step)}

    def test_a_plan_step_gets_the_templates_of_what_it_writes(self):
        analysed = {'dimension_analysis_ref': {'path': '/nowhere', 'sha256': '0'}}
        first = self.names(analysed)
        self.assertLessEqual({'stage-plan.json', 'upstream-test-plan.json'}, first)
        self.assertFalse(first & {'proposal.md', 'spec.md', 'design.md', 'tasks.md', 'dimension-analysis.json', 'semantic-model.json', 'change-impact.json'})
        again = self.names({**analysed, 'plan': {}, 'plan_ref': {}})  # nothing changes without a plan to revise
        self.assertEqual(again, first)
        revising = self.names({**analysed, 'plan': {'paths': []}, 'change_request': {'request_ref': {}}})
        self.assertLessEqual({'proposal.md', 'spec.md', 'design.md', 'tasks.md', 'change-impact.json'}, revising)  # the documents exist and are edited
        self.assertLessEqual({'proposal.md', 'spec.md', 'design.md', 'tasks.md'}, self.names({}))  # no analysis to start from

    def test_a_coder_is_not_handed_the_preflight_template_and_a_fixer_is(self):
        self.assertNotIn('context-readiness.json', self.names(None, 'implementer'))
        self.assertIn('context-readiness.json', self.names(None, 'fixer'))
        self.assertIn('context-readiness.json', self.names(None, 'test-runner'))


class CardTests(unittest.TestCase):
    def test_a_coders_card_says_nothing_about_reporting_a_preflight(self):
        s = {'context_readiness_required': True}
        keys = lambda role, state: {(row['ref'], row['section']) for row in reading.card(state, None, dispatch(role))}
        self.assertNotIn((CR, '2. 精确插入节点'), keys('implementer', s))
        self.assertIn((CR, '2. 精确插入节点'), keys('fixer', s))
        self.assertIn((CR, '2. 精确插入节点'), keys('implementer', {}))  # a run without the readiness gate is as before
        matrix = lambda role: next(row['section'] for row in reading.card(s, None, dispatch(role)) if '操作矩阵@' in (row['section'] or ''))
        self.assertNotIn('context-submit', matrix('implementer'))
        self.assertIn('context-submit', matrix('fixer'))

    def test_a_step_that_waits_for_its_provider_carries_no_card(self):
        waiting = ledger.with_card({}, None, {'role': 'global-orchestrator', 'operation': 'dependency-ready', 'ready': False,
                                              'reason': 'dependency-incomplete'})
        self.assertEqual(waiting['must_read'], [])
        ready = ledger.with_card({}, None, {'role': 'global-orchestrator', 'operation': 'dependency-ready', 'ready': True, 'reason': None})
        self.assertTrue(ready['must_read'])


class PlanningInputTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = t.f

    def test_a_planner_must_read_what_it_plans_from_and_opens_the_trees_by_locator(self):
        f = self.f
        legacy = f.legacy / 'LoginScreen.java'; legacy.write_text('class LoginScreen {}')
        target = f.target / 'existing/Login.kt'; target.parent.mkdir(parents=True, exist_ok=True); target.write_text('object Login')
        note = f.ref('allocation-note.md', 'what this slice owns')
        state = f.state()
        sources = [file_ref(legacy)['path'], file_ref(target)['path']]
        state['modules']['M001']['context_refs'] = [file_ref(legacy), file_ref(target), note]
        paths = lambda refs: {ref['path'] for ref in refs}
        standing, planning = paths(cr.standing_refs(state, 'M001', 'planning')), paths(cr.input_refs(state, 'M001', 'planning'))
        self.assertLessEqual({*sources, note['path']}, standing)
        self.assertFalse(planning.intersection(sources))
        self.assertIn(note['path'], planning)  # what the allocator wrote for the slice is still read
        self.assertIn(state['modules']['M001']['dimension_analysis_ref']['path'], planning)
        self.assertEqual(standing - planning, set(sources))
        cr.verify_inputs(state, 'M001', 'planning')
        legacy.write_text('class LoginScreen { int changed; }')
        with self.assertRaises(ValueError):  # not required reading, still not allowed to drift under a ready report
            cr.verify_inputs(state, 'M001', 'planning')


if __name__ == '__main__':
    unittest.main()
