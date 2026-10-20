"""A live smoke of the built-in web Main: a legacy-shaped login site is served over HTTP, a frozen web PATH is run through
web_main.py in a real headless Chromium with video, and the Ledger's completion contract reads the report. The first run
leaves the screen after the last step; the second run names that screen as the user's screenshot, so the reference
assertion is judged against it. Not collected by pytest: it needs a Python with Playwright (and an installed Chromium)
and Pillow. Exit code 0 means both runs were accepted as Green.

    <python-with-playwright> skills/migration-test/tests/smoke_web_main.py [--keep]
"""
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / 'migration-ledger/scripts'))
sys.path.insert(0, str(HERE.parents[2] / 'migration-ledger/tests'))
from contracts import digest, file_ref
import smoke_browser_capture as site
import test_completion

MAIN = HERE.parents[1] / 'scripts/web_main.py'


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


def query(origin, reference=None):
    dom = lambda aid, after, description, predicate: {'assertion_id': aid, 'expected': True, 'description': description, 'matcher': 'exact', 'verification': 'dom',
                                                       'after_step': after, 'predicate': predicate}
    assertions = [dom('A1', 6, 'the list heading reads Items', {'kind': 'text', 'selector': '#heading', 'equals': 'Items'}),
                  dom('A2', 6, 'the list page is open', {'kind': 'url', 'contains': 'list.html'}),
                  dom('A3', 2, 'the user name was typed', {'kind': 'value', 'selector': '#user', 'equals': 'ann'}),
                  dom('A5', 3, 'the role was chosen', {'kind': 'value', 'selector': '#role', 'equals': 'user'}),
                  dom('A6', 4, 'the terms were accepted', {'kind': 'checked', 'selector': '#agree'}),
                  dom('A7', 5, 'the link leads to the list', {'kind': 'attribute', 'selector': 'a.login', 'name': 'href', 'contains': 'list'}),
                  dom('A8', 6, 'the list holds rows', {'kind': 'count', 'selector': '#list li', 'at_least': 10})]
    if reference:
        assertions.append({'assertion_id': 'A4', 'expected': True, 'description': 'the list screen the user showed', 'matcher': 'exact',
                           'verification': 'refer_image_assert', 'after_step': 6, 'reference_media_ref': reference, 'tolerance': 90})
    return {'run_id': 'smoke', 'module_id': 'M001', 'path_id': 'P1', 'name': 'login then list', 'freeze_id': 'F', 'code_baseline': 'B', 'platform': 'web',
            'task_type': 'test', 'kind': 'automation', 'execution_contract_version': 2,
            'steps': [{'action': 'goto', 'url': origin + '/index.html'}, {'action': 'fill', 'selector': '#user', 'text': 'ann'},
                      {'action': 'select', 'selector': '#role', 'value': 'user'}, {'action': 'check', 'selector': '#agree'},
                      {'action': 'hover', 'selector': 'a.login'}, {'action': 'click', 'selector': 'a.login'}],
            'expected_assertions': assertions}


def run_once(name, base, q, record_video):
    attempt = base / '.sdd-runs/smoke/runs/harmony/automation' / name; attempt.mkdir(parents=True)
    config = base / f'{name}-config.json'; config.write_text(json.dumps({'headless': True, 'viewport': {'width': 1000, 'height': 700}, 'record_video': record_video, 'attempts': 2 if record_video else 1}))
    query_file = base / f'{name}-query.json'; query_file.write_text(json.dumps(q))
    started = time.time()
    run = subprocess.run([sys.executable, str(MAIN), '--query-file', str(query_file), '--result-file', str(attempt / 'result.json'), '--config', str(config)],
                         capture_output=True, text=True, timeout=300)
    row = {'case': name, 'exit_code': run.returncode, 'seconds': round(time.time() - started, 1)}
    if not (attempt / 'result.json').is_file():
        row['stderr'] = run.stderr[-400:]; return row, False, None
    report = json.loads((attempt / 'result.json').read_text())
    row['quality'] = report['quality']; row['assertions'] = {a['assertion_id']: a.get('observed', a['actual']) for a in report['assertions']}
    row['media'] = sorted({m['kind'] for m in report['media_refs']}); row['screenshots'] = sum(1 for m in report['media_refs'] if m['kind'] == 'screenshot')
    row['flaky'] = report.get('flaky'); row['unstable'] = report.get('unstable')
    (attempt / 'log.txt').write_text(run.stdout + run.stderr)
    receipt = {'execution_contract_version': 2, **{k: q[k] for k in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline')}, 'exit_code': run.returncode,
               'query_ref': file_ref(query_file), 'log_ref': file_ref(attempt / 'log.txt'), 'result_ref': file_ref(attempt / 'result.json')}
    planned = {k: q[k] for k in ('path_id', 'kind', 'platform', 'task_type', 'expected_assertions')}
    accepted = test_completion.interpret(receipt, planned)
    row['ledger'] = (accepted['quality'], accepted.get('execution_status'))
    if accepted['quality'] != 'green-passed':
        row['root_cause'] = accepted['root_cause']['summary'][:200]
    trace = json.loads(Path(report['step_trace_ref']['path']).read_text())
    last_screen = trace['steps'][-1]['after_ref']
    return row, accepted['quality'] == 'green-passed' and report['quality'] == 'green-passed' and (not record_video or 'recording' in row['media']), last_screen


def main():
    keep = '--keep' in sys.argv
    base = Path(tempfile.mkdtemp(prefix='sdd-web-main-smoke-')).resolve()
    try:
        folder = base / 'site'; folder.mkdir(); site.write_site(folder)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(folder)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = 'http://127.0.0.1:%d' % server.server_address[1]
        passed = True
        row, ok, last_screen = run_once('dom-predicates', base, query(origin), record_video=True)
        passed = passed and ok; print(('PASS ' if ok else 'FAIL ') + json.dumps(row, ensure_ascii=False))
        if last_screen:
            shown = base / '.sdd-runs/smoke/context/user-list-screen.png'; shown.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(last_screen['path'], shown)
            reference = {'path': str(shown), 'sha256': hashlib.sha256(shown.read_bytes()).hexdigest()}
            row, ok, _ = run_once('user-screenshot', base, query(origin, reference), record_video=False)
            passed = passed and ok; print(('PASS ' if ok else 'FAIL ') + json.dumps(row, ensure_ascii=False))
        server.shutdown()
        if keep: print('kept', base)
        return 0 if passed else 1
    finally:
        if not keep: shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
