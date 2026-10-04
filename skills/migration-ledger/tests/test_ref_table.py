"""A file reference is written once under `refs` and cited by id; readers see the document written out."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import context_readiness as cr
import dimensions
import ledger
import test_context_readiness
import test_dimensions
import test_ledger
from contracts import REF_LISTS, Rejected, digest, expand_refs, read_json

REF = {'path': '/legacy/a.md', 'sha256': 'a' * 64}
OTHER = {'path': '/legacy/b.md', 'sha256': 'b' * 64}


def tabled(document):
    """The same document with every evidence and context reference moved into a refs table and cited by id."""
    table, ids = {}, {}

    def cite(ref):
        key = json.dumps(ref, sort_keys=True)
        if key not in ids:
            ids[key] = 'E%d' % (len(ids) + 1)
            table[ids[key]] = ref
        return ids[key]

    def walk(value):
        if isinstance(value, dict):
            return {key: [cite(item) if isinstance(item, dict) and set(item) == {'path', 'sha256'} else walk(item) for item in items]
                    if key in REF_LISTS and isinstance(items, list) else walk(items) for key, items in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value
    result = walk(document)
    result['refs'] = table
    return result


class ExpandTests(unittest.TestCase):
    def test_a_citation_is_the_reference_it_names_and_the_table_is_gone(self):
        document = {'refs': {'E1': REF}, 'rows': [{'evidence_refs': ['E1', OTHER], 'notes': ['E1']}], 'context_refs': ['E1']}
        self.assertEqual(expand_refs(document), {'rows': [{'evidence_refs': [REF, OTHER], 'notes': ['E1']}], 'context_refs': [REF]})
        self.assertIn('refs', document)  # the author's document is not touched

    def test_an_unknown_id_is_rejected_and_what_is_not_a_table_is_left_alone(self):
        with self.assertRaisesRegex(Rejected, 'unknown reference id E2; the document lists E1'):
            expand_refs({'refs': {'E1': REF}, 'evidence_refs': ['E2']})
        for document in ({'evidence_refs': [REF]}, {'refs': ['a'], 'evidence_refs': [REF]}, {'refs': {'E1': {'path': 1}}},
                         {'refs': {}}, ['E1']):
            self.assertEqual(expand_refs(document), document)

    def test_every_reader_gets_the_written_out_form(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'doc.json'
            path.write_text(json.dumps({'refs': {'E1': REF}, 'items': [{'evidence_refs': ['E1']}]}))
            self.assertEqual(read_json(path), {'items': [{'evidence_refs': [REF]}]})


class AuthoredDocumentTests(unittest.TestCase):
    def test_a_dimension_analysis_cites_its_evidence_by_id_and_stays_hash_bound(self):
        d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f
        analysis = d.analysis('M010')
        written = f.ref('written-out.json', analysis)
        by_id = f.ref('by-id.json', tabled(analysis))
        self.assertLess(len(Path(by_id['path']).read_bytes()), len(Path(written['path']).read_bytes()))
        self.assertEqual(dimensions.load(by_id, 'M010'), dimensions.load(written, 'M010'))  # one content, one form
        broken = tabled(analysis)
        broken['dimensions'][0]['evidence_refs'] = ['E99']
        with self.assertRaisesRegex(Rejected, 'unknown reference id E99'):
            dimensions.load(f.ref('broken.json', broken), 'M010')
        (f.base / 'dimension-source.md').write_text('changed after the table was written')
        with self.assertRaisesRegex(Rejected, 'evidence hash mismatch'):  # what a table lists is hashed like any reference
            dimensions.load(by_id, 'M010')

    def test_the_ledger_archives_what_a_table_lists_and_a_wrong_id_cannot_hide(self):
        d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f
        analysis = d.analysis('M010')
        proof = analysis['dimensions'][0]['evidence_refs'][0]
        root = f.root.resolve()
        saved = ledger.preserve_refs(root, f.ref('archived.json', tabled(analysis)))
        self.assertIn(proof['path'], {row['source_path'] for row in saved})
        broken = tabled(analysis)
        broken['dimensions'][0]['evidence_refs'] = ['E99']
        with self.assertRaisesRegex(Rejected, 'unknown reference id'):
            ledger.preserve_refs(root, f.ref('wrong-id.json', broken))

    def test_a_plan_is_stored_and_hashed_written_out_whichever_form_its_author_used(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()
        plan = f.plan()
        by_id = tabled(plan)
        self.assertTrue(by_id['refs'] and by_id['source_closure']['evidence_refs'][0].startswith('E'))
        f.call('plan', {'plan_ref': f.ref('plan-by-id.json', by_id)}, role='spec-designer')
        m = f.state()['modules']['M001']
        self.assertNotIn('refs', m['plan'])
        self.assertEqual(m['plan']['source_closure']['evidence_refs'], plan['source_closure']['evidence_refs'])
        self.assertEqual(m['plan_hash'], digest(plan))  # one content, one hash

    def test_a_preflight_report_cites_its_evidence_by_id(self):
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        report = f.report('coding')
        ref = f.record(tabled(report))
        self.assertIn('refs', json.loads(Path(ref['path']).read_text()))
        self.assertEqual(f.state()['modules']['M001']['context_receipts']['coding:implementer']['verdict'], 'ready')
        cr.validate(f.state(), 'M001', 'coding', ref)


if __name__ == '__main__':
    unittest.main()
