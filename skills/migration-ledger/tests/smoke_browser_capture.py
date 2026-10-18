"""A live smoke of the browser legacy lane, one case per way a legacy web application behaves: an inner list that scrolls, a
page that scrolls as a whole, a single-page view rendered after a click, a list that loads more while it is scrolled, a
component behind a shadow root beside a same-origin frame, form fields matched by their placeholder, and a phone viewport.
Each case is captured through the worker in a real headless Chromium, then analysed into the runtime index and the
DOM-derived tree and frozen as UI evidence. Not collected by pytest: it needs a Python with Playwright (and an installed
Chromium) and Pillow, which the package does not vendor. Exit code 0 means every case walked end to end.

    <python-with-playwright> skills/migration-ledger/tests/smoke_browser_capture.py [--keep] [--only <case>]
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import file_ref, read_json
import lean_adapter
import lean_visual_worker as worker
import lean_worker
import semantics
import ui_evidence

STYLE = ('body{margin:0;font-family:sans-serif}h1,h2{margin:0;height:80px;line-height:80px;padding-left:24px}'
         'ul{margin:0;padding:0;list-style:none}li{height:40px;line-height:40px;padding-left:24px;border-bottom:1px solid #eee}'
         'ul.inner{height:600px;overflow-y:auto}form{padding:24px}input{display:block;margin:8px 0}')
HEAD = '<!doctype html><html><head><meta charset="utf-8"><title>%s</title><style>' + STYLE + '</style></head><body>'


def rows(n, start=0, end=False):
    return ''.join(f'<li class="row">Item {i}</li>' for i in range(start, start + n)) + ('<li class="row" id="end">End</li>' if end else '')


def write_site(folder):
    (folder / 'index.html').write_text(HEAD % 'Legacy Login' + '<h1 id="title">Sign in</h1><img id="logo" src="logo.png" alt="logo" aria-label="logo" width="120" height="20">'
                                       '<form id="form"><input id="user" placeholder="user name"><button id="submit" type="button">Sign in</button></form>'
                                       '<a class="login" id="to-list" href="list.html">Continue</a></body></html>')
    (folder / 'list.html').write_text(HEAD % 'Legacy List' + '<h1 id="heading">Items</h1><ul id="list" class="inner" aria-label="items">' + rows(60, end=True) + '</ul></body></html>')
    (folder / 'page.html').write_text(HEAD % 'Legacy Feed' + '<h1 id="heading">Feed</h1><ul id="feed">' + rows(80, end=True) + '</ul></body></html>')
    (folder / 'spa.html').write_text(HEAD % 'Legacy Orders' + '<h1 id="heading">Orders app</h1><button id="load" type="button">Load orders</button><div id="view"></div>'
                                     '<script>document.getElementById("load").addEventListener("click", () => { setTimeout(() => { document.getElementById("view").innerHTML = '
                                     '\'<h2 id="orders-title">Orders</h2><ul id="orders">\' + Array.from({length: 5}, (_, i) => \'<li class="row">Order \' + i + \'</li>\').join(\'\') + \'</ul>\'; }, 400); });</script></body></html>')
    (folder / 'lazy.html').write_text(HEAD % 'Legacy Lazy' + '<h1 id="heading">Lazy</h1><ul id="lazy" class="inner">' + rows(15) + '</ul>'
                                      '<script>const ul = document.getElementById("lazy"); let count = 15, busy = false;'
                                      'ul.addEventListener("scroll", () => { if (busy || count >= 45) return; if (ul.scrollTop + ul.clientHeight >= ul.scrollHeight - 80) { busy = true;'
                                      ' setTimeout(() => { for (let i = 0; i < 15; i++) { const li = document.createElement("li"); li.className = "row"; li.textContent = "Item " + (count + i); ul.appendChild(li); }'
                                      ' count += 15; if (count >= 45) { const end = document.createElement("li"); end.className = "row"; end.id = "end"; end.textContent = "End"; ul.appendChild(end); } busy = false; }, 300); } });</script></body></html>')
    (folder / 'shadow.html').write_text(HEAD % 'Legacy Account' + '<app-header></app-header><iframe id="legal" src="frame.html" width="600" height="120"></iframe>'
                                        '<script>customElements.define("app-header", class extends HTMLElement { connectedCallback() { const root = this.attachShadow({mode: "open"});'
                                        ' root.innerHTML = \'<style>h1{margin:0;height:80px;line-height:80px;padding-left:24px}</style><h1 id="title">Account</h1>\'; } });</script></body></html>')
    (folder / 'frame.html').write_text(HEAD % 'Legal' + '<p id="terms">Terms apply</p></body></html>')
    import struct, zlib
    raw = b''.join(b'\x00' + bytes((30, 90, 200)) * 120 for _ in range(20))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    (folder / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 120, 20, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


CASES = {
    'inner-scroll': ('index.html', None, [{'coverage': 'login:base:viewport', 'target_match': [{'resource-id': 'title', 'text': 'Sign in'}]},
                                          {'coverage': 'list:base:scroll', 'actions': [{'action': 'click', 'selector': 'a.login'}], 'target_match': [{'resource-id': 'list'}],
                                           'scroll_region': {'resource-id': 'list'}, 'scroll_end_match': [{'text': 'End'}], 'max_scrolls': 12}], {'list:base:scroll': 'scroll-complete'}),
    'page-scroll': ('page.html', None, [{'coverage': 'feed:base:scroll', 'target_match': [{'resource-id': 'feed'}], 'scroll_region': {'class': 'body'},
                                         'scroll_end_match': [{'text': 'End'}], 'max_scrolls': 20}], {'feed:base:scroll': 'scroll-complete'}),
    'spa-click': ('spa.html', None, [{'coverage': 'orders:loaded:viewport', 'actions': [{'action': 'click', 'selector': '#load'}],
                                      'target_match': [{'resource-id': 'orders-title', 'text': 'Orders'}]}], {}),
    'lazy-list': ('lazy.html', None, [{'coverage': 'lazy:base:scroll', 'target_match': [{'resource-id': 'lazy'}], 'scroll_region': {'resource-id': 'lazy'},
                                       'scroll_end_match': [{'text': 'End'}], 'max_scrolls': 20}], {'lazy:base:scroll': 'scroll-complete'}),
    'shadow-iframe': ('shadow.html', None, [{'coverage': 'account:base:viewport', 'target_match': [{'resource-id': 'title', 'text': 'Account'}, {'resource-id': 'terms', 'text': 'Terms apply'}]}], {}),
    'form-fields': ('index.html', None, [{'coverage': 'login:fields:viewport', 'target_match': [{'resource-id': 'user', 'text': 'user name'}, {'resource-id': 'submit', 'text': 'Sign in'}]}], {}),
    'phone-viewport': ('index.html', {'width': 390, 'height': 844}, [{'coverage': 'login:phone:viewport', 'target_match': [{'resource-id': 'title', 'text': 'Sign in'}]}], {'screenshot': (390, 844)}),
}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


def run_case(name, origin, base):
    page, viewport, targets, expect = CASES[name]
    url = origin + '/' + page
    root = base / name / '.sdd-runs/run-1'; (root / 'context').mkdir(parents=True)
    stated = {'kind': 'browser', 'url': url, **({'viewport': viewport} if viewport else {})}
    statement = root / 'context/legacy-preview.json'; statement.write_text(json.dumps({'effective_config': {'legacy_preview': stated}, 'source_refs': {}}))
    state = {'run_id': 'run-1', 'project_context_ref': file_ref(statement), 'modules': {}}
    task = {'role': 'spec-designer', 'assignment_id': 'A1', 'fencing_token': 'fence-1'}
    actor = {'role': 'spec-designer', 'instance_id': 'spec-1', 'device_lock': {'held': True, 'device_id': url, 'assignment_id': 'A1', 'fencing_token': 'fence-1'}}
    out = root / 'runs/harmony/sandbox/spec-1/attempt-1'; out.mkdir(parents=True)
    started = time.time()
    result = worker.legacy_capture({'targets': targets}, root=root, out=out, state=state, task=task, actor=actor, module_id='M001')
    row = {'case': name, 'status': result['status'], 'captured': result.get('captured'), 'blocked': result.get('blocked') or (result.get('root_cause') or {}).get('reason')}
    try:
        if result['status'] != 'CAPTURED':
            return row, False
        ok = True
        for coverage, achieved in expect.items():
            if coverage == 'screenshot':
                from PIL import Image
                record = ui_evidence.capture_target(result['manifest_ref'], targets[0]['coverage'])
                size = Image.open(record['snapshot']['screenshot']).size
                row['screenshot'] = size; ok = ok and size == achieved
            else:
                record = ui_evidence.capture_target(result['manifest_ref'], coverage)
                row[coverage] = record['coverage']; ok = ok and record['coverage']['achieved'] == achieved
        analysis = lean_worker.web_analysis({'platform': 'web', 'capture_ref': result['manifest_ref'], 'targets': [t['coverage'] for t in targets]}, 'M001', out / 'analysis')
        ui_evidence.validate_tree_ref(analysis['ui_tree_ref'], runtime_index_ref=analysis['runtime_index_ref'])
        manifest = read_json(result['manifest_ref']['path'])
        for target in targets:
            evidence = lean_adapter.ui_evidence(manifest, analysis['ui_tree_ref'], target=target['coverage'], capture_ref=result['manifest_ref'], runtime_index_ref=analysis['runtime_index_ref'])
            semantics._ui_evidence({'ui_evidence': evidence})
        row['tree_screens'] = len(read_json(analysis['ui_tree_ref']['path'])['screens'])
        return row, ok
    except Exception as exc:  # the smoke reports, it does not hide
        row['error'] = type(exc).__name__ + ': ' + str(exc)[:200]
        return row, False
    finally:
        row['seconds'] = round(time.time() - started, 1)


def main():
    keep = '--keep' in sys.argv
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    base = Path(tempfile.mkdtemp(prefix='sdd-browser-smoke-')).resolve()  # managed paths never pass through a symlink
    try:
        site = base / 'site'; site.mkdir(); write_site(site)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(site)))  # served, as a legacy web application is
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = 'http://127.0.0.1:%d' % server.server_address[1]
        passed = True
        for name in CASES:
            if only and name != only:
                continue
            row, ok = run_case(name, origin, base)
            passed = passed and ok
            print(('PASS ' if ok else 'FAIL ') + json.dumps(row, ensure_ascii=False))
        server.shutdown()
        if keep:
            print('kept', base)
        return 0 if passed else 1
    finally:
        if not keep:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
