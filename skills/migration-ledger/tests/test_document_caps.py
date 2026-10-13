"""An authored document states its decisions and cites the source; the Ledger refuses one that restates it at length."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import control_policy
import spec_skeleton
from contracts import Rejected, check_ref, file_ref
import test_control_policy
import test_source_changes


class DocumentCapTests(unittest.TestCase):
    def setUp(self):
        t = test_control_policy.ControlPolicyTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = t.f; self.f.global_plan()

    def swell(self, plan, kind, size):
        d = next(d for d in plan['definitions'] if d['kind'] == kind); path = check_ref(d)
        path.write_text(path.read_text() + '\n' + 'x' * (size - path.stat().st_size - 1)); d.update(file_ref(path))

    def test_each_document_has_a_size_and_the_set_has_one(self):
        f = self.f
        p = f.plan(); self.swell(p, 'design', control_policy.DOCUMENT_BYTES['design'])
        f.call('plan', {'plan_ref': f.ref('at-the-cap.json', p)}, role='spec-designer')
        for kind, cap in control_policy.DOCUMENT_BYTES.items():
            bad = f.plan(); self.swell(bad, kind, cap + 1)
            with self.subTest(kind=kind), self.assertRaisesRegex(Rejected, f'{kind} over {cap // 1000} KB'):
                f.call('plan', {'plan_ref': f.ref(f'over-{kind}.json', bad)}, role='spec-designer')
        full = f.plan()
        for kind, cap in control_policy.DOCUMENT_BYTES.items():
            self.swell(full, kind, cap)
        full['definitions'] += [{**f.ref(f'defs/spec-{name}.md', 'y' * 12_000), 'kind': 'spec'} for name in ('alpha', 'beta')]
        with self.assertRaisesRegex(Rejected, 'definitions over 60 KB'):
            control_policy.document_sizes(full)

    def test_the_test_plan_the_fixture_contract_and_an_empty_reuse_plan_have_sizes(self):
        f = self.f
        big = f.ref('big.json', {'filler': 'z' * 20_000})
        with self.assertRaisesRegex(Rejected, 'upstream test plan over 20 KB'):
            control_policy.document_sizes({'definitions': [], 'test_design_ref': big})
        with self.assertRaisesRegex(Rejected, 'fixture contract over 20 KB'):
            control_policy.document_sizes({'definitions': [], 'source_closure': {'verification': {'fixture_contract_ref': big}}})
        review = {'mappings': [{'mapping_id': 'MAP1', 'decision': 'new', 'rationale': 'r' * 2_000}]}
        with self.assertRaisesRegex(Rejected, 'reuse plan over 2 KB'):
            control_policy.document_sizes({'definitions': [], 'reuse_plan_ref': f.ref('all-new.json', review)})
        review['mappings'].append({'mapping_id': 'MAP2', 'decision': 'adapt', 'capability_id': 'CAP1'})
        control_policy.document_sizes({'definitions': [], 'reuse_plan_ref': f.ref('one-adapted.json', review)})  # it maps something

    def test_the_skeleton_cites_the_allocation_and_has_no_decisions_section(self):
        t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        result = spec_skeleton.write(t.f.root, 'M001', t.f.root / 'staging/spec-designer/skeleton')
        text = {name: check_ref(ref).read_text() for name, ref in result['files'].items()}
        self.assertNotIn('## Decisions', text['design.md'])
        self.assertIn('dimension_analysis_ref', text['design.md']); self.assertIn('M001-Logic', text['design.md'])
        out = t.f.state()['modules']['M001']['scope']['out']
        for name in ('proposal.md', 'design.md'):
            self.assertIn(f'scope.out（{len(out)} 条）', text[name])
            for line in out:
                self.assertNotIn(f'- {line}\n', text[name])


if __name__ == '__main__':
    unittest.main()
