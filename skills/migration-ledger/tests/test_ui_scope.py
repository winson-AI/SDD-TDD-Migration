"""A screen that is one class of a large source file is collected alone: an entry `path#Class` indexes that class,
and `path#Class.member` one function of it."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lean_tools import collect_ui_sources
import test_resource_signals

SCREENS = '''package demo
// class PhoneScreen is described below; this comment is not a declaration
class LoginActivity {
    val note = "{ a brace in a string }"; val closing = '}'
    /* class PhoneScreen { not code } */
    inner class PhoneScreen : View {
        fun bind() {
            photo.setImageResource(R.drawable.ic_photo)
            card.setBackground(ContextCompat.getDrawable(context, R.drawable.bg_card))
        }
        class Row { fun icon() = R.drawable.ic_row_a }
    }
    inner class PasswordScreen : View {
        fun bind() {
            lock.setImageResource(R.drawable.ic_loading)
            spinner.setAnimation(R.raw.spinner)
        }
    }
    fun createView(context: Context): View {
        back.setImageResource(R.drawable.ic_loading)
        back.setOnClickListener { card.setBackground(ContextCompat.getDrawable(context, R.drawable.bg_card)) }
        return root
    }
    fun setPage(page: Int) { bind(); title.setText(R.string.app_name) }
}
'''

HOST = '''class Host extends Base {
    // void onBackPressed() { in a comment }
    private final String note = "void onBackPressed() { in a string }";
    private final int size = measure();
    @Override
    public void onBackPressed() throws IllegalStateException, RuntimeException {
        if (page == 0) { measure(); }
    }
    int measure() { return 1; }
    int measure(int scale) { return scale; }
    class Inner { void hidden() { } }
}
'''


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.p = p = test_resource_signals.CollectorSignalsTests(); p.setUp(); self.addCleanup(p.doCleanups)
        p.project()
        p.write('java/demo/LoginActivity.kt', SCREENS)

    def collect(self, *entries):
        return collect_ui_sources.collect(SimpleNamespace(android_root=str(self.p.root), scope='probe', entry=list(entries), source_file=[], layout=[]))

    def source(self, index):
        fact, = index['sourceFiles']
        return fact

    def test_an_entry_that_names_a_class_collects_that_class_alone(self):
        fact = self.source(self.collect('app/src/main/java/demo/LoginActivity.kt#PhoneScreen'))
        self.assertEqual(fact['scope'], {'symbols': ['PhoneScreen'], 'ranges': [{'lines': [6, 12]}]})
        self.assertEqual(sorted(fact['resourceRefs']), ['@drawable/bg_card', '@drawable/ic_photo', '@drawable/ic_row_a'])  # its nested class too
        self.assertTrue(fact['presentationMutations'])
        self.assertTrue(all(6 <= row['line'] <= 12 for row in fact['presentationMutations']))  # the file's own line numbers
        self.assertTrue(all(6 <= row['line'] <= 12 for row in fact['resourceUsages']))

    def test_the_whole_file_is_collected_when_no_class_is_named(self):
        fact = self.source(self.collect('app/src/main/java/demo/LoginActivity.kt'))
        self.assertNotIn('scope', fact)
        self.assertLessEqual({'@drawable/ic_photo', '@drawable/ic_loading', '@raw/spinner'}, set(fact['resourceRefs']))
        both = self.source(self.collect('app/src/main/java/demo/LoginActivity.kt#PhoneScreen', 'app/src/main/java/demo/LoginActivity.kt'))
        self.assertNotIn('scope', both)  # one entry asked for all of it

    def test_two_named_classes_are_collected_together(self):
        fact = self.source(self.collect('app/src/main/java/demo/LoginActivity.kt#PhoneScreen', 'app/src/main/java/demo/LoginActivity.kt#PasswordScreen'))
        self.assertEqual((fact['scope']['symbols'], [row['lines'] for row in fact['scope']['ranges']]), (['PasswordScreen', 'PhoneScreen'], [[6, 12], [13, 18]]))
        self.assertIn('@raw/spinner', fact['resourceRefs'])

    def test_a_class_the_file_does_not_declare_is_reported_and_nothing_is_collected_for_it(self):
        index = self.collect('app/src/main/java/demo/LoginActivity.kt#EmailScreen')
        self.assertEqual(index['sourceFiles'], [])
        self.assertIn('symbol is not declared in the source file', [row['reason'] for row in index['unresolved']])

    def test_a_class_is_found_by_its_qualified_name(self):
        index = self.collect('demo.HomeActivity')
        self.assertEqual([fact['path'] for fact in index['sourceFiles']], ['app/src/main/java/demo/HomeActivity.kt'])
        self.assertEqual(index['unresolved'], [])

    def test_an_entry_that_names_a_function_collects_that_function_alone(self):
        fact = self.source(self.collect('app/src/main/java/demo/LoginActivity.kt#LoginActivity.createView'))
        self.assertEqual(fact['scope'], {'symbols': ['LoginActivity.createView'], 'ranges': [{'lines': [19, 23]}]})
        self.assertEqual(sorted(fact['resourceRefs']), ['@drawable/bg_card', '@drawable/ic_loading'])  # the block it opens too
        self.assertTrue(fact['presentationMutations'])
        self.assertTrue(all(19 <= row['line'] <= 23 for row in fact['presentationMutations'] + fact['resourceUsages']))

    def test_a_function_and_a_class_of_one_file_are_collected_together(self):
        fact = self.source(self.collect('app/src/main/java/demo/LoginActivity.kt#PhoneScreen',
                                        'app/src/main/java/demo/LoginActivity.kt#LoginActivity.createView',
                                        'app/src/main/java/demo/LoginActivity.kt#LoginActivity.setPage'))
        self.assertEqual((fact['scope']['symbols'], [row['lines'] for row in fact['scope']['ranges']]),
                         (['LoginActivity.createView', 'LoginActivity.setPage', 'PhoneScreen'], [[6, 12], [19, 23], [24, 24]]))
        self.assertNotIn('@raw/spinner', fact['resourceRefs'])  # the other screen of the file

    def test_a_function_declared_in_a_nested_class_is_not_a_function_of_the_outer_class(self):
        index = self.collect('app/src/main/java/demo/LoginActivity.kt#LoginActivity.bind')
        self.assertEqual(index['sourceFiles'], [])
        self.assertIn('symbol is not declared in the source file', [row['reason'] for row in index['unresolved']])

    def test_a_function_is_found_by_its_declaration_not_by_a_call_or_a_mention(self):
        lines = lambda symbol: [[collect_ui_sources.line_number(HOST, start), collect_ui_sources.line_number(HOST, end - 1)]
                                for start, end in collect_ui_sources.declaration_spans(HOST, symbol)]
        self.assertEqual(lines('Host.onBackPressed'), [[6, 8]])  # not the comment, the string, or its annotation line
        self.assertEqual(lines('Host.measure'), [[9, 9], [10, 10]])  # both overloads; neither the initializer nor the call
        self.assertEqual((lines('Host.hidden'), lines('Host.missing'), lines('Inner.hidden')), ([], [], [[11, 11]]))

    def test_braces_in_strings_chars_and_comments_do_not_end_a_class(self):
        spans = collect_ui_sources.declaration_spans(SCREENS, 'PhoneScreen')
        self.assertEqual(len(spans), 1)
        body = SCREENS[spans[0][0]:spans[0][1]]
        self.assertTrue(body.lstrip().startswith('inner class PhoneScreen') and body.rstrip().endswith('}'))
        self.assertIn('class Row', body); self.assertNotIn('PasswordScreen', body)
        text, kept = collect_ui_sources.scoped_text(SCREENS, {'PhoneScreen'})
        self.assertEqual((len(text), text.count('\n')), (len(SCREENS), SCREENS.count('\n')))  # offsets and lines are the file's


class IndexAsEvidenceTests(unittest.TestCase):
    """What a tool records about the files it scanned is a fact of its output, not a reference of the run: an index can
    be cited as evidence although its file records carry paths relative to the tree that was scanned."""
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'run'; (self.root / 'artifacts').mkdir(parents=True)
        self.base = Path(self.tmp.name).resolve()

    def ref(self, name, value):
        import json
        from contracts import file_ref
        path = self.base / name
        path.write_text(value if isinstance(value, str) else json.dumps(value))
        return file_ref(path)

    def index(self, **extra):
        return self.ref('ui-source-index.json', {'sourceFiles': [{'path': 'app/src/main/java/demo/LoginActivity.kt', 'sha256': 'a' * 64,
                                                                   'language': 'kt', 'resourceRefs': ['@drawable/ic_photo']}], **extra})

    def test_an_index_with_relative_file_records_is_archived_as_one_document(self):
        import ledger
        ref = self.index()
        saved = ledger.preserve_refs(self.root, {'report_ref': ref})
        self.assertEqual([row['source_path'] for row in saved], [ref['path']])  # the index itself, and nothing it lists
        self.assertTrue((self.root / 'artifacts' / ref['sha256']).is_file())

    def test_a_reference_inside_a_cited_document_is_still_followed_and_checked(self):
        import ledger
        from contracts import Rejected
        proof = self.ref('proof.md', 'read the source')
        saved = ledger.preserve_refs(self.root, {'report_ref': self.index(evidence_refs=[proof])})
        self.assertIn(proof['path'], [row['source_path'] for row in saved])
        missing = {'path': str(self.base / 'gone.md'), 'sha256': 'b' * 64}
        with self.assertRaises(ValueError):
            ledger.preserve_refs(self.root, {'report_ref': self.ref('second-index.json', {'evidence_refs': [missing]})})

    def test_a_reference_a_request_makes_itself_must_be_absolute(self):
        import ledger
        from contracts import Rejected, cited
        with self.assertRaisesRegex(Rejected, 'absolute evidence path required'):
            ledger.preserve_refs(self.root, {'report_ref': {'path': 'staging/report.json', 'sha256': 'c' * 64}})
        record = {'path': 'a/relative/file.kt', 'sha256': 'd' * 64}
        self.assertEqual((cited(record), cited(record, nested=True), cited({'path': '/abs/file', 'sha256': 'e'}, nested=True), cited({'path': 'x'})),
                         (True, False, True, False))

    def test_a_ready_report_may_stand_on_an_index(self):
        import context_readiness as cr
        cr.verify_inputs({'target_root': str(self.base / 'target')}, 'M001', 'planning', deep=True, refs=[self.index()])


if __name__ == '__main__':
    unittest.main()
