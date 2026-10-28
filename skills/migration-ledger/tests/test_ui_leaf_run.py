"""A run whose leaves have screens, walked in a prepared run from the root's registration to its end: the legacy cannot be
run and the target has no device, so the visible cases end unverified, and each leaf's first plan leaves its screen's
closure and some item ids out, as a first version may. Built and unit-tested, each leaf is reopened by the Ledger for what
its plan owes before its static review; the revision only adds to the plan, so the code and its Green stay, and the static
review is judged once, on the revised plan. The counts are reported, not a gate."""
import json
from pathlib import Path
import sys
import unittest
import warnings

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_continuous_run
import test_source_changes
import workflow_cost
from contracts import baseline, check_ref, file_ref, read_json

# The model turns last recorded in VERIFICATION.md for this run, by role.
RECORDED = {'global-orchestrator': 1, 'module-orchestrator': 1, 'spec-designer': 4, 'implementer': 2, 'test-runner': 4, 'auditor': 1}
RECORDED_CARD = 20903  # the most protocol bytes one turn's card handed a model in this run (the reopened plan)


def config(f):
    """The project says the legacy cannot be shown, the target has no device, and where copied files go."""
    return {'legacy_preview': {'kind': 'none', 'reason': 'the legacy needs an account the run does not have'},
            'test_adapter': {'device': {'unavailable': 'no device in this environment'}},
            'target_resources': {'copy': {'root': str(f.target / 'res'), 'path': '{kind}/{name}{ext}', 'accessor': 'Res.{kind}.{name}',
                                          'formats': ['png', 'vector-xml'], 'density': ['xxhdpi']},
                                 'declined': {'parameters': 'the target keeps its own theme values'}}}


class UiLeafWalk(test_continuous_run.ContinuousWalk):
    def setUp(self):
        real = test_source_changes.SourceChangeTests.register_root
        test_source_changes.SourceChangeTests.register_root = lambda t, features=None, global_paths=(): real(
            t, features, global_paths, kinds=('UI', 'Logic', 'Resource'), config=config)
        try:
            super().setUp()
        finally:
            test_source_changes.SourceChangeTests.register_root = real

    def leaf_plan(self, mid):
        """What the Spec-Designer plans: where the screen's resource lands and who reads it, every item traced to its task;
        reopened, the screen's closure and every item id in the documents."""
        plan = super().leaf_plan(mid)
        f, m = self.f, self.f.state()['modules'][mid]
        analysis = read_json(check_ref(plan['dimension_analysis_ref']))
        home = Path(m['write_paths'][0])
        for row in analysis['dimensions']:
            for item in row['items'] if row['dimension'] == 'Resource' else []:
                item.update(target_resource=str(home / 'icon.svg'), consumer=str(home / 'code.py'))
        plan['dimension_analysis_ref'] = f.ref('analysis-' + mid + '.json', analysis)
        for task in plan['tasks']:
            task['dimension_analysis']['parent_ref'] = plan['dimension_analysis_ref']
        automation = [p['path_id'] for p in plan['paths'] if p['kind'] == 'automation']
        traced = {row['item_id'] for row in plan['dimension_trace']}
        held = {}
        for row in analysis['dimensions']:
            for item in row['items'] if row['status'] == 'applicable' else []:
                held.setdefault(row['dimension'], []).append(item['item_id'])
                if item['item_id'] not in traced:
                    plan['dimension_trace'].append({'item_id': item['item_id'], 'task_ids': ['T1'], 'path_ids': automation,
                                                    'assertions': [{'path_id': pid, 'assertion_id': 'A1'} for pid in automation]})
        for task in plan['tasks']:
            for row in task['dimension_analysis']['dimensions']:
                if held.get(row['dimension']):
                    row.update(status='applicable', item_ids=held[row['dimension']])
        if m.get('change_request'):  # reopened for what the first plan owed
            plan['source_closure'].update(ui_renderers=['ui/' + m['name'] + 'Activity.java'], ui_topology='list with a header image',
                                          states=['loading', 'content', 'empty'], navigation='opened from the search entry; back returns',
                                          platform_lifecycle='no permissions; data through the repository; cancelled on leave')
            ids = ' '.join(iid for ids in held.values() for iid in ids)
            definitions = []
            for d in plan['definitions']:
                if d['kind'] in ('spec', 'design', 'tasks'):  # the documents gain a line; nothing in them changes
                    target = Path(d['path']).with_name('revised-' + Path(d['path']).name)
                    target.write_text(check_ref(d).read_text() + '\n' + ids + '\n')
                    d = {**file_ref(target), 'kind': d['kind']}
                definitions.append(d)
            plan['definitions'] = definitions
        return plan

    def code(self, mid, a):
        """What the Implementer submits: the code, the resource where the plan put it, evidence for every item."""
        out = super().code(mid, a)
        m = self.f.state()['modules'][mid]
        analysis = read_json(check_ref(m['plan']['dimension_analysis_ref']))
        items = [(row['dimension'], item) for row in analysis['dimensions'] if row['status'] == 'applicable' for item in row['items']]
        files, proof = list(out['code_files']), out['dimension_evidence'][0]['evidence_refs']
        traces = []
        for dimension, item in items:
            trace = {'item_id': item['item_id'], 'task_ids': ['T1'], 'summary': dimension + ' implemented', 'evidence_refs': proof}
            if dimension == 'Resource':
                target = Path(item['target_resource']); target.write_text('<svg/>\n'); files.append(file_ref(target))
                trace.update(target_resource_ref=file_ref(target), consumer_refs=[file_ref(Path(item['consumer']))])
            traces.append(trace)
        out.update(code_files=files, code_baseline=baseline(files), dimension_evidence=traces)
        out['task_trace'][0]['files'] = [ref['path'] for ref in files]
        return out


class UiLeafRunTests(UiLeafWalk):
    def test_a_run_of_screen_leaves_ends_unverified_with_what_each_plan_owed_settled_and_its_code_kept(self):
        taken, st = self.walk(120)
        turns = {}
        for row in self.setup_turns + taken:
            turns[row['role']] = turns.get(row['role'], 0) + 1
        card = max(row['card_bytes'] for row in taken)
        if sum(turns.values()) > sum(RECORDED.values()) or card > RECORDED_CARD:
            warnings.warn('the screen run took %s and a %d-byte card, recorded %s and %d: %s' % (turns, card, RECORDED, RECORDED_CARD, json.dumps(taken)))
        self.assertEqual(turns, RECORDED)
        self.assertEqual(st['global_next_step']['reason'], 'completed-with-unverified-tests')  # no device: its cases are owed a device
        s = self.f.state()
        for mid in ('M011', 'M012'):
            m = s['modules'][mid]
            self.assertEqual(m['phase'], 'completed')
            owed = {k: v for k, v in s['issues'].items() if k.startswith('OWED-' + mid)}
            self.assertTrue(owed and all(mid in v['resolved'] for v in owed.values()))  # what the first plan owed, settled by the revision
            self.assertEqual((m['task_revalidation']['mode'], m['task_revalidation']['retained_task_ids']), ('partial', ['T1']))  # the code stays
        reopened = [row for row in workflow_cost.journal(self.f.root) if row['operation'] == 'change']
        self.assertEqual({row['actor']['role'] for row in reopened}, {'module-orchestrator'})
        self.assertTrue(all(row['request_id'].startswith('advance-') for row in reopened))  # opened by the Ledger, no model turn


if __name__ == '__main__':
    unittest.main()
