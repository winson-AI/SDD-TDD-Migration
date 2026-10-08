"""How the target takes resources is settled before UI work is registered, a stated convention is used, and an API call
is addressed the way its transport addresses it."""
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import api_contract
import dimensions
import project_context as pc
import resource_copy
from contracts import Rejected
import test_context_readiness
import test_dimensions
import test_progressive_fidelity
import test_resource_copy
import test_run_changes


class ConventionTests(unittest.TestCase):
    def test_a_part_the_target_does_not_take_is_declined_with_its_reason(self):
        declined = {'declined': {'copy': 'the target bundles no files', 'parameters': 'values are typed in the design system'}}
        self.assertEqual(pc.target_resources(declined), declined)
        self.assertEqual(pc.target_resources({}), {})
        for bad in ({'declined': {'copy': ' '}}, {'declined': {'fonts': 'not a part'}}, {'declined': 'none of it'}):
            with self.subTest(bad=bad), self.assertRaisesRegex(Rejected, 'declined gives the reason'):
                pc.target_resources(bad)

    def test_a_part_is_stated_or_declined_never_both(self):
        c = test_resource_copy.CopyPlanTests('test_every_file_resource_the_target_loads_gets_a_row_with_its_path_and_name')
        c.setUp(); self.addCleanup(c.doCleanups)
        stated = pc.target_resources({'copy': c.rules, 'declined': {'parameters': 'no generated file'}}, str(c.n.target))
        self.assertEqual((sorted(stated), stated['declined']), (['copy', 'declined'], {'parameters': 'no generated file'}))
        with self.assertRaisesRegex(Rejected, 'names no part it states'):
            pc.target_resources({'copy': c.rules, 'declined': {'copy': 'and yet'}}, str(c.n.target))


class SettledBeforeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_run_changes.PreparedRunRevisionTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f, self.d = t.f, t.source.d

    def module(self, *kinds):
        analysis = self.d.analysis('M020', kinds)
        proof = analysis['dimensions'][0]['evidence_refs'][0]
        for row in analysis['dimensions']:
            if row['status'] == 'applicable' and row['dimension'] in dimensions.CONDITION_FACETS:
                row['condition_review'] = {facet: {'reason': 'Reviewed source; no conditional variant', 'evidence_refs': [proof],
                                                   'condition_refs': []} for facet in dimensions.CONDITION_FACETS[row['dimension']]}
        return {'module_id': 'M020', 'case_ids': ['C1'], 'scope': analysis['scope'],
                'dimension_analysis_ref': self.f.ref('m020-dimensions.json', analysis)}

    def test_ui_work_is_registered_once_the_run_knows_how_the_target_takes_it(self):
        state = self.f.state()
        self.assertTrue(state['planning_coverage_required'])
        self.assertEqual(state['target_resources'], {})
        dimensions.allocation(state, self.module('Logic'))  # nothing to copy, nothing to fill
        with self.assertRaisesRegex(Rejected, r'target_resources\.copy is not settled'):
            dimensions.allocation(state, self.module('Logic', 'UI'))
        with self.assertRaisesRegex(Rejected, r'target_resources\.copy is not settled'):
            dimensions.allocation(state, self.module('Logic', 'Resource'))
        state['target_resources'] = {'declined': {'copy': 'the target bundles no files'}}
        dimensions.allocation(state, self.module('Logic', 'Resource'))  # resources alone fill no parameter file
        with self.assertRaisesRegex(Rejected, r'target_resources\.parameters is not settled'):
            dimensions.allocation(state, self.module('Logic', 'UI'))
        state['target_resources']['declined']['parameters'] = 'values are typed in the design system'
        with self.assertRaisesRegex(Rejected, r'test_adapter\.device is not settled'):  # nor where a user-visible case is verified
            dimensions.allocation(state, self.module('Logic', 'UI'))
        with mock.patch.object(pc, 'device_verification', return_value={'platforms': ['android']}):
            dimensions.allocation(state, self.module('Logic', 'UI'))

    def test_an_analysis_the_ledger_already_holds_is_not_asked_again(self):
        state, module = self.f.state(), self.module('Logic', 'UI')
        state['modules']['M020'] = {'dimension_analysis_ref': module['dimension_analysis_ref']}
        dimensions.allocation(state, module)

    def test_a_run_settles_it_through_a_reviewed_context_revision(self):
        f, t = self.f, self.t
        report = t.report({'target_resources': {'declined': {'copy': 'the target bundles no files',
                                                             'parameters': 'values are typed in the design system'}},
                           'test_adapter': {'device': {'unavailable': 'this task has no device farm'}}}, affected=())
        ref = f.ref('settle-resources.json', report)
        receipt = f.ref('settle-context.json', f.report('global-planning', module=None, draft=ref))
        f.raw('run-review', {'report_ref': ref, 'context_ref': receipt}, role='global-orchestrator', module=None)
        step = f.state()['global_next_step']
        self.assertEqual((step['operation'], step['ready']), ('revise-run', True))
        f.call('revise-run', step['payload'], role='host', module=None)
        state = f.state()
        self.assertEqual(sorted(state['target_resources']['declined']), ['copy', 'parameters'])
        self.assertEqual(pc.device_verification(state), {'unavailable': 'this task has no device farm'})
        dimensions.allocation(state, self.module('Logic', 'UI'))


