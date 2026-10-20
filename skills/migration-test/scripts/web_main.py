#!/usr/bin/env python3
"""The built-in web Main. Invoke ONLY through execute_test.py after Ledger authorization: it runs one frozen web PATH in a
real browser (Playwright), keeps a screenshot before and after every step, judges each DOM predicate after its step,
compares the screen with the user's screenshot when an assertion names one, and writes the report the Ledger accepts.
An assertion without an observation is never Green; a step that cannot be performed stops the path and is Yellow."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-ledger/scripts'))
from runner_storage import harmony_output, scope
from run_storage import checked_path
from harmony_contract import digest, ref, write
from web_contract import DEFAULT_TOLERANCE, validate_query

PRODUCER = 'web-main'
PREDICATE_RETRIES = 10  # a predicate that does not hold yet is read again every 300 ms, for 3 s at most
CONTEXT = ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline')
COMPARE_WIDTH = 640


def now():
    return datetime.now(timezone.utc).isoformat()


class PlaywrightPage:
    """A real page in a real browser, headless unless the configuration says otherwise; the video, when recorded, is kept."""
    def __init__(self, config, out):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = getattr(self.playwright, config.get('browser', 'chromium')).launch(headless=config.get('headless', True))
        options = {}
        if config.get('viewport'):
            options['viewport'] = {'width': int(config['viewport']['width']), 'height': int(config['viewport']['height'])}
        if config.get('record_video'):
            options['record_video_dir'] = str(out / 'video')
            if 'viewport' in options: options['record_video_size'] = options['viewport']
        self.context = self.browser.new_context(**options)
        self.page = self.context.new_page()
        self.page.set_default_timeout(int(config.get('timeout_ms', 10_000)))
        self.version = self.browser.version

    def settle(self):
        try: self.page.wait_for_load_state('networkidle', timeout=2000)
        except Exception: pass  # a page that never goes idle is still observed as it is

    def goto(self, url): self.page.goto(url, wait_until='load'); self.settle()
    def click(self, selector): self.page.click(selector); self.settle()
    def fill(self, selector, text): self.page.fill(selector, text)
    def press(self, key): self.page.keyboard.press(key); self.settle()
    def wait(self, ms): self.page.wait_for_timeout(ms)
    def screenshot(self, path): self.page.screenshot(path=str(path))
    def select(self, selector, value): self.page.select_option(selector, value); self.settle()
    def check(self, selector): self.page.check(selector)
    def uncheck(self, selector): self.page.uncheck(selector)
    def hover(self, selector): self.page.hover(selector); self.settle()
    def scroll_to(self, selector): self.page.locator(selector).first.scroll_into_view_if_needed()
    def text(self, selector): found = self.page.locator(selector); return found.first.inner_text() if found.count() else None
    def value(self, selector): found = self.page.locator(selector); return found.first.input_value() if found.count() else None
    def visible(self, selector): found = self.page.locator(selector); return bool(found.count()) and found.first.is_visible()
    def count(self, selector): return self.page.locator(selector).count()
    def attribute(self, selector, name): found = self.page.locator(selector); return found.first.get_attribute(name) if found.count() else None
    def checked(self, selector): found = self.page.locator(selector); return bool(found.count()) and found.first.is_checked()
    def enabled(self, selector): found = self.page.locator(selector); return bool(found.count()) and found.first.is_enabled()
    def url(self): return self.page.url
    def title(self): return self.page.title()

    def close(self):
        video = self.page.video
        try: recorded = Path(video.path()) if video else None  # known before the context closes; the file is complete after
        except Exception: recorded = None
        self.context.close(); self.browser.close(); self.playwright.stop()
        return recorded


def act(page, step):
    action = step['action']
    if action == 'goto': page.goto(step['url'])
    elif action == 'click': page.click(step['selector'])
    elif action == 'fill': page.fill(step['selector'], step['text'])
    elif action == 'press': page.press(step['key'])
    elif action == 'select': page.select(step['selector'], step['value'])
    elif action in ('check', 'uncheck', 'hover', 'scroll_to'): getattr(page, action)(step['selector'])
    else: page.wait(step['ms'])


def judge(page, predicate):
    """(passed, what the page showed) for one DOM predicate."""
    kind = predicate['kind']
    actual = {'text': lambda: page.text(predicate['selector']), 'value': lambda: page.value(predicate['selector']),
              'visible': lambda: page.visible(predicate['selector']), 'count': lambda: page.count(predicate['selector']),
              'checked': lambda: page.checked(predicate['selector']), 'enabled': lambda: page.enabled(predicate['selector']),
              'attribute': lambda: page.attribute(predicate['selector'], predicate['name']),
              'url': page.url, 'title': page.title}[kind]()
    if kind in ('visible', 'checked', 'enabled'): return actual is True, actual
    if 'at_least' in predicate: return isinstance(actual, int) and actual >= predicate['at_least'], actual
    if 'equals' in predicate:
        shown = actual.strip() if isinstance(actual, str) else actual
        return shown == predicate['equals'], actual
    if 'contains' in predicate: return isinstance(actual, str) and predicate['contains'] in actual, actual
    return isinstance(actual, str) and re.search(predicate['matches'], actual) is not None, actual


def visual_score(reference, candidate):
    """The screen against the user's screenshot, scored 0..100 like the package's visual comparison."""
    from PIL import ImageFilter
    from lean_tools import ui_visual_score as v
    a, b = v.resize_to_width(v.load_rgb(reference), COMPARE_WIDTH), v.resize_to_width(v.load_rgb(candidate), COMPARE_WIDTH)
    ra, rb = v.crop_common(a, b, 0)
    ssim = v.global_ssim_gray(ra, rb)
    edges = v.global_ssim_gray(ra.filter(ImageFilter.FIND_EDGES), rb.filter(ImageFilter.FIND_EDGES))
    height = abs(a.height - b.height) / max(1, a.height)
    return v.score_from_metrics(ssim, edges, v.rgb_distance(v.average_rgb(ra), v.average_rgb(rb)), v.mean_abs_error(ra, rb), height)


class Run:
    """One frozen path on one page: every step and every observation is flushed as it happens, so a stop keeps what was seen."""
    def __init__(self, query, out, environment=None):
        self.q, self.out, self.observations, self.error = query, out, [], None
        self.environment = environment or out / 'environment.json'
        self.trace = {'schema_version': 1, 'query_sha256': digest(query), 'steps': [
            {'step_number': i, 'step_sha256': digest(step), 'status': 'not-executed'} for i, step in enumerate(query['steps'], 1)]}
        self.media = []
        self.flush()

    def flush(self):
        write(self.out / 'step-trace.json', self.trace)
        write(self.out / 'observations.json', self.observations)

    def shot(self, name):
        path = self.out / name
        self.page.screenshot(path)
        self.media.append(path)
        return ref(path)

    def observe(self, a, number, step, evidence, result, actual, reason, error=None, unstable=False):
        self.observations.append({'sequence': len(self.observations) + 1, 'assertion_ids': [a['assertion_id']], 'description': a['description'],
                                  'result': result, 'actual': actual, 'reason': reason, 'tool': a['verification'], 'evidence_refs': [evidence],
                                  'error': error, 'after_step': number, 'step_sha256': digest(step), 'recorded_at': now(), 'unstable': unstable})
        self.flush()

    def verify(self, a, number, step, after):
        try:
            if a['verification'] == 'dom':
                passed, actual = judge(self.page, a['predicate'])
                retries = 0
                while not passed and retries < PREDICATE_RETRIES:  # read-only: a page still rendering is read again for a bounded while, never acted on
                    retries += 1; self.page.wait(300); passed, actual = judge(self.page, a['predicate'])
                self.observe(a, number, step, after, passed, actual, 'predicate ' + a['predicate']['kind'] + (f' held after {retries} re-reads' if passed and retries else ' held' if passed else ' did not hold'),
                             unstable=passed and retries > 0)
            else:
                picture = a['reference_media_ref']  # the user's screenshot lives in the run's context, outside this output
                if hashlib.sha256(Path(picture['path']).read_bytes()).hexdigest() != picture['sha256']:
                    raise ValueError('reference screenshot differs from the one the Ledger bound')
                score = visual_score(picture['path'], after['path'])
                tolerance = a.get('tolerance', DEFAULT_TOLERANCE)
                self.observe(a, number, step, after, score >= tolerance, score, f'visual score {score} against tolerance {tolerance}')
        except Exception as exc:  # the observation is kept with its error; nothing is inferred
            self.observe(a, number, step, after, None, None, 'verification failed', f'{type(exc).__name__}: {str(exc)[:200]}')

    def walk(self, page):
        self.page = page
        for number, step in enumerate(self.q['steps'], 1):
            row = self.trace['steps'][number - 1]
            row.update(status='running', started_at=now()); self.flush()
            try:
                row['before_ref'] = self.shot(f'step-{number}-before.png')
                act(page, step)
                after = row['after_ref'] = self.shot(f'step-{number}-after.png')
            except Exception as exc:
                row.update(status='blocked', finished_at=now()); self.flush()
                self.error = f'step {number}: {type(exc).__name__}: {str(exc)[:200]}'
                return
            row.update(status='executed', actions=[step], finished_at=now()); self.flush()
            for a in self.q['expected_assertions']:
                if a['after_step'] == number:
                    self.verify(a, number, step, after)

    def report(self, video):
        rows, unknown = [], []
        for a in self.q['expected_assertions']:
            seen = [e for e in self.observations if e['assertion_ids'] == [a['assertion_id']] and not e['error'] and type(e['result']) is bool]
            actual = seen[-1]['result'] if seen else None
            if actual is None: unknown.append(a['assertion_id'])
            rows.append({'assertion_id': a['assertion_id'], 'expected': True, 'actual': actual, 'passed': actual is True,
                         **({'observed': seen[-1]['actual'], 'unstable': seen[-1].get('unstable', False)} if seen else {})})
        failed = [r['assertion_id'] for r in rows if r['actual'] is False]
        quality = 'yellow-blocked' if self.error or unknown else 'red-bug' if failed else 'green-passed'
        media = [{'kind': 'screenshot', 'ref': ref(p)} for p in self.media] + ([{'kind': 'recording', 'ref': ref(video)}] if video and video.is_file() else [])
        report = {'producer': PRODUCER, 'platform': 'web', 'task_type': 'test', 'step_contract_version': 1, **{k: self.q[k] for k in CONTEXT},
                  'query_sha256': digest(self.q), 'quality': quality, 'assertions': rows, 'flaky': False,
                  'observations_ref': ref(self.out / 'observations.json'), 'step_trace_ref': ref(self.out / 'step-trace.json'),
                  'environment_ref': ref(self.environment), 'media_refs': media, 'artifacts': [], 'unstable': [r['assertion_id'] for r in rows if r.get('unstable')]}
        if quality != 'green-passed':
            problem = self.error or (f'failed frozen assertions: {", ".join(failed)}' if failed else 'assertions without an observation: ' + ', '.join(unknown))
            report['root_cause'] = {'category': 'code' if quality == 'red-bug' else 'tooling', 'summary': problem, 'confidence': 'observed',
                                    'owner': self.q['module_id'], 'next_action': 'diagnose' if quality == 'red-bug' else 'inspect the web Main output and rerun the path',
                                    'evidence_refs': [report['observations_ref'], report['step_trace_ref']]}
        return report


def attempt(query, config, out, open_page, environment):
    run, page, video = Run(query, out, environment), None, None
    try:
        page = open_page(config, out)
        run.walk(page)
    except Exception as exc:
        run.error = run.error or f'{type(exc).__name__}: {str(exc)[:200]}'
    finally:
        if page is not None:
            try: video = page.close()
            except Exception: video = None
    return run.report(video)


def execute(query, config, out, open_page=PlaywrightPage):
    """The path in a page the factory opens; returns the report. Tests inject a page, the host gets a browser. `attempts` in the
    configuration (1..5) walks the path that many times on fresh pages: an assertion that does not come out the same every
    time is flaky, and the path is Yellow for it, as the Harmony Main grades it."""
    attempts = config.get('attempts', 1)
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise ValueError('attempts is an integer in 1..5')
    environment = out / 'environment.json'
    if attempts == 1:
        return attempt(query, config, out, open_page, environment)
    reports = []
    for n in range(1, attempts + 1):
        folder = out / f'attempt-{n}'; folder.mkdir(parents=True, exist_ok=True)
        reports.append(attempt(query, config, folder, open_page, environment))
    report = dict(reports[-1])
    by_id = {a['assertion_id']: {r['assertions'][i]['actual'] for r in reports if i < len(r['assertions'])} for i, a in enumerate(query['expected_assertions'])}
    flaky = sorted(aid for aid, values in by_id.items() if len(values) > 1)
    write(out / 'attempts.json', {'attempts': attempts, 'results': [{'quality': r['quality'], 'assertions': r['assertions']} for r in reports], 'flaky': flaky})
    report.update(attempts_ref=ref(out / 'attempts.json'), flaky=bool(flaky))
    if flaky:
        report['quality'] = 'yellow-blocked'
        report['root_cause'] = {'category': 'flaky', 'summary': 'assertions that did not come out the same in every attempt: ' + ', '.join(flaky),
                                'confidence': 'observed', 'owner': query['module_id'], 'next_action': 'diagnose the instability before any verdict',
                                'evidence_refs': [report['attempts_ref'], report['observations_ref'], report['step_trace_ref']]}
    return report


def main(argv=None, open_page=PlaywrightPage):
    """The adapter entry; a test passes its own page factory, the host gets a browser."""
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('query-file', 'result-file'): parser.add_argument('--' + key, required=True)
    parser.add_argument('--config', help='JSON: browser, headless, viewport {width, height}, record_video, timeout_ms')
    parser.add_argument('--root', help='Run root; otherwise inferred from the canonical result path')
    a = parser.parse_args(argv)
    if os.getpgrp() != os.getpid(): os.setsid()  # this invocation owns its browser processes
    query_bytes = Path(a.query_file).read_bytes()
    q = json.loads(query_bytes)
    result_path = harmony_output(a.root, a.result_file, 'automation')
    if result_path.exists() or result_path.is_symlink():
        raise FileExistsError('result file must be new: ' + str(result_path))
    result_path = result_path.resolve()
    out = result_path.parent / 'web'
    out.mkdir(parents=True, exist_ok=False)
    snapshot = checked_path(result_path.parent / 'query.json')
    if snapshot.exists():
        if snapshot.read_bytes() != query_bytes: raise ValueError('existing query snapshot differs from execution input')
    else:
        with snapshot.open('xb') as stream: stream.write(query_bytes)
    config = json.loads(Path(a.config).read_text()) if a.config else {}
    config['record_video'] = bool(config.get('record_video') or q.get('record_video'))  # the frozen PATH asks for the film, or the run does
    environment = {'python': sys.version, 'platform': 'web', 'task_type': 'test', 'runner_root': str(out), 'query_ref': ref(snapshot),
                   'browser': config.get('browser', 'chromium'), 'headless': config.get('headless', True), 'viewport': config.get('viewport'),
                   'record_video': bool(config.get('record_video')), 'packages': {}}
    for name in ('playwright', 'pillow'):
        try: environment['packages'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: environment['packages'][name] = None
    write(out / 'environment.json', environment)
    try:
        validate_query(q)
        with scope(out):
            report = execute(q, config, out, open_page)
    except ValueError as exc:  # a query the Main cannot run: no step was taken, the reason is the receipt
        run = Run(q, out) if isinstance(q.get('steps'), list) and q.get('expected_assertions') else None
        report = {'producer': PRODUCER, 'platform': 'web', 'task_type': 'test', **{k: q.get(k) for k in CONTEXT}, 'query_sha256': digest(q),
                  'quality': 'yellow-blocked', 'assertions': [], 'flaky': False, 'environment_ref': ref(out / 'environment.json'), 'media_refs': [],
                  'root_cause': {'category': 'tooling', 'summary': str(exc), 'confidence': 'observed', 'owner': q.get('module_id') or 'host',
                                 'next_action': 'request same-Run PATH planning/CR review', 'evidence_refs': []}}
        if run: report.update(observations_ref=ref(out / 'observations.json'), step_trace_ref=ref(out / 'step-trace.json'))
    write(result_path, report)
    return {'green-passed': 0, 'red-bug': 1}.get(report['quality'], 2)


if __name__ == '__main__':
    sys.exit(main())
