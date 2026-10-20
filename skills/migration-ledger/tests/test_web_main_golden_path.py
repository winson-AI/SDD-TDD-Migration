"""A web PATH end to end through the Ledger: planned with frozen steps and DOM predicates, frozen, dispatched to a
Test-Runner, run by the built-in web Main through execute_test (the real engine on a page fixture), its report bound and
accepted, the module at DoD; and a predicate the page does not satisfy is the case's Red, routed to diagnosis like any other."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
from contracts import check_ref, digest, read_json
from execute_test import execute
from harmony_stage import build as stage_result
import test_unit_reports

MAIN = Path(__file__).resolve().parents[2] / 'migration-test/scripts/web_main.py'
STEPS = [{'action': 'goto', 'url': 'http://127.0.0.1:1/index.html'}, {'action': 'fill', 'selector': '#user', 'text': 'ann'}, {'action': 'click', 'selector': 'a.login'}]
ASSERTIONS = [{'assertion_id': 'A1', 'expected': True, 'description': 'the list heading reads Items', 'matcher': 'exact', 'verification': 'dom', 'after_step': 3,
               'predicate': {'kind': 'text', 'selector': '#heading', 'equals': 'Items'}},
              {'assertion_id': 'A2', 'expected': True, 'description': 'the typed name stays', 'matcher': 'exact', 'verification': 'dom', 'after_step': 2,
               'predicate': {'kind': 'value', 'selector': '#user', 'equals': 'ann'}}]
WRAPPER = '''import json, sys
from pathlib import Path
sys.path.insert(0, %(main_dir)r)
import web_main
# The fixture's run is not laid out under .sdd-runs; the managed-path rules have their own tests, the engine and the Ledger are real here.
web_main.harmony_output = lambda root, output, area=None: Path(output).resolve()
def plain_write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\\n')
web_main.write = plain_write
TEXTS = json.loads(Path(%(texts)r).read_text())
PNG = bytes.fromhex(%(png)r)
class FakePage:
    def __init__(self, config, out): self.calls = []
    def goto(self, url): self.calls.append(url)
    def click(self, selector): pass
    def fill(self, selector, text): TEXTS[selector] = text
    def press(self, key): pass
    def wait(self, ms): pass
    def screenshot(self, path): Path(path).write_bytes(PNG)
    def text(self, selector): return TEXTS.get(selector)
    def value(self, selector): return TEXTS.get(selector)
    def visible(self, selector): return selector in TEXTS
    def count(self, selector): return int(selector in TEXTS)
    def url(self): return 'http://127.0.0.1:1/list.html'
    def title(self): return 'List'
    def close(self): return None
sys.exit(web_main.main(open_page=FakePage))
'''


class WebMainGoldenPathTests(unittest.TestCase):
    def setUp(self):
        self.inner = test_unit_reports.UnitReportTests(); self.inner.setUp(); self.addCleanup(self.inner.doCleanups)
        f = self.f = self.inner.f
        self.texts = f.base / 'page-texts.json'; self.texts.write_text(json.dumps({'#heading': 'Items'}))
        wrapper = f.base / 'web-main-with-fake-page.py'
        import io
        from PIL import Image
        png = io.BytesIO(); Image.new('RGB', (16, 16), (200, 200, 200)).save(png, format='PNG')
        wrapper.write_text(WRAPPER % {'main_dir': str(MAIN.parent), 'texts': str(self.texts), 'png': png.getvalue().hex()})
        self.argv = [sys.executable, '-B', str(wrapper)]
        old_plan, old_report = f.plan, f.report
        def plan():
            p = old_plan()
            web = next(row for row in p['paths'] if row['path_id'] == 'P1')  # the case's automation path, on the served target page
            web.pop('command', None); web.pop('unit_report', None)
            web.update(platform='web', task_type='test', steps=[dict(s) for s in STEPS], expected_assertions=[dict(a) for a in ASSERTIONS])
            return p
        def report(stage, *args, **kwargs):
            r = old_report(stage, *args, **kwargs)
            if stage == 'testing':
                r['execution'] = {'argv': self.argv, 'cwd': str(f.target), 'environment_ref': f.ref('web-env.md', 'web Main with a page fixture')}
            return r
        f.plan, f.report = plan, report

    def run_web(self):
        f = self.f
        self.inner.run_unit()  # build, unit and static accepted under BUILD1
        self.inner.fixture.split.f.assign('test-runner', 'AUTO1')
        receipt = execute(f.root, 'M001', 'AUTO1', 'P1', self.argv, f.target, f.root / 'runs/harmony/automation/web-attempt')
        result = stage_result(f.root, 'M001', 'AUTO1', [receipt])
        a = f.state()['modules']['M001']['assignments']['AUTO1']
        f.submit(result, a); f.call('accept', {'assignment_id': 'AUTO1'})
        return result['paths'][0], read_json(check_ref(receipt))

    def test_the_web_path_runs_in_the_main_and_the_module_reaches_dod(self):
        row, receipt = self.run_web()
        self.assertEqual((row['quality'], receipt['exit_code']), ('green-passed', 0))
        self.assertEqual([(a['assertion_id'], a['actual']) for a in row['assertions']], [('A1', True), ('A2', True)])
        query = read_json(check_ref(receipt['query_ref']))
        self.assertEqual((query['platform'], query['steps'], query['execution_contract_version']), ('web', STEPS, 2))
        report = read_json(check_ref(receipt['result_ref']))
        self.assertEqual((report['producer'], report['query_sha256'] == digest(query), {m['kind'] for m in report['media_refs']}), ('web-main', True, {'screenshot'}))
        self.assertEqual(len(read_json(check_ref(report['step_trace_ref']))['steps']), 3)
        m = self.f.state()['modules']['M001']
        self.assertEqual((m['results']['P1']['quality'], m['phase']), ('green-passed', 'dod'))

    def test_a_predicate_the_page_does_not_satisfy_is_the_cases_red(self):
        self.texts.write_text(json.dumps({'#heading': 'Orders'}))
        row, receipt = self.run_web()
        self.assertEqual((row['quality'], row['root_cause']['category'], receipt['exit_code']), ('red-bug', 'code', 1))
        self.assertEqual([(a['assertion_id'], a['actual']) for a in row['assertions']], [('A1', False), ('A2', True)])
        m = self.f.state()['modules']['M001']
        self.assertEqual((m['results']['P1']['quality'], m['phase']), ('red-bug', 'testing'))


if __name__ == '__main__':
    unittest.main()
