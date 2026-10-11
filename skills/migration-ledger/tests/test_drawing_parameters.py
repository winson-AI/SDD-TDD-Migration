"""Drawing code gives a Paint its colour and stroke and hands lengths and colours to a canvas, a rect or a path: those are
parameters of the screen like a setter's arguments, recorded once by the collector instead of being read by each slice."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import parameter_records as records

SOURCE = '''class Badge extends View { void draw(Canvas canvas) {
  paint.setColor(Theme.getColor(Theme.key_badge));
  paint.setStrokeWidth(AndroidUtilities.dpf2(1.5f));
  paint.setShadowLayer(AndroidUtilities.dp(4), 0, AndroidUtilities.dp(2), 0x40000000);
  rect.set(AndroidUtilities.dp(8), AndroidUtilities.dp(4), getWidth() - AndroidUtilities.dp(8), AndroidUtilities.dp(28));
  canvas.drawRoundRect(rect, AndroidUtilities.dp(6), AndroidUtilities.dp(6), paint);
  canvas.drawCircle(cx, cy, AndroidUtilities.dpr(10), paint);
  canvas.drawText(text, x, y, paint);
  items.set(0, item);
  // canvas.drawRect(0, 0, AndroidUtilities.dp(1), AndroidUtilities.dp(1), paint);
} }'''


class DrawingParameterTests(unittest.TestCase):
    def setUp(self):
        self.rows = {}
        for row in records.code_parameters(SOURCE, 'Badge.java'):
            self.rows.setdefault(row['receiver'], {}).setdefault(row['name'], []).append(row)

    def one(self, receiver, name):
        row, = self.rows[receiver][name]
        return {k: row[k] for k in ('type', 'value', 'unit', 'token') if k in row}

    def test_a_paint_gives_its_colour_stroke_and_shadow(self):
        self.assertEqual(self.one('paint', 'paintColor'), {'type': 'token', 'token': 'Theme.key_badge'})  # a theme key the Spec maps once
        self.assertEqual(self.one('paint', 'strokeWidth'), {'type': 'dimension', 'value': 1.5, 'unit': 'dp'})
        self.assertEqual(self.one('paint', 'shadowRadius'), {'type': 'dimension', 'value': 4, 'unit': 'dp'})
        self.assertEqual(self.one('paint', 'shadowDy'), {'type': 'dimension', 'value': 2, 'unit': 'dp'})
        self.assertEqual(self.one('paint', 'shadowColor'), {'type': 'color', 'value': '#40000000'})

    def test_lengths_and_colours_handed_to_a_canvas_or_a_rect_are_recorded_by_argument(self):
        self.assertEqual({name for name in self.rows['rect']}, {'set.arg1', 'set.arg2', 'set.arg4'})  # arg3 is computed: the drawing's own structure
        self.assertEqual((self.one('rect', 'set.arg1'), self.one('rect', 'set.arg4')), ({'type': 'dimension', 'value': 8, 'unit': 'dp'}, {'type': 'dimension', 'value': 28, 'unit': 'dp'}))
        self.assertEqual({name for name in self.rows['canvas']}, {'drawRoundRect.arg2', 'drawRoundRect.arg3', 'drawCircle.arg3'})  # drawText hands no length
        self.assertEqual(self.one('canvas', 'drawCircle.arg3'), {'type': 'dimension', 'value': 10, 'unit': 'dp'})
        self.assertNotIn('items', self.rows)  # a list's set is not a drawing
        self.assertTrue(all(row['line'] in range(2, 8) for rows in self.rows.values() for group in rows.values() for row in group))  # nothing from the comment


if __name__ == '__main__':
    unittest.main()
