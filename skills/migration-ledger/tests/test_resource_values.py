"""A value the parameter sheet carries travels by the sheet: it needs no Resource item of its own."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import resource_fidelity as rf
import ui_parameters
from contracts import Rejected, file_ref
import test_resource_usage


class SheetCarriesValuesTests(unittest.TestCase):
    def setUp(self):
        self.u = u = test_resource_usage.UsageClosureTests('test_a_use_outside_the_excluded_symbol_keeps_the_obligation')
        u.setUp(); self.addCleanup(u.doCleanups)
        c = u.c
        c.write('res/values/extra.xml', '<resources><string name="hint">Hint</string></resources>')
        c.write('res/values-de/extra.xml', '<resources><string name="hint">Hinweis</string></resources>')
        c.code('\nfun hint() { label.setText(getString(R.string.hint)) }\n')
        c.declare('@string/hint'); u.s.recollect()

    def bind_sheet(self):
        u = self.u
        ui = u.f.analysis['dimensions'][0]
        ui['parameter_sheet_ref'] = file_ref(u.n.write('evidence/parameter-sheet.json', ui_parameters.derive(u.f.analysis)))

    def closure(self):
        """The closure gates of a freeze; how the sheet's parameters are written to the target has its own tests."""
        import ui_fidelity
        u = self.u
        module = u.f.module()
        analysis = ui_fidelity._analysis(module)
        ui_fidelity.allocation_gate({**u.f.state, 'legacy_root': str(u.n.android)}, analysis)

    def test_a_declared_text_without_item_or_sheet_reduces_the_closure(self):
        with self.assertRaisesRegex(Rejected, 'uncovered presentation refs: .*@string/hint'):
            self.closure()
        self.assertEqual(rf.carried(self.u.f.analysis), set())

    def test_the_sheet_covers_the_value_and_its_variants(self):
        self.bind_sheet()
        self.assertIn('@string/hint', rf.carried(self.u.f.analysis))
        self.assertNotIn('@string/hint', rf.closure_gaps(self.u.f.analysis, ['@string/hint', '@drawable/not_in_the_sheet']))
        self.assertIn('@drawable/not_in_the_sheet', rf.closure_gaps(self.u.f.analysis, ['@string/hint', '@drawable/not_in_the_sheet']))
        self.closure()  # neither an item for the text nor one for its German variant


if __name__ == '__main__':
    unittest.main()