class SettledBeforeTheFirstRootTests(unittest.TestCase):
    def test_a_run_with_no_registered_root_settles_it_the_same_way(self):
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        old = f.state(); f.root = (f.base / '.sdd-runs/demo').resolve()
        actor = {'role': 'host', 'instance_id': 'host'}
        pc.update(f.base / '.sdd-migration', {'schema_version': 1, 'project_id': 'demo', 'request_id': 'config', 'expected_revision': 0,
                  'patch': {'legacy_root': str(f.legacy), 'target_root': str(f.target), 'architecture_path': old['new_architecture']['path']},
                  'source_ref': f.ref('user-config.md', 'Use these roots')}, actor, True)
        prepared = pc.prepare(f.base / '.sdd-migration', f.root, {'schema_version': 1, 'project_id': 'demo', 'request_id': 'prepare',
                              'run_id': 'demo', 'source_ref': f.ref('user-run.md', 'Migrate fixture')}, actor)
        f.call('init', {**{k: old[k] for k in ('target_root', 'legacy_root', 'global_spec', 'case_ids', 'requirement_ids')},
               'new_architecture': prepared['input']['new_architecture'], 'project_context_ref': prepared['project_context_ref'],
               'global_paths': []}, role='host')
        self.assertEqual(f.state()['modules'], {})  # nothing registered yet: the registry is not judged for coverage here
        report = {'schema_version': 1, 'run_id': 'demo', 'reason': 'Target resource convention read from the target project',
                  'context_patch': {'target_resources': {'declined': {'copy': 'the target bundles no files'}}},
                  'root_updates': [], 'modules': [],
                  'boundary_review': {'semantic_change': False, 'authorization_change': False, 'unresolved_questions': [],
                                      'reason': 'Configuration only', 'evidence_refs': [f.ref('boundary.md', 'Original goal kept')]}}
        ref = f.ref('settle.json', report)
        receipt = f.ref('settle-context.json', f.report('global-planning', module=None, draft=ref))
        f.raw('run-review', {'report_ref': ref, 'context_ref': receipt}, role='global-orchestrator', module=None)
        f.call('revise-run', f.state()['global_next_step']['payload'], role='host', module=None)
        self.assertEqual(f.state()['target_resources'], {'declined': {'copy': 'the target bundles no files'}})


class ManualReplacementTests(unittest.TestCase):
    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)

    def test_a_planned_picture_replaced_by_hand_states_what_stops_the_copy(self):
        f = self.d.f
        analysis = self.d.analysis('M001', ('Logic', 'Resource'))
        item = analysis['dimensions'][3]['items'][0]
        item.update(source_resource='@drawable/ic_back', resource_kind='vector', resource_strategy='manual_exact',
                    adaptation_evidence_ref=f.ref('replacement-review.md', 'inspected against the legacy rendering'))
        with self.assertRaisesRegex(Rejected, 'copy_blocker'):
            dimensions.judge(f.ref('replaced.json', analysis), 'M001')
        item['copy_blocker'] = 'the target loads no vector drawable'
        dimensions.judge(f.ref('replaced.json', analysis), 'M001')
        item.pop('copy_blocker'); item.update(source_resource='@string/title', resource_kind='string')
        dimensions.judge(f.ref('replaced.json', analysis), 'M001')  # a value has no file to copy


