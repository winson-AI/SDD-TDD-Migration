"""Approved same-Run contract retirement preserves history and requires goal audit."""
import copy
import unittest

import test_run_changes
import ledger
import run_changes
import audit_code_review
import migration_report
from contracts import Rejected, digest, read_json, check_ref


class ContractRetirementTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_changes.RootRevisionTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.f = f = self.fixture.f


    def report(self):
        f = self.f
        update = self.fixture.update('M010')
        update['scope']['requirement_ids'] = ['R2']; update['case_ids'] = ['C2']
        report = self.fixture.report([update])
        proof = f.ref('retirement-source.md', 'Original requirement was incorrectly allocated; explicit new behavior and coverage reviewed')
        path = copy.deepcopy(f.state()['global_paths'][0]); path.update(path_id='GP2', case_id='C2', requirement_id='R2')
        report.update(global_spec_ref=f.ref('replacement-spec.md', 'R2: corrected host requirement; C2: acceptance'),
            contract_patch={'requirement_ids': ['R2'], 'case_ids': ['C2'], 'global_paths': [path]},
            boundary_review={'semantic_change': True, 'authorization_change': False, 'unresolved_questions': [],
                             'reason': 'Replace the incorrect contract after human review', 'evidence_refs': [proof]},
            retirements=[{'kind': kind, 'id': old, 'replacement_ids': [new], 'reason': 'Incorrect upstream contract',
                          'evidence_refs': [proof]} for kind, old, new in
                         [('requirement', 'R1', 'R2'), ('case', 'C1', 'C2'), ('global-path', 'GP1', 'GP2')]])
        return report

    def review(self, report):
        f = self.f
        f.call('run-review', {'report_ref': f.ref(f'revision-{f.n}.json', report)}, role='global-orchestrator', module=None)
        return {'subject_sha256': f.state()['run_change_review']['subject_sha256']}

    def apply(self, report):
        f = self.f; payload = self.review(report); did = f'RET-{f.n}'
        f.call('decision', {'decision_id': did, 'decision': 'approved', 'module_id': None, **payload,
            'human_source_ref': f.ref('human-retirement.md', 'Approve this exact retirement and impact set')}, role='host', module=None)
        f.call('revise-run', {**payload, 'decision_id': did}, role='host', module=None)
        return f.state()

    def test_retirement_requires_exact_human_and_survives_replay(self):
        f = self.f; before = f.state(); report = self.report()
        payload = self.review(report)
        with self.assertRaisesRegex(Rejected, 'exact human decision'):
            f.call('revise-run', payload, role='host', module=None)
        s = self.apply(report)
        self.assertEqual(s['run_id'], before['run_id'])
        self.assertEqual(s['max_fix_rounds'], before['max_fix_rounds'])
        self.assertEqual(s['requirement_ids'], ['R2']); self.assertEqual(s['case_ids'], ['C2'])
        self.assertEqual(s['run_change_history'][-1]['previous_contract']['case_ids'], ['C1'])
        self.assertEqual(run_changes.retirements(ledger.read_events(f.root)[0]), run_changes.retirements(s))
        self.assertTrue(s['module_groups']['M010']['replanning_required'])
        summary = migration_report.build(f.root, s, s['last_sequence'])
        self.assertEqual(len(summary['contract_retirements']), 3)
        self.assertNotIn('C1', [r['case_id'] for r in summary['paths']])
        self.assertNotIn('GP1', [r['path_id'] for r in summary['paths']])
        self.assertIn('不计为测试成功', migration_report.render(summary))

    def test_no_silent_deletion_invalid_replacement_or_unaffected_owner(self):
        report = self.report()
        variants = [lambda r: r.pop('retirements'),
                    lambda r: r['retirements'][0].update(replacement_ids=['UNKNOWN']),
                    lambda r: r['retirements'].append(copy.deepcopy(r['retirements'][0])),
                    lambda r: r['boundary_review'].update(semantic_change=False),
                    lambda r: r['modules'][0].update(action='unchanged')]
        for index, change in enumerate(variants):
            bad = copy.deepcopy(report); change(bad)
            with self.subTest(index=index), self.assertRaises(Rejected):
                run_changes.validate(self.f.state(), self.f.ref(f'bad-{index}.json', bad))

    def test_retired_ids_cannot_be_reintroduced(self):
        s = self.apply(self.report())
        with self.assertRaisesRegex(Rejected, 'cannot be reused'):
            run_changes.contract(s, {'contract_patch': {'requirement_ids': ['R2', 'R1']},
                'global_spec_ref': self.f.ref('reuse-id.md', 'New requirements need new IDs')})

    def test_explicit_retirement_without_replacement_remains_auditable(self):
        report = self.report()
        for row in report['retirements']: row['replacement_ids'] = []
        s = self.apply(report)
        self.assertTrue(all(r['replacement_ids'] == [] for r in run_changes.retirements(s)))
        self.assertIn('retirements_sha256', audit_code_review.snapshot(s))

    def test_global_red_is_archived_when_path_is_retired_not_turned_green(self):
        # Exercise the transaction with an already accepted prior failure.
        f = self.f; s = f.state(); report = self.report()
        s['audit_results'] = {'GP1': {'quality': 'red-bug', 'executed': True, 'test_run_id': 'failed-attempt',
                                     'evidence_ref': f.ref('failed.log', 'Observed failure')}}
        ref = f.ref('failed-revision.json', report)
        run_changes.handle(f.root, s, {'operation': 'run-review', 'payload': {'report_ref': ref}},
                           {'role': 'global-orchestrator', 'instance_id': 'GO'})
        subject = s['run_change_review']['subject_sha256']
        s['decisions']['RET'] = {'decision': 'approved', 'module_id': None, 'consumed': False,
            'subject_sha256': subject, 'human_source_ref': f.ref('failed-retirement.md', 'Approve this exact revision')}
        run_changes.handle(f.root, s, {'operation': 'revise-run', 'payload': {'subject_sha256': subject, 'decision_id': 'RET'}},
                           {'role': 'host', 'instance_id': 'host'})
        self.assertNotIn('GP1', s['audit_results'])
        old = next(r for r in run_changes.retirements(s) if r['kind'] == 'global-path')
        self.assertEqual(old['previous_result']['quality'], 'red-bug')
        self.assertEqual(read_json(check_ref(old['revision_ref']))['retirements'], report['retirements'])

    def test_auditor_must_review_each_approved_disposition(self):
        s = self.apply(self.report()); f = self.f
        evidence = f.ref('audit-dispositions.md', 'Compared original goal, precise approval, replacements and current coverage')
        goal = {'global_spec_ref': s['global_spec'], 'origin_spec_ref': s['run_change_history'][0]['previous_global_spec'],
            'feature_ids': [], 'requirements': [{'requirement_id': 'R2', 'conclusion': 'satisfied', 'reason': 'Trace reviewed',
                'evidence_refs': [evidence], 'tasks': [], 'path_ids': ['GP2']}]}
        report = {'goal_review': goal, 'findings': []}
        with self.assertRaisesRegex(Rejected, 'every approved retirement'): audit_code_review.goal_review(s, report)
        goal['retirement_reviews'] = [{**{k:r[k] for k in ('kind', 'id', 'revision_ref', 'decision_id')},
            'conclusion': 'confirmed', 'reason': 'Approved disposition preserves revised goal coverage',
            'evidence_refs': [evidence]} for r in run_changes.retirements(s)]
        self.assertIn(evidence, audit_code_review.goal_review(s, report))
        goal['retirement_reviews'][0]['decision_id'] = 'UNRELATED'
        with self.assertRaisesRegex(Rejected, 'approved revision'): audit_code_review.goal_review(s, report)
