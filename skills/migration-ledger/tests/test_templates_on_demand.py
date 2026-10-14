"""A card names the templates of its step and carries none; a role fetches one by name when it writes that artifact."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reading


class TemplatesOnDemandTests(unittest.TestCase):
    def test_a_template_is_fetched_by_name_from_the_package_only(self):
        self.assertEqual(reading.show_template('stage-plan.json'), (reading.PACKAGE / 'template/stage-plan.json').read_text())
        for bad in ('../AGENTS.md', 'missing.json', '../template/stage-plan.json/..'):
            with self.subTest(bad=bad), self.assertRaises(KeyError):
                reading.show_template(bad)

    def test_a_card_lists_the_names_and_says_how_to_fetch_one(self):
        rows = reading.card({}, None, {'role': 'module-orchestrator', 'operation': 'assign'})
        template = (reading.PACKAGE / 'template/execution-assignment.json').read_text()
        with tempfile.TemporaryDirectory() as out:
            body = Path(reading.render(rows, out, ['execution-assignment.json'])['path']).read_text()
        self.assertIn('<!-- 本步模板 -->\n- execution-assignment.json\n', body)
        self.assertNotIn(template.strip(), body)
        self.assertIn('show --template <名>', body)


if __name__ == '__main__':
    unittest.main()
