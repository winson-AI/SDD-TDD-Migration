"""The built-in web Main: a frozen web PATH is walked step by step on a page, every predicate is judged after its step
on what the page shows, and the verdict is what was observed, never what was expected."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from harmony_contract import digest, ref
import web_main
from web_contract import validate_query


def query(**over):
    return {'run_id': 'R', 'module_id': 'M001', 'path_id': 'P1', 'name': 'login', 'freeze_id': 'F', 'code_baseline': 'B', 'platform': 'web', 'task_type': 'test',
            'steps': [{'action': 'goto', 'url': 'http://127.0.0.1:1/index.html'}, {'action': 'fill', 'selector': '#user', 'text': 'ann'}, {'action': 'click', 'selector': '#submit'}],
            'expected_assertions': [{'assertion_id': 'A1', 'expected': True, 'description': 'the list heading reads Items', 'matcher': 'exact', 'verification': 'dom',
                                     'after_step': 3, 'predicate': {'kind': 'text', 'selector': '#heading', 'equals': 'Items'}}], **over}


def png(color):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (120, 80), color); ImageDraw.Draw(image).rectangle((10, 10, 60, 40), fill=(0, 0, 0))
    out = io.BytesIO(); image.save(out, format='PNG'); return out.getvalue()


class FakePage:
    """What a page shows, as the Main reads it; `fail` names the action that cannot be performed; `late` is what the page
    shows only after a few reads."""
    def __init__(self, texts, pixels=None, late=None, config=None):
        self.calls, self.texts, self.pixels, self.fail, self.late, self.reads, self.config = [], texts, pixels or png((255, 255, 255)), None, late or {}, 0, config

    def act(self, *call):
        self.calls.append(call)
        if self.fail == call[0]: raise RuntimeError('Timeout 10000ms exceeded')

    def goto(self, url): self.act('goto', url)
    def click(self, selector): self.act('click', selector)
    def fill(self, selector, text): self.act('fill', selector, text)
    def press(self, key): self.act('press', key)
    def wait(self, ms): self.act('wait', ms)
    def screenshot(self, path): Path(path).write_bytes(self.pixels)
    def text(self, selector):
        self.reads += 1
        if self.reads >= 3: self.texts.update(self.late)
        return self.texts.get(selector)
    def value(self, selector): return self.texts.get(selector)
    def visible(self, selector): return selector in self.texts
    def count(self, selector): return 1 if selector in self.texts else 0
    def url(self): return 'http://127.0.0.1:1/list.html'
    def title(self): return 'Legacy List'
    def select(self, selector, value): self.act('select', selector, value); self.texts[selector] = value
    def check(self, selector): self.act('check', selector); self.texts[selector + ':checked'] = True
    def uncheck(self, selector): self.act('uncheck', selector); self.texts[selector + ':checked'] = False
    def hover(self, selector): self.act('hover', selector)
    def scroll_to(self, selector): self.act('scroll_to', selector)
    def attribute(self, selector, name): return self.texts.get(selector + '@' + name)
    def checked(self, selector): return self.texts.get(selector + ':checked') is True
    def enabled(self, selector): return selector in self.texts and not self.texts.get(selector + ':disabled')
    def close(self): self.calls.append(('close',)); return None


class ContractTests(unittest.TestCase):
    def test_what_the_main_cannot_run_is_refused_before_a_browser_opens(self):
        self.assertEqual(validate_query(query()), query())
        bad = [('platform', 'android'), ('steps', [{'action': 'click', 'selector': '#x'}]), ('steps', [{'action': 'goto', 'url': 'index.html'}]),
               ('steps', [{'action': 'goto', 'url': 'http://h/'}, {'action': 'scroll', 'dy': 1}]), ('steps', [{'action': 'goto', 'url': 'http://h/'}, {'action': 'wait', 'ms': 0}]),
               ('steps', [{'action': 'goto', 'url': 'http://h/', 'extra': 1}])]
        for key, value in bad:
            with self.assertRaises(ValueError, msg=key): validate_query(query(**{key: value}))
        assertion = query()['expected_assertions'][0]
        for change in ({'matcher': 'semantic'}, {'after_step': 4}, {'expected': 'Items'}, {'verification': 'one_image_assert'},
                       {'predicate': {'kind': 'text', 'selector': '#h'}}, {'predicate': {'kind': 'count', 'selector': '#h', 'equals': '1'}},
                       {'predicate': {'kind': 'visible', 'selector': '#h', 'equals': 'x'}}, {'predicate': {'kind': 'url', 'matches': '('}},
                       {'verification': 'refer_image_assert'}, {'verification': 'refer_image_assert', 'reference_media_ref': {'path': '/x.png', 'sha256': 'ab'}}):
            with self.assertRaises(ValueError, msg=str(change)): validate_query(query(expected_assertions=[{**assertion, **change}]))
        validate_query(query(expected_assertions=[{**assertion, 'predicate': {'kind': 'count', 'selector': 'li', 'equals': 3}},
                                                  {**assertion, 'assertion_id': 'A2', 'predicate': {'kind': 'url', 'matches': 'list'}},
                                                  {**assertion, 'assertion_id': 'A3', 'verification': 'refer_image_assert', 'reference_media_ref': {'path': '/x.png', 'sha256': 'a' * 64}}]))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.out = self.base / '.sdd-runs/contract/runs/harmony/automation/attempt/web'; self.out.mkdir(parents=True)
        (self.out / 'environment.json').write_text('{}')

    def run_path(self, page, q=None):
        return web_main.execute(q or query(), {}, self.out, open_page=lambda config, out: page), page

    def test_a_path_walks_in_order_and_its_predicates_decide_the_verdict(self):
        report, page = self.run_path(FakePage({'#heading': 'Items', '#user': 'ann'}))
        self.assertEqual(report['quality'], 'green-passed')
        self.assertEqual([c[0] for c in page.calls], ['goto', 'fill', 'click', 'close'])
        self.assertEqual(report['assertions'], [{'assertion_id': 'A1', 'expected': True, 'actual': True, 'passed': True, 'observed': 'Items', 'unstable': False}])
        trace = json.loads((self.out / 'step-trace.json').read_text())
        self.assertEqual((trace['query_sha256'], [s['status'] for s in trace['steps']]), (digest(query()), ['executed'] * 3))
        self.assertTrue(all(Path(s['before_ref']['path']).is_file() and Path(s['after_ref']['path']).is_file() for s in trace['steps']))
        observed = json.loads((self.out / 'observations.json').read_text())
        self.assertEqual((observed[0]['assertion_ids'], observed[0]['after_step'], observed[0]['result'], observed[0]['evidence_refs']),
                         (['A1'], 3, True, [trace['steps'][2]['after_ref']]))
        self.assertEqual((report['producer'], report['platform'], report['query_sha256'], len(report['media_refs'])), ('web-main', 'web', digest(query()), 6))
        self.assertEqual({m['kind'] for m in report['media_refs']}, {'screenshot'})
        report, _ = self.run_path(FakePage({'#heading': 'Orders'}))
        self.assertEqual((report['quality'], report['assertions'][0]['actual'], report['root_cause']['category']), ('red-bug', False, 'code'))
        self.assertIn('A1', report['root_cause']['summary'])

    def test_every_predicate_kind_reads_what_the_page_shows(self):
        a = query()['expected_assertions'][0]
        predicates = [('P1', {'kind': 'value', 'selector': '#user', 'equals': 'ann'}), ('P2', {'kind': 'visible', 'selector': '#heading'}),
                      ('P3', {'kind': 'count', 'selector': '#missing', 'equals': 0}), ('P4', {'kind': 'url', 'contains': 'list.html'}),
                      ('P5', {'kind': 'title', 'matches': '^Legacy'}), ('P6', {'kind': 'text', 'selector': '#missing', 'equals': 'x'})]
        q = query(expected_assertions=[{**a, 'assertion_id': aid, 'predicate': p} for aid, p in predicates])
        report, _ = self.run_path(FakePage({'#heading': 'Items', '#user': 'ann'}), q)
        self.assertEqual({r['assertion_id']: r['actual'] for r in report['assertions']}, {'P1': True, 'P2': True, 'P3': True, 'P4': True, 'P5': True, 'P6': False})
        self.assertEqual(report['quality'], 'red-bug')

    def test_a_predicate_that_holds_only_after_the_page_settles_is_read_again_and_the_path_film_follows_the_frozen_flag(self):
        page = FakePage({'#heading': 'Loading'}, late={'#heading': 'Items'})
        report, _ = self.run_path(page)
        self.assertEqual((report['quality'], report['assertions'][0]['observed']), ('green-passed', 'Items'))
        self.assertGreaterEqual(page.calls.count(('wait', 300)), 1)
        report, page = self.run_path(FakePage({'#heading': 'Orders'}))
        self.assertEqual((report['quality'], page.calls.count(('wait', 300))), ('red-bug', web_main.PREDICATE_RETRIES))
        seen = {}
        web_main.execute(query(record_video=True), {}, self.out, open_page=lambda config, out: seen.update(config) or FakePage({'#heading': 'Items'}))
        self.assertNotIn('record_video', seen)  # execute takes the configuration as given; main() merges the frozen flag into it
        import io as _io, contextlib
        q = query(record_video=True); (self.out.parent / 'q.json').write_text(json.dumps(q))
        argv = ['--query-file', str(self.out.parent / 'q.json'), '--result-file', str(self.out.parent / 'r' / 'result.json'), '--root', str(self.base / '.sdd-runs/contract')]
        web_main.main(argv, open_page=lambda config, out: seen.update(config) or FakePage({'#heading': 'Items'}))
        self.assertTrue(seen['record_video'])

    def test_forms_are_driven_and_judged_by_their_own_actions_and_predicates(self):
        a = query()['expected_assertions'][0]
        steps = query()['steps'] + [{'action': 'select', 'selector': '#role', 'value': 'admin'}, {'action': 'check', 'selector': '#agree'},
                                    {'action': 'hover', 'selector': 'a.login'}, {'action': 'scroll_to', 'selector': '#footer'}, {'action': 'uncheck', 'selector': '#news'}]
        predicates = [('P1', {'kind': 'value', 'selector': '#role', 'equals': 'admin'}), ('P2', {'kind': 'checked', 'selector': '#agree'}),
                      ('P3', {'kind': 'checked', 'selector': '#news'}), ('P4', {'kind': 'attribute', 'selector': 'a.login', 'name': 'href', 'contains': 'list'}),
                      ('P5', {'kind': 'enabled', 'selector': '#submit'}), ('P6', {'kind': 'count', 'selector': 'li', 'at_least': 1})]
        q = query(steps=steps, expected_assertions=[{**a, 'assertion_id': aid, 'after_step': 8, 'predicate': p} for aid, p in predicates])
        page = FakePage({'#heading': 'Items', '#submit': 'Sign in', 'a.login@href': 'list.html', 'li': 'x'})
        report, _ = self.run_path(page, q)
        self.assertEqual([c[0] for c in page.calls][3:8], ['select', 'check', 'hover', 'scroll_to', 'uncheck'])
        self.assertEqual({r['assertion_id']: r['actual'] for r in report['assertions']}, {'P1': True, 'P2': True, 'P3': False, 'P4': True, 'P5': True, 'P6': True})
        for bad in ({'kind': 'attribute', 'selector': 'a', 'equals': 'x'}, {'kind': 'checked', 'selector': 'a', 'equals': 'x'}, {'kind': 'text', 'selector': 'a', 'at_least': 1},
                    {'kind': 'count', 'selector': 'li', 'at_least': -1}):
            with self.assertRaises(ValueError, msg=str(bad)): validate_query(query(expected_assertions=[{**a, 'predicate': bad}]))
        with self.assertRaises(ValueError): validate_query(query(steps=query()['steps'] + [{'action': 'select', 'selector': '#role'}]))

    def test_repeated_attempts_expose_a_flaky_assertion_and_a_stable_one_stays_green(self):
        pages = iter([FakePage({'#heading': 'Items'}), FakePage({'#heading': 'Orders'}), FakePage({'#heading': 'Items'})])
        report = web_main.execute(query(), {'attempts': 3}, self.out, open_page=lambda config, out: next(pages))
        self.assertEqual((report['quality'], report['flaky'], report['root_cause']['category']), ('yellow-blocked', True, 'flaky'))
        self.assertIn('A1', report['root_cause']['summary'])
        attempts = json.loads(Path(report['attempts_ref']['path']).read_text())
        self.assertEqual(([r['quality'] for r in attempts['results']], attempts['flaky']), (['green-passed', 'red-bug', 'green-passed'], ['A1']))
        self.assertTrue(all((self.out / f'attempt-{n}' / 'step-trace.json').is_file() for n in (1, 2, 3)))
        stable = self.out / 'stable'; stable.mkdir(); (stable / 'environment.json').write_text('{}')
        report = web_main.execute(query(), {'attempts': 2}, stable, open_page=lambda config, out: FakePage({'#heading': 'Items'}))
        self.assertEqual((report['quality'], report['flaky']), ('green-passed', False))
        with self.assertRaises(ValueError): web_main.execute(query(), {'attempts': 9}, self.out)

    def test_a_step_that_cannot_be_performed_stops_the_path_as_yellow(self):
        page = FakePage({'#heading': 'Items'}); page.fail = 'click'
        report, _ = self.run_path(page)
        self.assertEqual((report['quality'], report['assertions'][0]['actual'], report['root_cause']['category']), ('yellow-blocked', None, 'tooling'))
        self.assertTrue(report['root_cause']['summary'].startswith('step 3: RuntimeError'))
        trace = json.loads((self.out / 'step-trace.json').read_text())
        self.assertEqual([s['status'] for s in trace['steps']], ['executed', 'executed', 'blocked'])
        self.assertEqual(json.loads((self.out / 'observations.json').read_text()), [])

    def test_the_user_screenshot_is_the_reference_of_the_assertion_that_names_it(self):
        reference = self.base / '.sdd-runs/contract/context/user-shot.png'; reference.parent.mkdir(parents=True); reference.write_bytes(png((255, 255, 255)))
        bound = {'path': str(reference), 'sha256': hashlib.sha256(reference.read_bytes()).hexdigest()}
        a = query()['expected_assertions'][0]
        shot = {**a, 'assertion_id': 'S1', 'verification': 'refer_image_assert', 'reference_media_ref': bound}; shot.pop('predicate')
        report, _ = self.run_path(FakePage({'#heading': 'Items'}), query(expected_assertions=[a, shot]))
        self.assertEqual((report['quality'], report['assertions'][1]['actual'], report['assertions'][1]['observed']), ('green-passed', True, 100.0))
        report, _ = self.run_path(FakePage({'#heading': 'Items'}, pixels=png((20, 20, 20))), query(expected_assertions=[a, {**shot, 'tolerance': 99}]))
        self.assertEqual((report['quality'], report['assertions'][1]['actual']), ('red-bug', False))
        self.assertLess(report['assertions'][1]['observed'], 99)
        reference.write_bytes(png((0, 0, 255)))  # the file no longer is what the Ledger bound
        report, _ = self.run_path(FakePage({'#heading': 'Items'}), query(expected_assertions=[a, shot]))
        self.assertEqual((report['quality'], report['assertions'][1]['actual']), ('yellow-blocked', None))
        self.assertIn('differs', json.loads((self.out / 'observations.json').read_text())[1]['error'])


if __name__ == '__main__':
    unittest.main()
