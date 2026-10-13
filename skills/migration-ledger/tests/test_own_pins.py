"""A leaf pins by hash only the target files it writes: what another leaf or the host writes changes under it, and a
leaf that needs it cites the provider's plan or contract, which the Ledger holds."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reading
import test_ledger
from contracts import Rejected, file_ref


class OwnPinsTests(unittest.TestCase):
    def test_a_plan_pinning_another_leafs_target_file_is_refused_and_its_own_is_not(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()
        other = f.target / 'm2' / 'settings.kts'; other.parent.mkdir(exist_ok=True); other.write_text('include(":m2")')
        plan = f.plan(); plan['source_closure']['wiring_evidence'] = [file_ref(other)]
        with self.assertRaisesRegex(Rejected, 'pins only its own target files') as caught:
            f.call('plan', {'plan_ref': f.ref('pinned.json', plan)}, role='spec-designer')
        self.assertEqual(reading.read_hint(str(caught.exception))['section'], '验证边界')
        own = f.target / 'm1' / 'code.py'; own.parent.mkdir(exist_ok=True); own.write_text('value = 1')
        plan = f.plan(); plan['source_closure']['wiring_evidence'] = [file_ref(own)]
        f.call('plan', {'plan_ref': f.ref('own.json', plan)}, role='spec-designer')  # its own file, under its write scope


if __name__ == '__main__':
    unittest.main()
