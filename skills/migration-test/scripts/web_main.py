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
    def text(self, selector): found = self.page.locator(selector); return found.first.inner_text() if found.count() else None
    def value(self, selector): found = self.page.locator(selector); return found.first.input_value() if found.count() else None
    def visible(self, selector): found = self.page.locator(selector); return bool(found.count()) and found.first.is_visible()
    def count(self, selector): return self.page.locator(selector).count()
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
    else: page.wait(step['ms'])


def judge(page, predicate):
    """(passed, what the page showed) for one DOM predicate."""
    kind = predicate['kind']
    actual = {'text': lambda: page.text(predicate['selector']), 'value': lambda: page.value(predicate['selector']),
              'visible': lambda: page.visible(predicate['selector']), 'count': lambda: page.count(predicate['selector']),
              'url': page.url, 'title': page.title}[kind]()
    if kind == 'visible': return actual is True, actual
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
    def __init__(self, query, out):
        self.q, self.out, self.observations, self.error = query, out, [], None
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

    def observe(self, a, number, step, evidence, result, actual, reason, error=None):
        self.observations.append({'sequence': len(self.observations) + 1, 'assertion_ids': [a['assertion_id']], 'description': a['description'],
                                  'result': result, 'actual': actual, 'reason': reason, 'tool': a['verification'], 'evidence_refs': [evidence],
                                  'error': error, 'after_step': number, 'step_sha256': digest(step), 'recorded_at': now()})
        self.flush()

    def verify(self, a, number, step, after):
        try:
            if a['verification'] == 'dom':
                passed, actual = judge(self.page, a['predicate'])
                self.observe(a, number, step, after, passed, actual, 'predicate ' + a['predicate']['kind'] + (' held' if passed else ' did not hold'))
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
                         **({'observed': seen[-1]['actual']} if seen else {})})
        failed = [r['assertion_id'] for r in rows if r['actual'] is False]
        quality = 'yellow-blocked' if self.error or unknown else 'red-bug' if failed else 'green-passed'
        media = [{'kind': 'screenshot', 'ref': ref(p)} for p in self.media] + ([{'kind': 'recording', 'ref': ref(video)}] if video and video.is_file() else [])
        report = {'producer': PRODUCER, 'platform': 'web', 'task_type': 'test', 'step_contract_version': 1, **{k: self.q[k] for k in CONTEXT},
                  'query_sha256': digest(self.q), 'quality': quality, 'assertions': rows, 'flaky': False,
                  'observations_ref': ref(self.out / 'observations.json'), 'step_trace_ref': ref(self.out / 'step-trace.json'),
                  'environment_ref': ref(self.out / 'environment.json'), 'media_refs': media, 'artifacts': []}
        if quality != 'green-passed':
            problem = self.error or (f'failed frozen assertions: {", ".join(failed)}' if failed else 'assertions without an observation: ' + ', '.join(unknown))
            report['root_cause'] = {'category': 'code' if quality == 'red-bug' else 'tooling', 'summary': problem, 'confidence': 'observed',
                                    'owner': self.q['module_id'], 'next_action': 'diagnose' if quality == 'red-bug' else 'inspect the web Main output and rerun the path',
                                    'evidence_refs': [report['observations_ref'], report['step_trace_ref']]}
        return report


def execute(query, config, out, open_page=PlaywrightPage):
    """The path in a page the factory opens; returns the report. Tests inject a page, the host gets a browser."""
    run, page, video = Run(query, out), None, None
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('query-file', 'result-file'): parser.add_argument('--' + key, required=True)
    parser.add_argument('--config', help='JSON: browser, headless, viewport {width, height}, record_video, timeout_ms')
    parser.add_argument('--root', help='Run root; otherwise inferred from the canonical result path')
    a = parser.parse_args()
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
            report = execute(q, config, out)
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
