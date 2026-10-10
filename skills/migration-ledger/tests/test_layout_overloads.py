"""A project's layout-parameter builder is declared as a table of names per arity. Overloads of one arity that differ by
type are told apart by the literal, and an overload the table does not declare is recorded, not left out."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import parameter_records as records

HELPERS = [{'call': 'Frames.linear', 'params': ['layout_width', 'layout_height', 'layout_gravity'], 'unit': 'dp'},
           {'call': 'Frames.linear', 'unit': 'dp', 'params': ['layout_width', 'layout_height', 'layout_weight', 'layout_gravity',
                                                              'marginLeft', 'marginTop', 'marginRight', 'marginBottom']}]
SOURCE = '''class Screen { void build() {
  root.addView(grows, Frames.linear(MATCH, 48, 1f));
  root.addView(pinned, Frames.linear(MATCH, 48, Gravity.TOP | Gravity.LEFT));
  root.addView(computed, Frames.linear(MATCH, 48, flags));
  root.addView(inset, Frames.linear(MATCH, 48, Gravity.TOP, 16, 0, 16, 0));
  root.addView(full, Frames.linear(0, 48, 1.0f, Gravity.CENTER, 8, 0, 8, 0));
  root.addView(plain, new LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT));
} }'''


class OverloadTests(unittest.TestCase):
    def setUp(self):
        self.rows = {}
        for row in records.code_parameters(SOURCE, 'Screen.java', helpers=HELPERS):
            self.rows.setdefault(row['receiver'], {})[row['name']] = row

    def test_a_float_is_a_weight_and_a_gravity_expression_a_gravity_whatever_the_table_names_there(self):
        self.assertEqual(set(self.rows['grows']), {'layout_width', 'layout_height', 'layout_weight'})  # declared as a gravity
        self.assertEqual((self.rows['grows']['layout_weight']['type'], self.rows['grows']['layout_weight']['value']), ('number', 1))
        self.assertEqual(self.rows['pinned']['layout_gravity']['value'], 'Gravity.TOP | Gravity.LEFT')
        self.assertEqual(self.rows['computed']['layout_gravity']['type'], 'expression')  # nothing in the argument says: the table stands
        self.assertEqual((self.rows['full']['layout_weight']['value'], self.rows['full']['layout_gravity']['value'], self.rows['full']['marginLeft']['value']),
                         (1, 'Gravity.CENTER', 8))
        for argument, name in (('0.5f', 'layout_weight'), ('1F', 'layout_weight'), ('.5f', 'layout_weight'), ('Gravity.END', 'layout_gravity'),
                               ('1', 'layout_gravity'), ('weight', 'layout_gravity')):
            self.assertEqual(records.overloaded('layout_gravity', argument), name, argument)
        self.assertEqual(records.overloaded('marginLeft', '1f'), 'marginLeft')  # only where the two can be confused

    def test_an_overload_the_table_does_not_declare_is_recorded_for_its_reader(self):
        row, = self.rows['inset'].values()
        self.assertEqual((row['name'], row['type'], row['text'], row['line']),
                         ('layout_params', 'expression', 'Frames.linear(MATCH, 48, Gravity.TOP, 16, 0, 16, 0)', 5))
        self.assertEqual(set(self.rows['plain']), {'layout_width', 'layout_height'})  # the platform's own are read as before
        self.assertEqual([receiver for receiver, rows in self.rows.items() if 'layout_params' in rows], ['inset'])
        undeclared = records.code_parameters('class A { void f() { root.addView(v, Other.build(1, 2)); } }', 'A.java', helpers=HELPERS)
        self.assertEqual(undeclared, [])  # a call no table names is still not a parameter source


if __name__ == '__main__':
    unittest.main()
