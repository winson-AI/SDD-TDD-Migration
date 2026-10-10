"""Every place the scoped code names a file resource is recorded and accounted for, whatever call receives it."""
import copy
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, file_ref
import resource_facts
import resource_fidelity as rf
import resource_signals as signals
import ui_evidence
import test_resource_signal_closure as closure

JAVA = '''package demo;

import android.graphics.drawable.BitmapDrawable;   // a type that is only named draws nothing

public class AccountActivity extends Activity {
    private GradientDrawable pending;
    private final Provider<Bitmap> mask = v -> {
        canvas.drawCircle(1f, 1f, 1f, paint);
        return bitmap;
    };

    @Override
    public View createView(Context context) {
        toolbar.setLeadingImage(R.drawable.ic_back);
        String label = "R.drawable.in_a_string {";
        /* R.drawable.in_a_comment } */
        avatar = new View(context) {
            @Override
            protected void onDraw(Canvas canvas) {
                canvas.drawCircle(0f, 0f, 4f, paint);
            }
        };
        if (drawable instanceof BitmapDrawable) {
            photo.setImage(location, null);
        }
        return view;
    }

    private class EntryView extends PagerView implements Listener {
        EntryView(Context context) {
            cells[0].set(R.drawable.ic_phone, getString(R.string.phone_title));
            animated = flag ? R.raw.wave : R.raw.still;
        }

        void show(Theme theme) throws IOException {
            background = new GradientDrawable(Orientation.LEFT_RIGHT, null);
        }
    }
}
'''
KOTLIN = '''package demo

class Feed(private val loader: Loader) {
    fun bind(item: Item) = rows.forEach { row ->
        row.icon.setIcon(R.drawable.ic_row)
    }

    override fun onDraw(canvas: Canvas) {
        canvas.drawPath(path, paint)
    }

    companion object {
        fun badge(): Drawable = ShapeDrawable(OvalShape())
    }
}
'''


def line(text, needle):
    return text[:text.index(needle)].count('\n') + 1


class UsageRecordTests(unittest.TestCase):
    def test_each_use_carries_its_line_class_function_and_receiving_call(self):
        rows = {row['ref']: row for row in signals.usages(JAVA)}
        self.assertEqual(sorted(rows), ['@drawable/ic_back', '@drawable/ic_phone', '@raw/still', '@raw/wave', '@string/phone_title'])
        back = rows['@drawable/ic_back']
        self.assertEqual((back['line'], back['symbol'], back['call']), (line(JAVA, 'setLeadingImage'), 'AccountActivity.createView', 'setLeadingImage'))
        phone = rows['@drawable/ic_phone']
        self.assertEqual((phone['line'], phone['symbol'], phone['call']), (line(JAVA, 'cells[0]'), 'AccountActivity.EntryView.EntryView', 'set'))
        self.assertEqual(rows['@string/phone_title']['call'], 'getString')
        wave = rows['@raw/wave']
        self.assertEqual(wave['symbol'], 'AccountActivity.EntryView.EntryView')
        self.assertNotIn('call', wave)  # an assignment is not an argument

    def test_a_reference_in_a_comment_or_a_string_is_not_a_use(self):
        refs = {row['ref'] for row in signals.usages(JAVA)}
        self.assertFalse({'@drawable/in_a_string', '@drawable/in_a_comment'} & refs)
        symbols = signals.Symbols(JAVA)
        self.assertEqual(symbols.at(JAVA.index('return view')), 'AccountActivity.createView')  # braces inside literals do not count

    def test_kotlin_functions_and_lambdas_are_named_by_their_declaration(self):
        row = signals.usages(KOTLIN, kotlin=True)[0]
        self.assertEqual((row['ref'], row['symbol'], row['call']), ('@drawable/ic_row', 'Feed.bind', 'setIcon'))

    def test_drawing_is_a_draw_call_or_a_drawable_built_in_code_never_a_type_that_is_only_named(self):
        rows = {row['owner']: row for row in signals.drawn_rows(JAVA, 'demo/AccountActivity.java')}
        self.assertEqual(set(rows), {'AccountActivity', 'AccountActivity.createView.onDraw', 'AccountActivity.EntryView.show'})
        self.assertEqual(rows['AccountActivity']['constructs'], ['drawCircle'])  # the field initialiser's lambda
        self.assertEqual(rows['AccountActivity.createView.onDraw']['constructs'], ['drawCircle', 'onDraw'])
        self.assertEqual(rows['AccountActivity.createView.onDraw']['line'], line(JAVA, 'protected void onDraw'))  # named where it is declared
        self.assertEqual(rows['AccountActivity.EntryView.show']['constructs'], ['GradientDrawable'])
        kotlin = {row['owner']: row['constructs'] for row in signals.drawn_rows(KOTLIN, 'demo/Feed.kt')}
        self.assertEqual(kotlin, {'Feed.onDraw': ['drawPath', 'onDraw'], 'Feed': ['ShapeDrawable']})  # an expression body has no block of its own

    def test_a_call_named_like_an_image_loader_that_nothing_explains_is_listed(self):
        symbols = signals.Symbols(JAVA)
        found = signals.sink_candidates(JAVA, 'demo/AccountActivity.java', (), symbols)
        self.assertEqual([(row['call'], row['line']) for row in found], [('setLeadingImage', line(JAVA, 'setLeadingImage')), ('setImage', line(JAVA, 'photo.setImage'))])
        declared = signals.sink_candidates(JAVA, 'demo/AccountActivity.java', ('setImage',), symbols)
        self.assertEqual([row['call'] for row in declared], ['setLeadingImage'])

    def test_a_qualifier_splits_into_what_the_file_is_for_and_which_rendition_it_is(self):
        self.assertEqual(resource_facts.variant('xxhdpi'), ('base', 'xxhdpi'))
        self.assertEqual(resource_facts.variant('default'), ('base', None))
        self.assertEqual(resource_facts.variant('night-xhdpi'), ('night', 'xhdpi'))
        self.assertEqual(resource_facts.variant('anydpi-v24'), ('base', 'anydpi'))  # a vector for newer platforms beside its fallbacks
        self.assertEqual(resource_facts.variant('night-v21'), ('night', None))
        self.assertEqual(resource_facts.variant('zh-rCN'), ('zh-rCN', None))


