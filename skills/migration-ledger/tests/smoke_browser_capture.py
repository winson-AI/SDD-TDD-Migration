"""A live smoke of the browser legacy lane: a small legacy web site is written to a temporary folder, captured through the
worker in a real headless Chromium (viewport and a scroll to its frozen end), analysed into the runtime index and the
DOM-derived tree, and frozen as UI evidence. Not collected by pytest: it needs a Python with Playwright (and an installed
Chromium) and Pillow, which the package does not vendor. Exit code 0 means the lane walked end to end.

    <python-with-playwright> skills/migration-ledger/tests/smoke_browser_capture.py [--keep]
"""
import json
import shutil
import sys
import tempfile
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

ROWS = 60
STYLE = ('body{margin:0;font-family:sans-serif}h1{margin:0;height:80px;line-height:80px;padding-left:24px}'
         'ul#list{margin:0;padding:0;list-style:none;height:600px;overflow-y:auto}li{height:40px;line-height:40px;padding-left:24px}')


def write_site(folder):
    (folder / 'index.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>Legacy Login</title><style>' + STYLE + '</style></head>'
                                       '<body><h1 id="title">Sign in</h1><img id="logo" src="logo.png" alt="logo" aria-label="logo" width="120" height="20">'
                                       '<form id="form"><input id="user" placeholder="user"><button id="submit" type="button">Sign in</button></form>'
                                       '<a class="login" id="to-list" href="list.html">Continue</a></body></html>')
    rows = ''.join(f'<li class="row">Item {i}</li>' for i in range(ROWS)) + '<li class="row" id="end">End</li>'
    (folder / 'list.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>Legacy List</title><style>' + STYLE + '</style></head>'
                                      '<body><h1 id="heading">Items</h1><ul id="list" aria-label="items">' + rows + '</ul></body></html>')
    import struct, zlib
    raw = b''.join(b'\x00' + bytes((30, 90, 200)) * 120 for _ in range(20))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    (folder / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 120, 20, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def main():
    keep = '--keep' in sys.argv
    base = Path(tempfile.mkdtemp(prefix='sdd-browser-smoke-')).resolve()  # managed paths never pass through a symlink
    try:
        site = base / 'site'; site.mkdir(); write_site(site)
        url = (site / 'index.html').resolve().as_uri()
        root = base / '.sdd-runs/run-1'; (root / 'context').mkdir(parents=True)
        statement = root / 'context/legacy-preview.json'
        statement.write_text(json.dumps({'effective_config': {'legacy_preview': {'kind': 'browser', 'url': url}}, 'source_refs': {}}))
        state = {'run_id': 'run-1', 'project_context_ref': file_ref(statement), 'modules': {}}
        task = {'role': 'spec-designer', 'assignment_id': 'A1', 'fencing_token': 'fence-1'}
        actor = {'role': 'spec-designer', 'instance_id': 'spec-1', 'device_lock': {'held': True, 'device_id': url, 'assignment_id': 'A1', 'fencing_token': 'fence-1'}}
        out = root / 'runs/harmony/sandbox/spec-1/attempt-1'; out.mkdir(parents=True)
        targets = [{'coverage': 'login:base:viewport', 'target_match': [{'resource-id': 'title', 'text': 'Sign in'}]},
                   {'coverage': 'list:base:scroll', 'actions': [{'action': 'click', 'selector': 'a.login'}], 'target_match': [{'resource-id': 'list'}],
                    'scroll_region': {'resource-id': 'list'}, 'scroll_end_match': [{'text': 'End'}], 'max_scrolls': 12}]
        started = time.time()
        result = worker.legacy_capture({'targets': targets}, root=root, out=out, state=state, task=task, actor=actor, module_id='M001')
        summary = {'status': result['status'], 'captured': result.get('captured'), 'blocked': result.get('blocked') or result.get('root_cause')}
        if result['status'] != 'CAPTURED':
            print(json.dumps(summary, ensure_ascii=False)); return 1
        scroll = ui_evidence.capture_target(result['manifest_ref'], 'list:base:scroll')
        summary['scroll'] = scroll['coverage']
        analysis = lean_worker.web_analysis({'platform': 'web', 'capture_ref': result['manifest_ref'], 'targets': [t['coverage'] for t in targets]}, 'M001', out / 'analysis')
        tree = read_json(analysis['ui_tree_ref']['path'])
        ui_evidence.validate_tree_ref(analysis['ui_tree_ref'], runtime_index_ref=analysis['runtime_index_ref'])
        manifest = read_json(result['manifest_ref']['path'])
        for target in targets:
            evidence = lean_adapter.ui_evidence(manifest, analysis['ui_tree_ref'], target=target['coverage'], capture_ref=result['manifest_ref'],
                                                runtime_index_ref=analysis['runtime_index_ref'])
            semantics._ui_evidence({'ui_evidence': evidence})
            summary.setdefault('baselines', {})[target['coverage']] = len(evidence['baseline_refs'])
        summary.update(screens=[s['id'] for s in tree['screens']], image_sources=len(tree['imageSources']),
                       login_nodes=len(ui_evidence.target_node_ids(tree, 'login', 'base')), seconds=round(time.time() - started, 1), out=str(out) if keep else None)
        ok = summary['scroll']['achieved'] == 'scroll-complete' and summary['screens'] == ['screen:login.base', 'screen:list.base'] and summary['image_sources'] == 1
        print(json.dumps(summary, ensure_ascii=False)); return 0 if ok else 1
    finally:
        if not keep:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