class StatedConventionTests(unittest.TestCase):
    def setUp(self):
        self.c = c = test_resource_copy.CopyPlanTests('test_every_file_resource_the_target_loads_gets_a_row_with_its_path_and_name')
        c.setUp(); self.addCleanup(c.doCleanups)

    def test_files_the_target_loads_are_copied_by_the_plan_not_authored_one_by_one(self):
        c = self.c
        self.assertTrue(c.plan()[0]['rows'])
        with self.assertRaisesRegex(Rejected, 'names its copy_plan_ref'):
            resource_copy.freeze_check(c.state(), c.f.analysis)
        c.adopt()
        resource_copy.freeze_check(c.state(), c.f.analysis)

    def test_without_a_convention_or_without_a_loadable_file_no_plan_is_owed(self):
        c = self.c
        resource_copy.freeze_check(c.state(target_resources={'declined': {'copy': 'the target bundles no files'}}), c.f.analysis)
        unloadable = resource_copy.convention({**c.rules, 'formats': ['gif']})
        self.assertEqual(c.plan(unloadable)[0]['rows'], [])
        resource_copy.freeze_check(c.state(target_resources={'copy': unloadable}), c.f.analysis)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.a = a = test_progressive_fidelity.ApiContractTests(); a.setUp(); self.addCleanup(a.doCleanups)
        for key in ('method', 'url'):
            a.source.pop(key)
        a.source.update(transport='rpc', operation='account.getSettings')

    def contract(self, **target):
        contract = copy.deepcopy(self.a.contract)
        for key in ('method', 'url'):
            contract['target'].pop(key)
        contract['target'].update({'transport': 'rpc', 'operation': 'account.getSettings', **target})
        return contract

    def test_a_remote_procedure_is_registered_by_its_operation(self):
        a = self.a
        calls, contracts = api_contract.load(a.analysis(self.contract()), a.items)
        self.assertEqual((calls['QUERY']['transport'], calls['QUERY']['operation']), ('rpc', 'account.getSettings'))
        self.assertEqual(contracts['QUERY']['item_id'], 'D')
        api_contract.plan(a.analysis(self.contract()), a.items, a.plan())  # the route and every facet are still owed

    def test_an_exact_contract_keeps_the_transport_and_the_operation(self):
        a = self.a
        for change in ({'operation': 'account.getOther'}, {'transport': 'sdk'}):
            with self.subTest(change=change), self.assertRaisesRegex(Rejected, 'exact route changed'):
                api_contract.load(a.analysis(self.contract(**change)), a.items)
        adapted = self.contract(transport='sdk')
        adapted.update(fidelity='approved-adaptation', alternative='call the vendor client', reason='the target ships the client library')
        api_contract.load(a.analysis(adapted), a.items)

    def test_a_call_names_how_it_is_addressed(self):
        a = self.a
        with self.assertRaisesRegex(Rejected, 'API target operation required for rpc'):
            api_contract.load(a.analysis(self.contract(operation=' ')), a.items)
        a.source.pop('operation')
        with self.assertRaisesRegex(Rejected, 'API source operation required for rpc'):
            api_contract.load(a.analysis(self.contract()), a.items)
        a.source.update(transport='carrier-pigeon', operation='account.getSettings')
        with self.assertRaisesRegex(Rejected, 'API transport must be http, rpc or sdk'):
            api_contract.load(a.analysis(self.contract()), a.items)
        a.source['transport'] = 'http'  # an HTTP call is still a method and a URL
        with self.assertRaisesRegex(Rejected, 'API source method/URL required'):
            api_contract.load(a.analysis(self.contract()), a.items)


if __name__ == '__main__':
    unittest.main()