class UsageClosureTests(unittest.TestCase):
    def setUp(self):
        self.c = closure.SignalClosureTests('test_drawables_nested_in_a_declared_drawable_must_be_covered')
        self.c.setUp(); self.addCleanup(self.c.doCleanups)
        self.s, self.n, self.f = self.c.s, self.c.n, self.c.f

    def wrapper(self):
        self.c.write('res/drawable/ic_nav.xml', closure.VECTOR % '')
        return self.c.code('\nfun build() {\n  toolbar.setNavIcon(R.drawable.ic_nav)\n  title.show(getString(R.string.settings_title))\n}\n')

    def scope(self, **rows):
        self.f.evidence['resource_scope'] = rows

    def review(self):
        return [file_ref(self.n.write('evidence/usage-review.json', {'reviewed': True}))]

    def test_the_collector_records_usage_sites_and_unexplained_loader_calls(self):
        index = self.wrapper()
        source = next(s for s in index['sourceFiles'] if s['path'].endswith('SettingsFragment.kt'))
        site = next(u for u in source['resourceUsages'] if u['ref'] == '@drawable/ic_nav')
        self.assertEqual((site['symbol'], site['call']), ('build', 'setNavIcon'))
        self.assertEqual(index['imageSinkCandidates'], [])
        index = self.c.code('\nfun avatar(u: User) { photo.loadAvatar(u.photo) }\n')
        self.assertEqual([c['call'] for c in index['imageSinkCandidates']], ['loadAvatar'])

    def test_a_picture_passed_to_a_project_method_must_be_declared_by_a_node(self):
        self.wrapper()
        self.assertEqual(list(self.c.needs()['undeclared']), ['@drawable/ic_nav'])  # the string is a value, not a file
        with self.assertRaisesRegex(Rejected, r'UI tree omits file resources the scoped code uses: @drawable/ic_nav '
                                              r'\(SettingsFragment.kt:\d+ build via setNavIcon\)'):
            self.s.freeze()
        import contracts
        with contracts.carrying() as owed:  # where a leaf's request is judged, the same gap is collected and the rest is judged too
            self.s.freeze()
        self.assertRegex(owed[0], 'UI tree omits file resources the scoped code uses: @drawable/ic_nav ')
        self.c.declare('@drawable/ic_nav'); self.s.recollect()
        self.assertEqual(self.c.needs()['undeclared'], {})
        with self.assertRaisesRegex(Rejected, 'uncovered presentation refs: @drawable/ic_nav'):
            self.s.freeze()
        self.c.cover_files()
        self.s.freeze()

    def test_code_outside_the_ui_scope_is_excluded_by_symbol_or_reference_with_evidence(self):
        self.wrapper()
        self.scope(usage_exclusions=[{'symbol': 'build', 'reason': 'toolbar belongs to another module', 'evidence_refs': self.review()}])
        self.s.freeze()
        self.scope(usage_exclusions=[{'ref': '@drawable/ic_nav', 'reason': 'toolbar belongs to another module', 'evidence_refs': self.review()}])
        self.s.freeze()
        for row, message in (({'symbol': 'build', 'evidence_refs': self.review()}, 'needs a symbol or a ref, and a reason'),
                             ({'reason': 'no target', 'evidence_refs': self.review()}, 'needs a symbol or a ref, and a reason'),
                             ({'symbol': 'elsewhere', 'reason': 'x', 'evidence_refs': self.review()}, 'must name a class, function or reference the scoped code uses'),
                             ({'symbol': 'build', 'ref': '@drawable/other', 'reason': 'x', 'evidence_refs': self.review()}, 'must name a class, function'),
                             ({'symbol': 'build', 'reason': 'x', 'evidence_refs': []}, 'requires review evidence')):
            self.scope(usage_exclusions=[row])
            with self.subTest(row=row), self.assertRaisesRegex(Rejected, message):
                self.s.freeze()

    def setter(self):
        """A picture a setter the collector knows shows in one function: the use is also a presentation mutation."""
        self.c.write('res/drawable/ic_nav.xml', closure.VECTOR % '')
        index = self.c.code('\nfun otherChannel() {\n  icon.setImageResource(R.drawable.ic_nav)\n}\n')
        source = next(s for s in index['sourceFiles'] if s['path'].endswith('SettingsFragment.kt'))
        row = next(m for m in source['presentationMutations'] if '@drawable/ic_nav' in m['resourceRefs'])
        # The tree records that the source sets it, as a rule that names no resource of this target.
        self.f.fixture['tree']['screens'][0]['root']['dynamicRules'].append({'when': 'another channel', 'property': row['property'],
            'result': 'outside this module', 'sourcePath': row['sourcePath'], 'line': row['line']})
        self.s.source_index(index)
        return index

    def validate(self):
        evidence = self.f.evidence
        return ui_evidence.validate_tree_ref(evidence['ui_tree_ref'], source_index_ref=evidence['source_index_ref'],
            runtime_index_ref=evidence.get('runtime_index_ref'), resource_scope=evidence.get('resource_scope'))

    def test_a_picture_a_setter_shows_in_excluded_code_need_not_be_declared_by_the_tree(self):
        self.setter()
        with self.assertRaisesRegex(Rejected, 'omits source runtime presentation references: @drawable/ic_nav'):
            self.validate()
        import contracts
        with contracts.carrying() as owed:
            self.validate()
        self.assertEqual(owed[0], 'native UI validation: ui-tree presentation.resourceRefs omits source runtime presentation references: @drawable/ic_nav')
        self.assertRegex(owed[1], '^UI tree omits file resources the scoped code uses: @drawable/ic_nav ')  # judged on, so both are seen at once
        self.assertEqual(len(owed), 2)
        for row in ({'symbol': 'otherChannel'}, {'ref': '@drawable/ic_nav'}):
            self.scope(usage_exclusions=[{**row, 'reason': 'a channel outside this module', 'evidence_refs': self.review()}])
            with self.subTest(row=row):
                self.validate(); self.s.freeze()  # scoped out with evidence: no node declares it and no item covers it
                self.assertNotIn('@drawable/ic_nav', self.c.needs()['refs'])

    def test_a_setter_outside_the_excluded_symbol_keeps_the_reference_on_the_tree(self):
        self.setter()
        index = self.c.code('\nfun header() { logo.setImageResource(R.drawable.ic_nav) }\n')
        self.scope(usage_exclusions=[{'symbol': 'otherChannel', 'reason': 'a channel outside this module', 'evidence_refs': self.review()}])
        self.assertEqual(rf.scoped_out_refs(index, self.f.evidence['resource_scope']), set())
        with self.assertRaisesRegex(Rejected, 'omits source runtime presentation references: @drawable/ic_nav'):
            self.validate()

    def test_a_use_outside_the_excluded_symbol_keeps_the_obligation(self):
        self.wrapper()
        self.c.code('\nfun header() { bar.setNavIcon(R.drawable.ic_nav) }\n')
        self.scope(usage_exclusions=[{'symbol': 'build', 'reason': 'toolbar belongs to another module', 'evidence_refs': self.review()}])
        with self.assertRaisesRegex(Rejected, r'ic_nav \(SettingsFragment.kt:\d+ header via setNavIcon\)'):
            self.s.freeze()


