"""Events record what they changed; replay rebuilds exactly the state the controller committed."""
import copy
import json
import unittest

import test_ledger
import test_workflow
import ledger
from contracts import digest


def journal(root):
    return [json.loads(line) for line in (root / 'ledger/events.jsonl').read_text().splitlines()]


class JournalPatchTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_workflow.WorkflowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def repaired_run(self):
        f = self.f
        r = f.failed_module(); f.diagnose(); f.implementation('fixer', 'F1')
        a, r2 = f.make_test_result('TEST2', previous=r['paths'][0]['test_run_id'])
        f.submit(r2, a); f.call('accept', {'assignment_id': 'TEST2'})
        f.call('complete', {'dod_ref': f.ref('dod.md', 'reviewed')})
        return f

    def test_replay_reproduces_the_projected_state(self):
        f = self.repaired_run()
        state, events = ledger.read_events(f.root)
        projected = json.loads((f.root / 'ledger/global.json').read_text())
        for extra in ('last_sequence', 'parent_mo_names'):
            projected.pop(extra)
        self.assertEqual(state, projected)
        self.assertEqual(state['modules']['M001']['phase'], 'completed')
        self.assertIn('effect', events[0]); self.assertNotIn('patch', events[0])
        self.assertTrue(all('patch' in e and 'effect' not in e for e in events[1:]))

    def test_an_event_records_only_what_it_changed(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / 'm2')]},
               role='global-orchestrator', module=None)
        f.prepare()  # global plan, plan and freeze of M001
        events = journal(f.root)
        frozen = next(e for e in reversed(events) if e['operation'] == 'freeze')
        changed = frozen['patch']['set']['modules']
        self.assertEqual(list(changed), ['M001'])           # the sibling's state is not rewritten
        self.assertNotIn('plan', changed['M001'])           # nor the unchanged plan of the module itself
        self.assertIn('freeze_id', changed['M001'])
        planned = next(e for e in events if e['operation'] == 'plan')
        self.assertLess(len(json.dumps(frozen)), len(json.dumps(planned)))
        full = len(json.dumps(ledger.read_events(f.root)[0]))
        self.assertLess(len(json.dumps(frozen['patch'])), full / 4)

    def test_an_event_lists_only_artifacts_no_earlier_event_archived(self):
        f = self.repaired_run()
        state, events = ledger.read_events(f.root)
        listed = set()
        for event in events:
            for item in event['artifact_snapshots']:
                if item.get('status'):
                    continue  # drift and historical-snapshot records belong to their event
                key = (item['source_path'], item['sha256'])
                self.assertNotIn(key, listed)
                listed.add(key)
        index = ledger.artifact_index(events)
        self.assertEqual(set(index), listed)
        spec = state['global_spec']  # referenced again by later payloads, archived once, still found
        self.assertIn((spec['path'], spec['sha256']), index)
        plan_ref = state['modules']['M001']['plan_ref']
        self.assertEqual(index[(plan_ref['path'], plan_ref['sha256'])][1]['event_id'],
                         next(e['event_id'] for e in events if e['operation'] == 'plan'))

    def test_nested_removals_are_replayed(self):
        before = {'modules': {'M001': {'results': {'P1': {'quality': 'red-bug'}, 'P2': {'quality': 'green-passed'}}, 'blocked': {'kind': 'human'}},
                              'M002': {'phase': 'testing'}}, 'audit_queue': {'M001': {'reason': 'x'}}}
        after = copy.deepcopy(before)
        del after['modules']['M002']; del after['audit_queue']['M001']; del after['modules']['M001']['results']['P1']
        after['modules']['M001']['blocked'] = None
        after['modules']['M001']['results']['P2'] = {'quality': 'green-passed', 'test_run_id': 'T2'}
        changed, removed = ledger.journal_diff(before, after)
        self.assertEqual(sorted(removed), [['audit_queue', 'M001'], ['modules', 'M001', 'results', 'P1'], ['modules', 'M002']])
        self.assertEqual(changed['modules']['M001']['results']['P2'], after['modules']['M001']['results']['P2'])  # an entry is whole
        original = copy.deepcopy(before)
        replayed = dict(before)
        ledger.apply_change(replayed, {'patch': {'set': changed, 'del': removed}})
        self.assertEqual(replayed, after)
        self.assertEqual(before, original)  # replay copies on write: objects owned by earlier events stay intact

    def test_events_written_as_whole_keys_still_replay_and_can_be_extended(self):
        f = self.repaired_run()
        expected, events = ledger.read_events(f.root)
        converted, previous = [], None
        for event, state, changed in ledger.replay(copy.deepcopy(events)):
            old = {k: v for k, v in event.items() if k not in ('patch', 'effect', 'sha256')}
            old.update(effect={k: copy.deepcopy(state[k]) for k in changed}, previous_hash=previous)
            old['sha256'] = previous = digest(old)
            converted.append(old)
        (f.root / 'ledger/events.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False, sort_keys=True) + '\n' for e in converted))
        state, replayed = ledger.read_events(f.root)
        self.assertEqual(state, expected)
        self.assertTrue(all('effect' in e for e in replayed))
        f.call('session', {'role': 'implementer', 'session_id': 'S-NEXT'})  # a new event on top of the old ones
        state, replayed = ledger.read_events(f.root)
        self.assertIn('patch', replayed[-1])
        self.assertEqual(state['modules']['M001']['sessions']['implementer']['session_id'], 'S-NEXT')
        self.assertEqual({k: v for k, v in state.items() if k != 'modules'}, {k: v for k, v in expected.items() if k != 'modules'})

    def test_replay_does_not_mutate_the_events_it_reads(self):
        f = self.repaired_run()
        _, events = ledger.read_events(f.root)
        pristine = copy.deepcopy(events)
        states = [copy.deepcopy(state) for _, state, _ in ledger.replay(events)]
        self.assertEqual(events, pristine)
        self.assertEqual(states[-1], ledger.read_events(f.root)[0])


if __name__ == '__main__':
    unittest.main()


class StateReferenceTests(unittest.TestCase):
    """State keeps hash-bound references to reports and results, not copies of them."""

    def test_receipts_and_submissions_are_references(self):
        import test_context_readiness
        from pathlib import Path
        from contracts import Rejected
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        a, result = f.make_test_result(); f.submit(result, a)
        m = f.state()['modules']['M001']
        submission = m['submissions'][a['assignment_id']]
        self.assertEqual(set(submission), {'ref', 'kind', 'green', 'test_run_ids'})
        self.assertEqual((submission['kind'], submission['green']), ('tests', True))
        self.assertTrue(m['context_receipts'])
        for receipt in m['context_receipts'].values():
            # A receipt is references and a digest: the report stays in its file, the derived inputs in one hash, and
            # a report that reads the run's history keeps the version it read.
            self.assertEqual(set(receipt) - {'history_ref'}, {'report_ref', 'stage', 'producer', 'verdict', 'inputs_sha256'})
            self.assertEqual('history_ref' in receipt, receipt['stage'] in test_context_readiness.cr.HISTORY_STAGES)
        path = Path(submission['ref']['path']); original = path.read_text()
        path.write_text(original.replace('green-passed', 'red-bug'))
        with self.assertRaises(Rejected):  # the accepted result is the hash-bound file, read again at accept
            f.call('accept', {'assignment_id': a['assignment_id']})
        path.write_text(original)
        f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')

    def test_design_assignment_keeps_the_refs_it_must_read_not_the_input_document(self):
        import test_design_stage
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups); f.global_plan()
        a, _ = test_design_stage.start_design(f, f.plan())
        self.assertNotIn('input_content', a)
        self.assertTrue(a['input_refs'])
