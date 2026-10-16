"""A fact nobody's source, target or document holds: recorded as a knowledge need, answered by a person with sources,
written as a document of the run, handed to the leaves it concerned; the project's own documents are searchable."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import knowledge
import ledger
import lean_knowledge
import project_context as pc
import test_control_policy
import test_ledger
import test_project_context
from contracts import Rejected, check_ref, digest


class KnowledgeNeedTests(unittest.TestCase):
    def setUp(self):
        self.t = test_control_policy.ControlPolicyTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f; self.f.global_plan()
        self.f.call('plan', {'plan_ref': self.f.ref('policy-plan.json', self.f.plan())}, role='spec-designer')

    def need(self, blocks=True):
        self.f.call('issue', {'issue_id': 'KN-1', 'kind': 'knowledge-need', 'blocks': blocks, 'applies_to': ['M001'],
                              'summary': 'retry policy of the payment SDK on timeout is not in the sources or the documents'}, role='spec-designer', module=None)
        return self.f.state()['issues']['KN-1']

    def test_a_blocking_need_holds_the_freeze_until_a_person_answers_with_sources(self):
        f = self.f; issue = self.need()
        f.call('plan-review', {'review_ref': self.t.review()})
        with self.assertRaisesRegex(Rejected, 'blocking issue open'):
            f.call('freeze', f.state()['next_steps'][0].get('payload') or {'review_ref': self.t.review()})
        with self.assertRaisesRegex(Rejected, 'settled by a knowledge decision'):
            f.call('issue-resolve', {'issue_id': 'KN-1', 'module_id': 'M001', 'evidence_ref': f.ref('guess.md', 'we think it retries twice')}, role='spec-designer', module=None)
        payload = {'decision_id': 'K1', 'kind': 'knowledge', 'decision': 'approved', 'module_id': 'M001', 'question_id': 'KN-1',
                   'subject_sha256': knowledge.subject('KN-1', issue), 'answers': ['the SDK retries once after 3 s, then raises TimeoutError'],
                   'sources': ['vendor SDK manual v2.3 §4.1'], 'human_source_ref': f.ref('answer.md', 'answered by the integration owner')}
        with self.assertRaisesRegex(Rejected, 'knowledge sources'):
            f.call('decision', {**payload, 'sources': []}, role='host', module=None)
        f.call('decision', payload, role='host', module=None)
        s = f.state()
        doc = check_ref(s['decisions']['K1']['knowledge_ref'])
        self.assertTrue(doc.name == 'K1.md' and 'retries once' in doc.read_text() and 'SDK manual' in doc.read_text())
        self.assertEqual(s['issues']['KN-1']['resolved']['M001']['decision_id'], 'K1')
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['knowledge_decisions'][0]['decision_id']), ('freeze', 'K1'))  # read with the step, the plan stays bound
        f.call('freeze', step['payload'])

    def test_a_need_that_does_not_block_is_recorded_and_the_first_version_goes_on(self):
        f = self.f; self.need(blocks=False)
        f.call('plan-review', {'review_ref': self.t.review()})
        step = f.state()['next_steps'][0]
        self.assertEqual(step['operation'], 'freeze'); f.call('freeze', step['payload'])
        self.assertIn('KN-1', f.state()['issues'])


class ProjectKnowledgeTests(unittest.TestCase):
    def test_the_projects_documents_and_answers_are_searchable_by_line(self):
        pj = test_project_context.ProjectContextTests(); pj.setUp(); self.addCleanup(pj.doCleanups)
        doc = pj.base / 'wiki-payments.md'; doc.write_text('# Payments\n\nRetry policy: the gateway retries once.\nTimeouts are 3 s.\n')
        pc.update(pj.root, pj.request('knowledge', 1, {'knowledge_paths': [str(doc)]}), pj.actor)
        prepared = pj.prepare()
        pj.start(pj.init_payload(prepared))
        state = ledger.status(pj.run)
        hits = knowledge.search(state, 'retry')
        self.assertEqual((len(hits), hits[0]['count'], hits[0]['hits'][0]['line']), (1, 1, 3))
        self.assertTrue(Path(hits[0]['ref']['path']).is_file())
        result = lean_knowledge.run('knowledge-query', {'mode': 'project', 'query': 'timeouts'}, prepared, pj.run)
        self.assertEqual((result['mode'], result['status'], result['matches'][0]['hits'][0]['text']), ('project', 'hits', 'Timeouts are 3 s.'))
        self.assertEqual(lean_knowledge.run('knowledge-query', {'mode': 'project', 'query': 'nowhere'}, prepared, pj.run)['status'], 'no-match')


if __name__ == '__main__':
    unittest.main()