class DensityTests(unittest.TestCase):
    def setUp(self):
        self.c = closure.SignalClosureTests('test_drawables_nested_in_a_declared_drawable_must_be_covered')
        self.c.setUp(); self.addCleanup(self.c.doCleanups)
        self.s, self.n, self.f = self.c.s, self.c.n, self.c.f
        for density in ('mdpi', 'xhdpi', 'xxhdpi'):
            self.c.write(f'res/drawable-{density}/ic_logo.png', b'\x89PNG\r\n\x1a\n' + density.encode())
        self.c.declare('@drawable/ic_logo')
        self.c.code('\nfun logo() = R.drawable.ic_logo\n')

    def skeleton(self):
        found = rf.skeletons(self.c.index(), self.c.tree(), self.f.evidence.get('resource_scope'))['resources']
        return next(s for s in found if s['source_resource'] == '@drawable/ic_logo')

    def items(self):
        return self.f.analysis['dimensions'][3]['items']

    def test_the_densities_of_a_drawable_are_one_resource_and_one_item_names_the_rendition_it_migrates(self):
        skeleton = self.skeleton()
        self.assertEqual((skeleton['qualifier'], skeleton['renditions']), ('xxhdpi', ['mdpi', 'xhdpi', 'xxhdpi']))
        self.items().append(self.c.item_for(skeleton))
        self.s.freeze()  # no item or exclusion for the other two densities

    def test_any_rendition_the_source_holds_may_be_the_one_migrated(self):
        chosen = self.n.android / 'app/src/main/res/drawable-xhdpi/ic_logo.png'
        self.items().append(self.c.item_for({**self.skeleton(), 'qualifier': 'xhdpi', 'source_resource_ref': file_ref(chosen)}))
        self.s.freeze()
        self.items()[-1]['qualifier'] = 'hdpi'
        with self.assertRaisesRegex(Rejected, 'differs from actual source'):
            self.s.freeze()

    def test_two_items_for_one_picture_are_one_too_many(self):
        skeleton = self.skeleton()
        other = self.n.android / 'app/src/main/res/drawable-mdpi/ic_logo.png'
        self.items().append(self.c.item_for(skeleton))
        self.items().append(self.c.item_for({**skeleton, 'qualifier': 'mdpi', 'source_resource_ref': file_ref(other)}, item_id='logo-mdpi'))
        with self.assertRaisesRegex(Rejected, 'closure requires one item for @drawable/ic_logo / base'):
            self.s.freeze()

    def test_a_night_picture_is_different_content_and_keeps_its_own_item(self):
        self.c.write('res/drawable-night-xxhdpi/ic_logo.png', b'\x89PNG\r\n\x1a\nnight')
        self.s.recollect()
        self.items().append(self.c.item_for(self.skeleton()))
        with self.assertRaisesRegex(Rejected, 'closure requires one item for @drawable/ic_logo / night'):
            self.s.freeze()
        groups = rf.resource_groups(rf.indexed_resources(self.c.index(), self.c.needs()['refs']))
        self.assertEqual(sorted(q for q in groups[('@drawable/ic_logo', 'night')]), ['night-xxhdpi'])

    def test_a_project_order_or_the_loadable_format_decides_the_rendition(self):
        groups = rf.resource_groups(rf.indexed_resources(self.c.index(), self.c.needs()['refs']))
        renditions = groups[('@drawable/ic_logo', 'base')]
        self.assertEqual(rf.rendition(renditions), 'xxhdpi')
        self.assertEqual(rf.rendition(renditions, order=['xhdpi', 'xxhdpi']), 'xhdpi')
        self.assertEqual(rf.rendition(renditions, formats=['png']), 'xxhdpi')
        self.assertIsNone(rf.rendition(renditions, formats=['webp']))


if __name__ == '__main__':
    unittest.main()
