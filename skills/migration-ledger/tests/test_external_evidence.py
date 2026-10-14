"""What the run reads but did not write - a legacy source, a library jar, a checkout - is cited by hash and left where it
is; the archive holds what the run and the package wrote. A projection of the Ledger is never evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_ledger
from contracts import Rejected, digest, file_ref


class ExternalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def test_an_input_outside_the_run_is_listed_once_and_not_copied(self):
        f = self.f
        legacy = f.legacy / 'LoginActivity.java'; legacy.write_text('class LoginActivity {}' * 2000)
        f.global_plan()
        plan = f.plan()
        cited = file_ref(legacy); legacy = Path(cited['path'])  # the reference names the resolved path
        plan['source_closure']['legacy_evidence'] = [cited]
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        state, events = ledger.read_events(f.root)
        row = next(x for e in events for x in e.get('artifact_snapshots', []) if x.get('source_path') == str(legacy))  # the plan event, or a gap it recorded after
        self.assertEqual(row['status'], 'external-reference')
        self.assertFalse((f.root / 'artifacts' / row['sha256']).exists())  # cited by hash, left where it is
        f.approve(digest(plan), 'D1')
        _, events = ledger.read_events(f.root)
        self.assertEqual(sum(1 for e in events for x in e.get('artifact_snapshots', []) if x.get('source_path') == str(legacy)), 1)  # once
        archived = next(x for e in events for x in e.get('artifact_snapshots', []) if x['source_path'].endswith('/plan.json'))
        self.assertTrue(Path(archived['path']).exists())  # what the run wrote is archived

    def test_reuse_checkouts_and_dependency_stores_are_external_inputs(self):
        f = self.f
        self.assertEqual(ledger.external_roots({'legacy_root': str(f.legacy), 'reuse_sources': [{'source_id': 'lib', 'root': str(f.base / 'lib')}]}),
                         [f.legacy.resolve(), (f.base / 'lib').resolve()])
        self.assertTrue(ledger.external(str(f.base / 'lib' / 'Api.kt'), ledger.external_roots({'reuse_sources': [{'root': str(f.base / 'lib')}]})))
        self.assertTrue(ledger.external('/home/dev/.gradle/caches/modules-2/files-2.1/lib/1.0/x/lib.jar', []))  # a build tool's store
        self.assertFalse(ledger.external(str(f.base / 'staging' / 'plan.json'), ledger.external_roots({'legacy_root': str(f.legacy)})))  # what the run wrote

    def test_a_ledger_projection_is_not_evidence(self):
        f = self.f
        f.global_plan()
        plan = f.plan()
        projection = f.root / 'ledger' / 'global.json'
        self.assertTrue(projection.exists())
        plan['source_closure']['projection'] = [file_ref(projection)]
        with self.assertRaisesRegex(Rejected, 'ledger projection is not evidence'):
            f.call('plan', {'plan_ref': f.ref('plan-projection.json', plan)}, role='spec-designer')


if __name__ == '__main__':
    unittest.main()
