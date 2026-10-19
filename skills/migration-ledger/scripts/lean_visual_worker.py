"""Bounded device capture and semantic comparison for a current SDD test assignment.

Only lean_worker calls this module after authentication/phase/plan checks. Host supplies a
live device-lock attestation; this is not a device lock service or an OS sandbox. No Ledger
events, acceptance, repair loop, arbitrary shell, implicit configuration or output directory.
"""
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import zipfile

from contracts import check_ref, digest, file_ref, read_json, require
import run_storage
import runner_storage
import image_parity
import ui_evidence
import ui_fidelity
import visual_evidence
from lean_tools import mobile_snapshot, semantic_visual_inspect, validate_manifest

OPERATIONS = {'visual-install', 'visual-capture', 'semantic-inspect'}
ADB_KINDS = ('android-device', 'android-emulator', 'vm')  # legacy_preview kinds an adb serial reaches


def save(path, value):
    run_storage.atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())
    return file_ref(path)


def blocked(reason, kind='environment-unavailable', **extra):
    return {'status': 'BLOCKED', 'quality_candidate': 'yellow-blocked', 'executed': False,
            'root_cause': {'kind': kind, 'reason': reason}, 'acceptance': 'staged-evidence-only', **extra}


def failed(reason, kind, **extra):
    """An observed defect of the candidate itself: evidence for a Red, never an environment gap."""
    return {'status': 'FAILED', 'quality_candidate': 'red-bug', 'executed': True,
            'root_cause': {'kind': kind, 'reason': reason}, 'acceptance': 'staged-evidence-only', **extra}


def token(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value),
            label + ' must be a safe nonempty identifier')
    return value


class DeviceFailure(RuntimeError):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def image_valid(path, formats=('PNG', 'JPEG')):
    try:
        from PIL import Image
    except ImportError as exc:
        raise DeviceFailure('environment-unavailable', 'Pillow is required to decode screenshot evidence') from exc
    try:
        with Image.open(path) as image:
            if image.format not in formats:
                raise ValueError('unsupported screenshot format')
            image.verify()
        with Image.open(path) as image:
            image.load()
    except Exception as exc:
        raise DeviceFailure('capture-incomplete', 'screenshot could not be decoded and verified') from exc


def hap_identity(artifact):
    try:
        with zipfile.ZipFile(artifact) as archive:
            for name in ('module.json', 'pack.info'):
                if name not in archive.namelist():
                    continue
                if archive.getinfo(name).file_size > 1024 * 1024:
                    continue
                data = json.loads(archive.read(name))
                if not isinstance(data, dict):
                    continue
                summary = data.get('summary') if isinstance(data.get('summary'), dict) else {}
                app = data.get('app') if name == 'module.json' else summary.get('app')
                if not isinstance(app, dict):
                    continue
                version = app.get('version') if isinstance(app.get('version'), dict) else {}
                code = app.get('versionCode', version.get('code'))
                if app.get('bundleName') and isinstance(code, (str, int)) and not isinstance(code, bool):
                    return {'bundleName': app['bundleName'], 'versionCode': str(code),
                            'versionName': app.get('versionName', version.get('name')), 'metadata_member': name}
    except (OSError, ValueError, TypeError, zipfile.BadZipFile):
        pass
    raise DeviceFailure('artifact-identity-unverified', 'accepted HAP lacks readable app bundle/version metadata')


def installed_identity(output, expected):
    if not isinstance(expected, dict) or not expected.get('bundleName') or not expected.get('versionCode'):
        return False
    try:
        start, end = output.index('{'), output.rindex('}') + 1
        data = json.loads(output[start:end])
    except (ValueError, TypeError):
        return False
    def walk(value):
        if isinstance(value, dict):
            if value.get('bundleName') == expected['bundleName'] and \
                    str(value.get('versionCode')) == expected['versionCode'] and \
                    (expected.get('versionName') is None or value.get('versionName') == expected['versionName']):
                return True
            return any(walk(child) for child in value.values())
        return isinstance(value, list) and any(walk(child) for child in value)
    return walk(data)


class Device:
    """Fixed HDC argv; remote file deletion is limited to this attempt's generated files."""
    platform, backend, image_mime = 'harmony', 'hdc', 'image/jpeg'

    def __init__(self, settings, out):
        require(settings.get('backend') == 'hdc', 'visual capture requires explicitly configured hdc backend')
        self.tool = settings.get('tool', 'hdc')
        require(isinstance(self.tool, str) and Path(self.tool).name == 'hdc', 'configured executable must be hdc')
        self.device = token(settings.get('device_id'), 'device_id')
        self.out = out
        self.logs = []
        self.remote_files = []
        self.version = None
        self.page_name, self.last_dump = '', ''

    def call(self, *args, timeout=30):
        argv = [self.tool, '-t', self.device, *map(str, args)]
        # Only read-only state queries are retried once on a transient timeout; actions never repeat.
        attempts = 2 if tuple(map(str, args[:3])) in (('shell', 'aa', 'dump'), ('shell', 'bm', 'dump')) else 1
        for attempt in range(attempts):
            try:
                result = subprocess.run(argv, cwd=self.out, env=runner_storage.environment(self.out),
                                        capture_output=True, text=True, errors='replace', timeout=timeout)
                break
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                self.logs.append({'argv': argv, 'error': type(exc).__name__, 'attempt': attempt + 1})
                if isinstance(exc, FileNotFoundError) or attempt + 1 == attempts:
                    raise DeviceFailure('environment-unavailable', type(exc).__name__) from exc
        self.logs.append({'argv': argv, 'exit_code': result.returncode,
                          'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise DeviceFailure('device-execution-error', f'command {args[0]} exited {result.returncode}; see command log')
        return result.stdout

    def foreground(self):
        """(bundle, page) in front, from aa dump; the dump is kept to tell an app that exited from one sent to the background."""
        self.last_dump = self.call('shell', 'aa', 'dump', '-l')
        return foreground_app(self.last_dump), self.page_name

    def running(self, app):
        return app_running(self.last_dump, app)

    def layout(self, label):
        output = self.call('shell', 'uitest', 'dumpLayout')
        match = re.search(r'saved to:\s*(/data/local/tmp/[A-Za-z0-9_.-]+\.json)', output)
        if not match:
            raise DeviceFailure('device-execution-error', 'cannot parse managed dumpLayout path')
        remote = match.group(1)
        self.remote_files.append(remote)
        local = run_storage.checked_path(self.out / 'temp' / f'layout-{label}.json', self.out)
        local.parent.mkdir(parents=True, exist_ok=True)
        self.call('file', 'recv', remote, local)
        raw = read_json(local)
        node = mobile_snapshot.harmony_node(raw)
        if node is None:
            raise DeviceFailure('target-precondition', 'layout contains no application nodes')
        self.page_name = mobile_snapshot.harmony_page_name(raw)
        return ET.tostring(node, encoding='unicode')

    def scroll(self, bounds):
        """One bounded swipe up inside the frozen scroll region."""
        x1, y1, x2, y2 = bounds
        self.call('shell', 'uitest', 'uiInput', 'swipe', (x1 + x2) // 2, y1 + (y2 - y1) * 3 // 4, (x1 + x2) // 2, y1 + (y2 - y1) // 4, 1000)

    def screenshot(self, label):
        nonce = digest(str(self.out))[:20]
        remote = f'/data/local/tmp/sdd-{nonce}-{label}.jpeg'
        self.remote_files.append(remote)
        self.call('shell', 'snapshot_display', '-f', remote)
        local = run_storage.checked_path(self.out / f'screenshot-{label}.jpeg', self.out)
        self.call('file', 'recv', remote, local)
        if not local.is_file() or not local.stat().st_size:
            raise DeviceFailure('capture-incomplete', 'device screenshot is missing or empty')
        image_valid(local, ('JPEG',))
        return local

    def finish(self):
        cleanup = []
        for remote in dict.fromkeys(self.remote_files):
            try:
                self.call('shell', 'rm', remote)
                cleanup.append({'path': remote, 'status': 'removed'})
            except DeviceFailure as exc:
                cleanup.append({'path': remote, 'status': 'retained-on-device', 'reason': str(exc)})
        return {'command_log_ref': save(self.out / 'commands.json', self.logs),
                'remote_cleanup_ref': save(self.out / 'remote-cleanup.json', cleanup)}


class AndroidDevice:
    """Fixed adb argv for the legacy application: install, launch, dump, screenshot; no arbitrary shell."""
    platform, backend, image_mime = 'android', 'adb', 'image/png'

    def __init__(self, serial, tool, out):
        require(isinstance(tool, str) and Path(tool).name == 'adb', 'configured executable must be adb')
        self.tool, self.device, self.out = tool, token(serial, 'serial'), out
        self.logs, self.remote_files, self.version = [], [], None
        self.nonce = digest(str(out))[:20]

    def call(self, *args, timeout=30):
        argv = [self.tool, '-s', self.device, *map(str, args)]
        attempts = 2 if tuple(map(str, args[:2])) == ('shell', 'dumpsys') else 1  # read-only queries retry once; actions never repeat
        for attempt in range(attempts):
            try:
                result = subprocess.run(argv, cwd=self.out, env=runner_storage.environment(self.out),
                                        capture_output=True, text=True, errors='replace', timeout=timeout)
                break
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                self.logs.append({'argv': argv, 'error': type(exc).__name__, 'attempt': attempt + 1})
                if isinstance(exc, FileNotFoundError) or attempt + 1 == attempts:
                    raise DeviceFailure('environment-unavailable', type(exc).__name__) from exc
        self.logs.append({'argv': argv, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise DeviceFailure('device-execution-error', f'command {args[0]} exited {result.returncode}; see command log')
        return result.stdout

    def foreground(self):
        """(package, activity) of the focused window, from dumpsys."""
        output = self.call('shell', 'dumpsys', 'window')
        match = re.search(r'mCurrentFocus=Window\{[^}]*?\s([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)\}', output)
        return (match.group(1), match.group(2)) if match else (None, None)

    def layout(self, label):
        remote = f'/sdcard/sdd-{self.nonce}-{label}.xml'
        self.remote_files.append(remote)
        self.call('shell', 'uiautomator', 'dump', remote)
        local = run_storage.checked_path(self.out / 'temp' / f'layout-{label}.xml', self.out)
        local.parent.mkdir(parents=True, exist_ok=True)
        self.call('pull', remote, local)
        xml = local.read_text(encoding='utf-8', errors='replace')
        try:
            ET.fromstring(xml)
        except ET.ParseError as exc:
            raise DeviceFailure('device-execution-error', 'uiautomator dump is not parseable XML') from exc
        return xml

    def scroll(self, bounds):
        """One bounded swipe up inside the frozen scroll region."""
        x1, y1, x2, y2 = bounds
        self.call('shell', 'input', 'swipe', (x1 + x2) // 2, y1 + (y2 - y1) * 3 // 4, (x1 + x2) // 2, y1 + (y2 - y1) // 4, 1000)

    def screenshot(self, label):
        remote = f'/sdcard/sdd-{self.nonce}-{label}.png'
        self.remote_files.append(remote)
        self.call('shell', 'screencap', '-p', remote)
        local = run_storage.checked_path(self.out / f'screenshot-{label}.png', self.out)
        self.call('pull', remote, local)
        if not local.is_file() or not local.stat().st_size:
            raise DeviceFailure('capture-incomplete', 'device screenshot is missing or empty')
        image_valid(local, ('PNG',))
        return local

    def finish(self):
        cleanup = []
        for remote in dict.fromkeys(self.remote_files):
            try:
                self.call('shell', 'rm', remote)
                cleanup.append({'path': remote, 'status': 'removed'})
            except DeviceFailure as exc:
                cleanup.append({'path': remote, 'status': 'retained-on-device', 'reason': str(exc)})
        return {'command_log_ref': save(self.out / 'commands.json', self.logs),
                'remote_cleanup_ref': save(self.out / 'remote-cleanup.json', cleanup)}


def dom_to_xml(node):
    """A DOM snapshot as the view tree the selectors, signatures and indices already read: one <node> per element."""
    def element(item):
        x1, y1, x2, y2 = [int(v) for v in (item.get('bounds') or [0, 0, 0, 0])]
        el = ET.Element('node', {'class': ' '.join(part for part in (item.get('tag') or '', item.get('cls') or '') if part),
                                 'resource-id': item.get('id') or '', 'text': item.get('text') or '', 'content-desc': item.get('aria') or '',
                                 'bounds': f'[{x1},{y1}][{x2},{y2}]', 'package': '', 'scrollable': 'true' if item.get('scrollable') else 'false',
                                 'image-src': item.get('src') or ''})
        for child in item.get('children') or []:
            el.append(element(child))
        return el
    root = ET.Element('hierarchy', {'rotation': '0'})
    root.append(element(node))
    return ET.tostring(root, encoding='unicode')


DOM_WALK = """() => { const vw = window.innerWidth, vh = window.innerHeight;
  const inter = (a, b) => ({l: Math.max(a.l, b.l), t: Math.max(a.t, b.t), r: Math.min(a.r, b.r), b: Math.min(a.b, b.b)});
  const clips = ['auto', 'scroll', 'hidden', 'clip'];
  const scroller = document.scrollingElement || document.documentElement;
  const pageScrolls = scroller.scrollHeight > vh + 1;  // the page itself scrolls: its body is the scroll region
  const walk = (el, clip, dx, dy) => { const r = el.getBoundingClientRect(); const style = getComputedStyle(el);
    const own = {l: r.left + dx, t: r.top + dy, r: r.right + dx, b: r.bottom + dy}; const box = inter(own, clip);
    const shown = box.r > box.l && box.b > box.t && style.visibility !== 'hidden' && style.display !== 'none';
    const childClip = clips.includes(style.overflowY) || clips.includes(style.overflowX) ? inter(clip, own) : clip;
    let kids = [];
    if (el.tagName === 'IFRAME') { let doc = null; try { doc = el.contentDocument; } catch (e) { doc = null; }  // a same-origin frame is part of the screen
      if (doc && doc.body) kids = [walk(doc.body, inter(clip, own), own.l, own.t)]; }
    else { const shadow = el.shadowRoot ? Array.from(el.shadowRoot.children) : [];  // a component's shadow tree is on the screen too
      kids = shadow.concat(Array.from(el.children)).map((c) => walk(c, childClip, dx, dy)); }
    const children = kids.filter(Boolean);
    if (!shown && children.length === 0) return null;  // like a native dump: what is clipped away is not on the screen
    const field = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
    const text = field ? (el.value || el.placeholder || '') : (el.childElementCount === 0 && !el.shadowRoot ? (el.innerText || el.textContent || '').trim().slice(0, 200) : '');
    const scrollable = (el.scrollHeight > el.clientHeight + 1 && ['auto', 'scroll'].includes(style.overflowY)) || (pageScrolls && dx === 0 && dy === 0 && (el === document.body || el === scroller));
    return { tag: el.tagName.toLowerCase(), id: el.id || '', cls: typeof el.className === 'string' ? el.className : '', text,
      aria: el.getAttribute('aria-label') || el.getAttribute('alt') || '', src: el.getAttribute('src') || '',
      bounds: [Math.round(box.l), Math.round(box.t), Math.round(Math.max(box.r, box.l)), Math.round(Math.max(box.b, box.t))], scrollable, children }; };
  return walk(document.body, {l: 0, t: 0, r: vw, b: vh}, 0, 0); }"""


def open_browser(out, viewport=None):
    """A headless Chromium page through Playwright; the host installs the browser, the worker only drives it."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DeviceFailure('environment-unavailable', 'Playwright is required for browser capture') from exc

    class PlaywrightPage:
        def __init__(self):
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch()
            self.page = self.browser.new_page(**({'viewport': dict(viewport)} if viewport else {}))
            self.version = 'chromium ' + self.browser.version

        def goto(self, url): self.page.goto(url, wait_until='load'); self.settle(True)
        def click(self, selector): self.page.click(selector, timeout=10000); self.settle(True)
        def back(self): self.page.go_back(wait_until='load'); self.settle(True)

        def settle(self, network=False):
            """A navigation, a click or a wheel returns before the page is done: wait for the network to go quiet and for three
            DOM reads in a row to agree, bounded, so the tree read next is the screen that stays."""
            if network:
                try:
                    self.page.wait_for_load_state('networkidle', timeout=2000)
                except Exception:
                    pass
            last, same = None, 0
            for _ in range(50):
                current = self.page.evaluate(DOM_WALK)
                same = same + 1 if current == last else 0
                if same >= 2:
                    return
                last = current; self.page.wait_for_timeout(100)
        def title(self): return self.page.title()
        def dom(self): return self.page.evaluate(DOM_WALK)
        def screenshot(self, path): self.page.screenshot(path=str(path))

        def wheel(self, x, y, dy):
            self.page.mouse.move(x, y); self.page.mouse.wheel(0, dy); self.settle()

        def wait(self, ms): self.page.wait_for_timeout(ms)

        def identity(self):
            """The build the served page declares: <meta name="sdd-build" content="<artifact sha256>">, written by the deploy step."""
            return self.page.evaluate("() => { const m = document.querySelector('meta[name=\"sdd-build\"]'); return m ? (m.getAttribute('content') || '') : ''; }")

        def close(self):
            self.browser.close(); self.playwright.stop()
    return PlaywrightPage()


class BrowserDevice:
    """The legacy web application in a browser: the url is the device, the DOM is the view tree, the page is the screen."""
    platform, backend, image_mime = 'web', 'playwright', 'image/png'
    match_retries = 10  # a view rendered by script after a click: the frozen selectors are read again, read-only, for a bounded while

    def __init__(self, url, out, page=None, viewport=None):
        self.url, self.out, self.logs = url, out, []
        self.device = urlparse(url).netloc or url
        self.page = page or open_browser(out, viewport)
        self.version = getattr(self.page, 'version', None) or 'playwright'
        self.tool = 'playwright'

    def act(self, name, *args):
        self.logs.append({'action': name, 'argv': ['browser', name, *[str(a) for a in args]], 'exit_code': 0})
        try:
            return getattr(self.page, name)(*args)
        except Exception as exc:  # the browser's own error: an environment fact, not a verdict
            self.logs[-1].update(exit_code=1, error=type(exc).__name__)
            raise DeviceFailure('device-execution-error', f'browser {name} failed; see command log') from exc

    def foreground(self):
        return self.device, str(self.act('title') or '')

    def wait(self, ms):
        self.act('wait', ms)

    def scroll(self, bounds):
        """One wheel turn of half the frozen region's height, at its centre."""
        x1, y1, x2, y2 = bounds
        self.act('wheel', (x1 + x2) // 2, (y1 + y2) // 2, max(1, (y2 - y1) // 2))

    def layout(self, label):
        xml = dom_to_xml(self.act('dom'))
        local = run_storage.checked_path(self.out / 'temp' / f'layout-{label}.xml', self.out)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(xml, encoding='utf-8')
        return xml

    def screenshot(self, label):
        local = run_storage.checked_path(self.out / f'screenshot-{label}.png', self.out)
        self.act('screenshot', local)
        if not local.is_file() or not local.stat().st_size:
            raise DeviceFailure('capture-incomplete', 'browser screenshot is missing or empty')
        image_valid(local, ('PNG',))
        return local

    def finish(self):
        try:
            self.page.close()
        except Exception:
            pass
        return {'command_log_ref': save(self.out / 'commands.json', self.logs)}


def web_actions(device, actions):
    require(isinstance(actions, list) and len(actions) <= 30, 'at most 30 frozen navigation actions')
    for action in actions:
        require(isinstance(action, dict), 'action must be an object')
        kind = action.get('action')
        if kind == 'back':
            device.act('back')
        elif kind == 'click':
            selector = action.get('selector')
            require(isinstance(selector, str) and 0 < len(selector) <= 200, 'click names a CSS selector')
            device.act('click', selector)
        else:
            require(False, 'unsupported navigation action; no arbitrary script execution')


def capture_web_target(device, stated, target, spec, out):
    """One legacy web screen as a legacy-reference record of platform web: navigated from the url by frozen clicks, matched by
    selectors on the DOM tree, captured with a stable tree around the screenshot. Viewport targets only."""
    label = re.sub(r'[^A-Za-z0-9_.-]+', '-', target['page_id'] + '-' + target['state_id'])
    if spec.get('navigation') is not None:
        return blocked('agent navigation needs an adb device statement; a browser walks frozen clicks')
    device.act('goto', stated['url'])
    web_actions(device, spec.get('actions', []))
    observed = observe_screen(device, device.device, target, spec, out, label)  # the host is the app; the title is the page
    if 'captures' not in observed:
        return observed
    meta = {**observed['meta'], 'app_id': stated['url'], 'legacy_preview': stated['kind']}
    meta_ref = save(out / f'meta-{label}.json', meta)
    captures, coverage = observed['captures'], observed['coverage']
    snapshot = {**captures[0], 'meta': meta_ref['path'], 'device_backend': observed['backend'], 'coverage': coverage, 'captures': captures}
    if not observed['complete']:
        return blocked('bounded scroll observations do not prove full scroll coverage', 'capture-incomplete', meta_ref=meta_ref)
    return {'status': 'COMPLETE', 'record': {'mode': 'targeted', 'phase': 'legacy-reference', 'platform': 'web',
            'page_id': target['page_id'], 'state_id': target['state_id'], 'observed_variant': target['state_id'], 'round': None,
            'status': 'COMPLETE', 'coverage': coverage, 'timestamp': datetime.now(timezone.utc).isoformat(), 'snapshot': snapshot,
            'target_match': {'kind': 'frozen-exact-selectors', 'matched': True}}}


def android_actions(device, actions):
    require(isinstance(actions, list) and len(actions) <= 30, 'at most 30 frozen navigation actions')
    for action in actions:
        require(isinstance(action, dict), 'action must be an object')
        kind = action.get('action')
        if kind == 'back':
            device.call('shell', 'input', 'keyevent', 'KEYCODE_BACK')
        elif kind in ('tap', 'swipe'):
            keys = ('x', 'y') if kind == 'tap' else ('x1', 'y1', 'x2', 'y2', 'velocity')
            values = [action.get(k) for k in keys]
            require(all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 40000 for v in values),
                    'frozen action coordinates/velocity must be bounded integers')
            device.call('shell', 'input', 'tap' if kind == 'tap' else 'swipe', *values)
        else:
            require(False, 'unsupported navigation action; no arbitrary shell, text, or script execution')


def android_identity(device, app, expected_sha256):
    """The installed package is the accepted APK byte for byte: adb reports its path, the device hashes it."""
    installed = device.call('shell', 'pm', 'path', app)
    match = re.search(r'package:(\S+)', installed)
    if not match:
        raise DeviceFailure('artifact-identity-unverified', 'the candidate package is not installed under its app_id')
    digest_line = device.call('shell', 'sha256sum', match.group(1)).strip().split()
    if not digest_line or digest_line[0].lower() != expected_sha256:
        raise DeviceFailure('artifact-identity-unverified', 'installed package bytes differ from the accepted APK')
    return {'package': app, 'sha256': expected_sha256, 'device_path': match.group(1), 'installed': installed}


def observe_screen(device, app, target, spec, out, label):
    """The frozen target on the screen of an adb device or a browser: foreground checked, selectors matched, each screen captured
    with a stable tree around the screenshot, a scroll bounded by its frozen region and end. Returns the observation or a blocked result."""
    package, activity = device.foreground()
    if package != app:
        return not_in_front(device, app, 'before capture')
    xml = device.layout(f'{label}-0')
    for _ in range(getattr(device, 'match_retries', 0)):  # read-only: a screen still rendering is read again, an action is never repeated
        if target_matches(xml, spec.get('target_match'), app):
            break
        device.wait(300); xml = device.layout(f'{label}-0')
    if not target_matches(xml, spec.get('target_match'), app):
        save(out / f'target-mismatch-{label}.json', {'foreground': f'{package}/{activity}', 'view_xml': xml})
        return blocked('frozen target selectors not observed', 'target-precondition')
    region, region_bounds = scoped_scroll_region(xml, spec.get('scroll_region'), app)
    end_match = spec.get('scroll_end_match')
    if end_match:
        target_matches(xml, end_match, app)
    max_scrolls = spec.get('max_scrolls', 8)
    require(isinstance(max_scrolls, int) and not isinstance(max_scrolls, bool) and 0 <= max_scrolls <= 20, 'max_scrolls must be 0..20')
    scroll = target['coverage'] == 'scroll'
    termination = ('viewport' if not scroll else 'missing-frozen-scroll-region-or-endpoint' if not region_bounds or not end_match else 'scroll-limit')
    captures, current_xml = [], xml
    for index in range(1 + (max_scrolls if termination == 'scroll-limit' else 0)):
        if index:
            device.scroll(region_bounds)
            current_xml = device.layout(f'{label}-{index}')
        package, activity = device.foreground()
        if package != app:
            return not_in_front(device, app, 'during capture')
        image_path = device.screenshot(f'{label}-{index}')
        view = out / f'view-{label}-{index}.xml'
        run_storage.atomic_bytes(view, current_xml.encode())
        signature = mobile_snapshot.view_signature(current_xml, f'{package}/{activity}')
        after_xml = device.layout(f'{label}-{index}-after')
        if after_xml != current_xml:
            after_view = out / f'view-{label}-{index}-after.xml'
            run_storage.atomic_bytes(after_view, after_xml.encode())
            return blocked('page/state changed while screenshot was taken; retain both trees and recapture a new attempt',
                           'capture-incomplete', screenshot_ref=file_ref(image_path), before_view_ref=file_ref(view), after_view_ref=file_ref(after_view))
        record = {'index': index, 'screenshot': str(image_path), 'view_tree': str(view), 'view_signature': signature}
        region, region_bounds = scoped_scroll_region(current_xml, spec.get('scroll_region'), app)
        if scroll and region_bounds and end_match and target_matches(ET.tostring(region, encoding='unicode'), end_match, app):
            captures.append(record); termination = 'frozen-scroll-end-observed'
            break
        if index and signature == captures[-1]['view_signature'] and file_ref(image_path)['sha256'] == file_ref(captures[-1]['screenshot'])['sha256']:
            termination = 'observed-repeat-not-proof-of-end'
            break
        captures.append(record)
        if index and not region_bounds:
            termination = 'frozen-scroll-region-lost'
            break
    complete = not scroll or termination == 'frozen-scroll-end-observed'
    coverage = {'requested': target['coverage'], 'achieved': 'viewport' if not scroll else 'scroll-complete' if complete else 'scroll-partial',
                'capture_count': len(captures), 'termination': termination}
    backend = {'name': device.backend, 'implementation': device.tool, 'version': device.version, 'device': device.device}
    meta = {'platform': device.platform, 'device': device.device, 'app_id': app, 'foreground': f'{package}/{activity}', 'page_name': activity,
            'image_mime': getattr(device, 'image_mime', 'image/png'), 'screenshot': Path(captures[0]['screenshot']).name, 'view_signature': captures[0]['view_signature'],
            'device_backend': backend, 'coverage': coverage, 'captures': captures, 'target_match': spec['target_match']}
    if scroll:
        meta.update(scroll_region=spec.get('scroll_region'), scroll_end_match=end_match, scroll_contract='frozen-source-backed-start-region-end')
    return {'captures': captures, 'coverage': coverage, 'complete': complete, 'backend': backend, 'meta': meta}


def install_legacy(device, stated, app, out):
    """The package the run was prepared with (or the one its build command produces) goes on the device; the install is evidence."""
    build_log = None
    if stated.get('build'):
        build = stated['build']
        try:
            run = subprocess.run(build['argv'], cwd=build['cwd'], env=runner_storage.environment(out), capture_output=True,
                                 text=True, errors='replace', timeout=build['timeout_seconds'])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise DeviceFailure('environment-unavailable', 'legacy build ' + type(exc).__name__) from exc
        build_log = save(out / 'build.json', {'argv': build['argv'], 'cwd': build['cwd'], 'exit_code': run.returncode,
                                              'stdout': run.stdout[-20000:], 'stderr': run.stderr[-20000:]})
        if run.returncode:
            raise DeviceFailure('environment-unavailable', 'legacy build failed; see build log')
        artifact = Path(build['output'])
        if not artifact.is_file():
            raise DeviceFailure('environment-unavailable', 'legacy build produced no package at its stated output')
    else:
        artifact = Path(stated['artifact'])
        if not artifact.is_file() or file_ref(artifact)['sha256'] != stated.get('artifact_sha256'):
            raise DeviceFailure('artifact-identity-unverified', 'the legacy package differs from the one the run was prepared with')
    device.call('install', '-r', artifact, timeout=240)
    installed = device.call('shell', 'pm', 'path', app)
    if 'package:' not in installed:
        raise DeviceFailure('artifact-identity-unverified', 'the legacy package is not installed under its app_id')
    return save(out / 'install.json', {'producer': 'lean-visual-worker', 'operation': 'legacy-install', 'status': 'INSTALLED',
                                       'artifact_ref': file_ref(artifact), 'app_id': app, 'device_id': device.device,
                                       'installed': installed, 'build_log_ref': build_log,
                                       'acceptance': 'installation-is-evidence-not-a-baseline'})


def agent_navigate(stated, device, app, target, spec, out, run_id, module_id, label):
    """The navigator the run states (the adapter's snapshot task) walks the frozen step texts to the screen; the worker still
    matches the frozen selectors and captures afterwards. A walk that did not reach the screen is a capture_gap suggestion."""
    navigation = spec['navigation']
    require(isinstance(navigation, dict) and navigation.get('mode') == 'agent' and isinstance(navigation.get('steps'), list)
            and 1 <= len(navigation['steps']) <= 30 and all(isinstance(s, str) and s.strip() for s in navigation['steps']),
            'navigation takes mode agent and 1..30 frozen step texts')
    navigator = stated.get('navigator')
    if not navigator:
        return blocked('legacy_preview.navigator is not configured: agent navigation needs the adapter that walks a snapshot task')
    folder = out / f'navigation-{label}'; folder.mkdir(parents=True, exist_ok=True)
    query = {'run_id': run_id, 'module_id': module_id, 'capture_id': spec['coverage'], 'name': 'legacy ' + target['page_id'] + ':' + target['state_id'],
             'platform': 'android', 'task_type': 'snapshot', 'steps': navigation['steps'],
             'preconditions': ['the legacy application ' + app + ' is installed and launched on ' + device.device],
             'parameters': {'device_id': device.device, 'app_id': app}}
    query_ref = save(folder / 'query.json', query); result_path = folder / 'result.json'
    argv = [*navigator['argv'], '--query-file', query_ref['path'], '--result-file', str(result_path)]
    try:
        run = subprocess.run(argv, cwd=navigator['cwd'], env=runner_storage.environment(out), capture_output=True,
                             text=True, errors='replace', timeout=navigator['timeout_seconds'])
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise DeviceFailure('environment-unavailable', 'legacy navigator ' + type(exc).__name__) from exc
    save(folder / 'navigator.json', {'argv': argv, 'exit_code': run.returncode, 'stdout': run.stdout[-20000:], 'stderr': run.stderr[-20000:]})
    try:
        report = read_json(result_path)
    except (OSError, ValueError) as exc:
        raise DeviceFailure('environment-unavailable', 'legacy navigator wrote no readable result') from exc
    status = report.get('status') if report.get('task_type') == 'snapshot' else None
    receipt = {'mode': 'agent', 'steps': navigation['steps'], 'status': status, 'reason': report.get('reason'),
               'query_ref': query_ref, 'result_ref': file_ref(result_path)}
    if status != 'reached':
        reason = 'agent navigation ' + (status or 'unreadable') + (': ' + str(report['reason']) if report.get('reason') else '')
        return blocked(reason, 'navigation-unverified', navigation=receipt, capture_gap={'reason': reason, 'evidence_refs': [receipt['result_ref']]})
    return {'status': 'REACHED', 'navigation': receipt}


def capture_legacy_target(device, stated, app, target, spec, out, run_id=None, module_id=None):
    """One legacy screen as an android-reference record: launched, navigated by frozen actions or the stated navigator, matched, captured stable."""
    label = re.sub(r'[^A-Za-z0-9_.-]+', '-', target['page_id'] + '-' + target['state_id'])
    launch = stated.get('launch')
    if launch:
        require(re.fullmatch(r'[A-Za-z0-9_.$]+', launch), 'legacy_preview.launch must be an activity name')
        device.call('shell', 'am', 'start', '-n', app + '/' + launch)
    else:
        device.call('shell', 'monkey', '-p', app, '-c', 'android.intent.category.LAUNCHER', '1')
    navigation = None
    if spec.get('navigation') is not None:
        outcome = agent_navigate(stated, device, app, target, spec, out, run_id, module_id, label)
        if outcome['status'] != 'REACHED':
            return outcome
        navigation = outcome['navigation']
    android_actions(device, spec.get('actions', []))
    observed = observe_screen(device, app, target, spec, out, label)
    if 'captures' not in observed:
        return observed
    meta = {**observed['meta'], 'legacy_preview': stated['kind'], 'artifact_sha256': stated.get('artifact_sha256'), **({'navigation': navigation} if navigation else {})}
    meta_ref = save(out / f'meta-{label}.json', meta)
    captures, coverage = observed['captures'], observed['coverage']
    snapshot = {**captures[0], 'meta': meta_ref['path'], 'device_backend': observed['backend'], 'coverage': coverage, 'captures': captures}
    if not observed['complete']:
        return blocked('bounded scroll observations do not prove full scroll coverage', 'capture-incomplete', meta_ref=meta_ref)
    return {'status': 'COMPLETE', 'record': {'mode': 'targeted', 'phase': 'android-reference', 'platform': 'android',
            'page_id': target['page_id'], 'state_id': target['state_id'], 'observed_variant': target['state_id'], 'round': None,
            'status': 'COMPLETE', 'coverage': coverage, 'timestamp': datetime.now(timezone.utc).isoformat(), 'snapshot': snapshot,
            'target_match': {'kind': 'frozen-exact-selectors', 'matched': True}}}


def legacy_capture(args, *, root, out, state, task, actor, module_id=None):
    """The legacy application's screens as android-reference records: installed from the package the run was prepared with,
    walked by frozen actions on the stated device, captured stable. The manifest is what analyze-ui and the SPEC's runtime
    evidence stand on; a screen that could not be captured is named with its reason, never invented."""
    import project_context
    require(actor.get('role') in ('spec-designer', 'test-runner'), 'legacy capture outside role')
    stated = project_context.legacy_preview(state)
    require(stated and stated['kind'] in (*ADB_KINDS, 'browser'),
            'legacy_preview must state an adb-visible provider (android-device, android-emulator or vm) or a browser url before the legacy is captured')
    root, out = Path(root).resolve(), Path(out).resolve()
    runner_storage.harmony_output(root, out, 'sandbox')
    run_id = state.get('run_id') or root.name
    targets = args.get('targets')
    require(isinstance(targets, list) and 1 <= len(targets) <= 20 and all(isinstance(t, dict) and isinstance(t.get('coverage'), str) for t in targets),
            'legacy-capture takes 1..20 targets, each naming its page:state:coverage')
    try:
        parsed = [validate_manifest.parse_target(t['coverage']) for t in targets]
    except RuntimeError as exc:
        require(False, 'legacy-capture target: ' + str(exc))
    require(len({(p['page_id'], p['state_id']) for p in parsed}) == len(parsed), 'one record per page:state')
    web = stated['kind'] == 'browser'
    device_lock(actor, {'device_id': stated['url'] if web else stated['device']['serial']}, task)
    app = stated['url'] if web else token(stated['app_id'], 'app_id')
    result, install_ref, records, blocked_targets, device = None, None, [], [], None
    try:
        device = BrowserDevice(stated['url'], out, viewport=stated.get('viewport')) if web else AndroidDevice(stated['device']['serial'], args.get('tool', 'adb'), out)
        if not web:
            device.version = (device.call('version').strip().splitlines() or [''])[0]
            if not device.version:
                raise DeviceFailure('environment-unavailable', 'adb version could not be observed')
            if device.call('get-state').strip() != 'device':
                raise DeviceFailure('environment-unavailable', 'the stated device is not connected (adb get-state)')
            install_ref = install_legacy(device, stated, app, out)
        for target, spec in zip(parsed, targets):
            outcome = (capture_web_target(device, stated, target, spec, out) if web
                       else capture_legacy_target(device, stated, app, target, spec, out, run_id, module_id))
            if outcome.get('status') == 'COMPLETE':
                records.append(outcome['record'])
            else:
                blocked_targets.append({'coverage': spec['coverage'], **outcome['root_cause'],
                                        **({'capture_gap': outcome['capture_gap']} if outcome.get('capture_gap') else {})})
        manifest_ref = save(out / 'manifest.json', {'schema_version': 2, 'capture_id': 'legacy-' + digest(str(out))[:12],
                                                     'legacy_preview': {k: stated.get(k) for k in ('kind', 'app_id', 'device', 'artifact_sha256', 'url')},
                                                     'install_ref': install_ref, 'targets': records})
        if records:
            try:
                validate_manifest.validate_manifest(read_json(manifest_ref['path']))
            except RuntimeError as exc:
                raise DeviceFailure('capture-incomplete', 'captured records do not validate: ' + str(exc)) from exc
        result = {'producer': 'lean-visual-worker', 'operation': 'legacy-capture',
                  'status': 'CAPTURED' if not blocked_targets else 'PARTIAL' if records else 'BLOCKED',
                  'manifest_ref': manifest_ref, 'install_ref': install_ref,
                  'captured': [f"{r['page_id']}:{r['state_id']}:{r['coverage']['requested']}" for r in records], 'blocked': blocked_targets,
                  'device_id': device.device, 'app_id': app, 'legacy_preview': stated['kind'],
                  'assignment_id': task['assignment_id'], 'fencing_token': task.get('fencing_token'),
                  'acceptance': 'a-capture-is-the-baseline-of-what-it-shows-not-a-visual-verdict'}
    except DeviceFailure as exc:
        result = blocked(str(exc), exc.kind, install_ref=install_ref)
    finally:
        result = (result or {}) | (device.finish() if device is not None else {})
    return result


def path_context(args, module, task):
    selected = [p for p in module['plan']['paths'] if p['path_id'] == args.get('path_id')]
    require(len(selected) == 1, 'frozen test path_id required')
    path = selected[0]
    require(path.get('kind') in ('automation', 'visual'), 'device tools require automation or visual PATH')
    require(task.get('role') == 'auditor' or task.get('test_scope') == path['kind'], 'PATH outside test assignment scope')
    if 'path_ids' in task:
        require(path['path_id'] in task['path_ids'], 'PATH outside audit assignment selection')
    return path


def accepted_artifact(args, module, path, backend='hdc'):
    ref = args.get('artifact_ref')
    artifact = check_ref(ref)
    if backend != 'browser':  # a web build's deliverable is whatever file the build PATH accepted; the served page names its hash
        suffix = '.apk' if backend == 'adb' else '.hap'
        require(artifact.suffix.lower() == suffix, 'visual installation requires one accepted ' + suffix[1:].upper() + ' artifact')
    artifacts = (module.get('path_build_artifacts', {}).get(path['path_id'], [])
                 if 'path_build_artifacts' in module else module.get('build_artifacts', []))
    require(ref in artifacts, 'artifact must belong to this PATH current accepted build')
    return artifact


def configuration(root, path):
    contract = path.get('visual_execution')
    if not isinstance(contract, dict) or not contract.get('environment_ref'):
        return None, None
    source = check_ref(contract['environment_ref'])
    run_storage.checked_path(source, root / 'runs/harmony/sandbox/environment')
    settings = read_json(source)
    require(isinstance(settings, dict), 'visual environment must be an object')
    return contract, settings


def frozen_visual_evidence(module, path):
    return visual_evidence.frozen_evidence(module, path)


def device_lock(actor, settings, task):
    lock = actor.get('device_lock')
    require(isinstance(lock, dict) and lock.get('held') is True
            and lock.get('device_id') == settings.get('device_id')
            and lock.get('assignment_id') == task['assignment_id']
            and lock.get('fencing_token') == task.get('fencing_token'),
            'Host must attest a current exclusive device lock for this assignment')
    return lock


def frozen_actions(device, actions):
    require(isinstance(actions, list) and len(actions) <= 30, 'at most 30 frozen navigation actions')
    for action in actions:
        require(isinstance(action, dict), 'action must be an object')
        kind = action.get('action')
        if kind == 'back':
            device.call('shell', 'uitest', 'uiInput', 'keyEvent', 'Back')
        elif kind in ('tap', 'swipe'):
            keys = ('x', 'y') if kind == 'tap' else ('x1', 'y1', 'x2', 'y2', 'velocity')
            values = [action.get(k) for k in keys]
            require(all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 40000 for v in values),
                    'frozen action coordinates/velocity must be bounded integers')
            device.call('shell', 'uitest', 'uiInput', 'click' if kind == 'tap' else 'swipe', *values)
        else:
            require(False, 'unsupported navigation action; no arbitrary shell, text, or script execution')


def target_matches(xml, expected, app_id):
    require(isinstance(expected, list) and expected, 'frozen target_match selectors required')
    nodes = list(ET.fromstring(xml).iter('node'))
    for selector in expected:
        require(isinstance(selector, dict) and selector and
                set(selector) <= {'class', 'resource-id', 'text', 'content-desc', 'focused'}
                and all(isinstance(value, str) and value for value in selector.values()),
                'target_match supports nonempty exact UI attribute selectors only')
        if not any(all(n.get(key) == value for key, value in selector.items()) and
                   n.get('package') in ('', app_id) for n in nodes):
            return False
    return True


def app_running(output, app):
    return any(re.search(r'app name \[' + re.escape(app) + r']', line) for line in output.splitlines())


def not_in_front(device, app, when):
    """The frozen app is not in front: gone from the running list it is a defect of the candidate (Red evidence); still
    running behind something it is a precondition gap. A device that cannot tell reports the gap."""
    if hasattr(device, 'running') and not device.running(app):
        return failed('app exited after launch ' + when, 'app-runtime-failure')
    return blocked('requested app is not the observed foreground app ' + when, 'target-precondition')


def foreground_app(output):
    current = None
    for line in output.splitlines():
        match = re.search(r'app name \[([^]]+)]', line)
        if match:
            current = match.group(1)
        if 'foreground' in line.lower() and current:
            return current
    return None


def scoped_scroll_region(xml, selector, app):
    if not selector:
        return None, None
    # Reuse the exact selector schema, then require an unambiguous actual scrollable node.
    target_matches(xml, [selector], app)
    matches = [node for node in ET.fromstring(xml).iter('node')
               if all(node.get(key) == value for key, value in selector.items())
               and node.get('package') in ('', app) and node.get('scrollable') == 'true']
    if len(matches) != 1:
        return None, None
    return matches[0], mobile_snapshot.bounds_box(matches[0].get('bounds', ''))


def candidate_context(device, contract, args, path, module, task, out, root):
    """What every candidate capture stands on: the frozen reference manifest and baseline, the current install receipt and a
    new round. Returns (target, manifest, install, round_id) or a blocked result."""
    target = validate_manifest.parse_target(path['coverage'])
    if path.get('baseline_ref') is None:
        # Image checks only: the target is captured on its own, and nodes are compared with rendered legacy pictures.
        require(path.get('image_check_ids'), 'a visual PATH without a baseline must carry image checks')
        manifest = {'schema_version': 2, 'targets': []}
    else:
        evidence = frozen_visual_evidence(module, path)
        if not evidence:
            return blocked('PATH lacks a frozen original capture manifest; use the existing adapter or review SPEC evidence',
                           'source-evidence-unavailable')
        manifest = read_json(check_ref(args.get('reference_manifest_ref')))
        validate_manifest.validate_manifest(manifest, [target])
        # A later attempt may append candidate rounds. Its Android reference is an exact copy of
        # the original frozen record, including every viewport, never just the first screenshot.
        reference = visual_evidence.match_source(args['reference_manifest_ref'], evidence, path['coverage'])
        require(reference['status'] == 'COMPLETE', 'source-only cannot authorize a visual candidate capture')
        require(any(file_ref(row['screenshot'])['sha256'] == path['baseline_ref']['sha256']
                    for row in reference['snapshot']['captures']), 'Android reference differs from frozen baseline')
    install_path = check_ref(args.get('install_ref'))
    run_storage.checked_path(install_path, out.parents[1])
    install = visual_evidence.installation(args['install_ref'], artifact_ref=args['artifact_ref'],
        code_baseline=module['code_baseline'], device_id=device.device, app_id=contract['app_id'],
        assignment_id=task['assignment_id'], fencing_token=task.get('fencing_token'), run_root=str(root))
    round_id = args.get('round')
    require(isinstance(round_id, int) and not isinstance(round_id, bool) and round_id > 0,
            'positive explicit capture round required')
    require(not any(visual_evidence.is_candidate(row) and row.get('page_id') == target['page_id']
                    and row.get('state_id') == target['state_id'] and row.get('round') == round_id
                    for row in manifest['targets']), 'preserve previous capture round; select a new round')
    return target, manifest, install, round_id


def capture_android(device, contract, args, path, module, task, out, root):
    """The candidate APK's screen as an android-candidate record, captured like the legacy reference but bound to the
    accepted build, the install receipt and the round."""
    context = candidate_context(device, contract, args, path, module, task, out, root)
    if isinstance(context, dict):
        return context
    target, manifest, install, round_id = context
    app = token(contract.get('app_id'), 'app_id')
    identity = android_identity(device, app, args['artifact_ref']['sha256'])
    activity = contract.get('ability')
    require(isinstance(activity, str) and re.fullmatch(r'[A-Za-z0-9_.$]+', activity), 'an Android candidate names its launch activity as ability')
    device.call('shell', 'am', 'start', '-n', app + '/' + activity)
    android_actions(device, contract.get('actions', []))
    observed = observe_screen(device, app, target, contract, out, 'candidate')
    if 'captures' not in observed:
        return observed
    return candidate_record(observed, 'android-candidate', 'android', target, manifest, round_id, args, module, task, out, path, artifact_identity=identity)


def web_identity(device, contract, artifact, sha256):
    """The served target page is reachable and declares the accepted build: its <meta name="sdd-build"> equals the artifact hash.
    Deployment is the host's or the build PATH's; the worker only reads what the page says it is."""
    url = contract.get('url')
    require(isinstance(url, str) and url.startswith(('http://', 'https://')) and urlparse(url).netloc == device.device,
            'a web target names the url served at its app_id host')
    device.act('goto', url)
    declared = str(device.act('identity') or '')
    device.logs.append({'action': 'install', 'argv': ['browser', 'install', url, str(artifact)], 'exit_code': 0 if declared == sha256 else 1, 'identity': declared})
    if declared != sha256:
        raise DeviceFailure('artifact-identity-unverified', 'the served page does not declare the accepted build (meta sdd-build differs from the artifact hash)')
    host, title = device.foreground()
    return {'kind': 'meta[name=sdd-build]', 'sha256': declared, 'url': url, 'title': title}


def capture_web(device, contract, args, path, module, task, out, root):
    """The deployed web target's screen as a web-candidate record: the page re-declares the accepted build, is walked by frozen
    clicks and observed like every other screen."""
    context = candidate_context(device, contract, args, path, module, task, out, root)
    if isinstance(context, dict):
        return context
    target, manifest, install, round_id = context
    identity = web_identity(device, contract, check_ref(args['artifact_ref']), args['artifact_ref']['sha256'])
    web_actions(device, contract.get('actions', []))
    observed = observe_screen(device, device.device, target, contract, out, 'candidate')
    if 'captures' not in observed:
        return observed
    return candidate_record(observed, 'web-candidate', 'web', target, manifest, round_id, args, module, task, out, path, artifact_identity=identity)


def capture(device, contract, args, path, module, task, out, root):
    """The candidate HAP's screen as a harmony-candidate record: its identity checked against the accepted install, launched
    by ability, walked by frozen actions, observed like every other screen."""
    context = candidate_context(device, contract, args, path, module, task, out, root)
    if isinstance(context, dict):
        return context
    target, manifest, install, round_id = context
    app = token(contract.get('app_id'), 'app_id')
    if not installed_identity(device.call('shell', 'bm', 'dump', '-n', app), install.get('artifact_identity') or {}):
        return blocked('installed app identity no longer matches the accepted HAP', 'artifact-identity-unverified')
    ability = token(contract.get('ability', 'EntryAbility'), 'ability')
    device.call('shell', 'aa', 'start', '-b', app, '-a', ability)
    frozen_actions(device, contract.get('actions', []))
    observed = observe_screen(device, app, target, contract, out, 'candidate')
    if 'captures' not in observed:
        return observed
    return candidate_record(observed, 'harmony-candidate', 'harmony', target, manifest, round_id, args, module, task, out, path)


def candidate_record(observed, phase, platform, target, manifest, round_id, args, module, task, out, path, **extra):
    """A candidate observation bound to the accepted build, the install receipt and the round, appended to the reference
    manifest as the record the adapter and the acceptance read; a partial scroll is kept but never advances."""
    captures, coverage = observed['captures'], observed['coverage']
    meta = {**observed['meta'], 'install_ref': args['install_ref'], 'artifact_ref': args['artifact_ref'], **extra,
            'code_baseline': module['code_baseline'], 'assignment_id': task['assignment_id'], 'fencing_token': task.get('fencing_token')}
    meta_ref = save(out / 'meta.json', meta)
    snapshot = {**captures[0], 'meta': meta_ref['path'], 'device_backend': observed['backend'], 'coverage': coverage, 'captures': captures}
    result_manifest = copy.deepcopy(manifest)
    result_manifest['targets'].append({'mode': 'targeted', 'phase': phase, 'platform': platform,
            'page_id': target['page_id'], 'state_id': target['state_id'], 'observed_variant': target['state_id'],
            'round': round_id, 'status': 'COMPLETE' if observed['complete'] else 'BLOCKED', 'coverage': coverage,
            'timestamp': datetime.now(timezone.utc).isoformat(), 'snapshot': snapshot,
            'target_match': {'kind': 'frozen-exact-selectors', 'matched': True}})
    manifest_ref = save(out / 'manifest.json', result_manifest)
    if not observed['complete']:
        return blocked('bounded scroll observations do not prove full scroll coverage; use the full runtime adapter',
                       'capture-incomplete', manifest_ref=manifest_ref)
    validate_manifest.validate_snapshot(snapshot, target['coverage'], path['coverage'])
    return {'status': 'CAPTURED', 'manifest_ref': manifest_ref, 'meta_ref': meta_ref,
            'artifact_ref': args['artifact_ref'], 'acceptance': 'capture-is-evidence-not-a-visual-verdict'}


def semantic(args, settings, path, out, root, module):
    require(path.get('baseline_ref') is not None, 'semantic inspection compares a baseline; this PATH carries image checks only')
    model = settings.get('visual_model')
    if not isinstance(model, dict) or model.get('mode') != 'external' or model.get('enabled') is not True:
        return blocked('explicit enabled external visual_model configuration required')
    model = copy.deepcopy(model)
    require('api_key' not in model, 'store only an API key environment variable name in visual configuration')
    env_name = model.get('api_key_env')
    require(isinstance(env_name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env_name), 'api_key_env required')
    model['api_key'] = os.environ.get(env_name, '')
    if not model['api_key'] or not model.get('name') or not model.get('base_url'):
        return blocked('visual model name/base_url or configured API key environment variable missing')
    url = urlparse(model['base_url'])
    require(url.scheme in ('https', 'http') and url.hostname and not url.username and not url.password,
            'visual model requires an explicit HTTP(S) endpoint without URL credentials')
    reference, candidate, score_file = [check_ref(args.get(k)) for k in ('reference_ref', 'candidate_ref', 'score_ref')]
    for evidence in (candidate, score_file):
        run_storage.checked_path(evidence, root)
    for screenshot in (reference, candidate):
        with screenshot.open('rb') as image:
            magic = image.read(8)
        require(screenshot.stat().st_size <= 32 * 1024 * 1024 and
                (magic == b'\x89PNG\r\n\x1a\n' or magic.startswith(b'\xff\xd8\xff')),
                'semantic images must be PNG/JPEG files no larger than 32 MiB')
        try:
            image_valid(screenshot)
        except DeviceFailure as exc:
            return blocked(str(exc), exc.kind)
    evidence = frozen_visual_evidence(module, path)
    baselines = evidence['baseline_refs'] if evidence else [path['baseline_ref']]
    require(file_ref(reference)['sha256'] in {ref['sha256'] for ref in baselines},
            'semantic reference differs from this coverage frozen baseline set')
    score = read_json(score_file)
    require(file_ref(score.get('reference')) == args['reference_ref'] and
            file_ref(score.get('candidate')) == args['candidate_ref'], 'score must bind the actual comparison images')
    timeout = model.get('timeout_seconds', 120)
    require(isinstance(timeout, int) and 1 <= timeout <= 180, 'visual model timeout must be 1..180 seconds')
    try:
        from lean_semantic_process import call
        raw = call(model, path['coverage'], reference, candidate, score, timeout)
        require(isinstance(raw, dict) and raw.get('status') == 'COMPLETE', 'model did not return COMPLETE semantic inspection')
        require(raw.get('visual_id', path['coverage']) == path['coverage'], 'semantic target mismatch')
        for key, maximum in (('overall', 100), ('comparability', 1)):
            value = raw.get(key)
            require(isinstance(value, (int, float)) and not isinstance(value, bool) and
                    math.isfinite(value) and 0 <= value <= maximum, 'invalid semantic ' + key)
        issues = raw.get('issues')
        require(isinstance(issues, list) and len(issues) <= 2 and all(isinstance(i, dict) and
                all(isinstance(i.get(k), str) and i[k].strip() for k in ('area', 'problem', 'likely_code_area', 'evidence'))
                and i.get('severity') in ('low', 'medium', 'high', 'critical') for i in issues),
                'semantic issues must follow the bounded evidence schema')
        result = semantic_visual_inspect.normalize_result(raw, path['coverage'], model)
        result.update(score_sha256=args['score_ref']['sha256'], reference=str(reference), candidate=str(candidate),
                      score_ref=args['score_ref'], reference_ref=args['reference_ref'], candidate_ref=args['candidate_ref'])
        return {'status': 'INSPECTED', 'semantic_ref': save(out / 'visual-issues.json', result),
                'acceptance': 'semantic-inspection-is-evidence-not-a-visual-verdict'}
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        # API error bodies and exception strings may echo credentials or inline screenshots.
        return blocked('semantic inspection failed: ' + type(exc).__name__, 'semantic-unavailable')


def parity(args, out, module, task, run_id):
    """Compare each frozen image check's node in a captured target screen with its rendered legacy picture.

    Reads evidence only: the candidate capture an earlier visual-capture produced and the references the
    checks froze. The report is a measurement; acceptance stays with the Ledger, which recomputes it."""
    path = path_context(args, module, task)
    checks = ui_fidelity.frozen_image_checks(module, path)
    require(checks, 'image parity requires a visual PATH that carries image checks')
    manifest_ref = args.get('manifest_ref')
    manifest_path = check_ref(manifest_ref)
    round_id = args.get('round')
    require(isinstance(round_id, int) and not isinstance(round_id, bool) and round_id > 0, 'positive explicit capture round required')
    page, state, _ = path['coverage'].split(':')
    records = [r for r in read_json(manifest_path).get('targets', []) if visual_evidence.is_candidate(r)
               and r.get('page_id') == page and r.get('state_id') == state
               and r.get('round') == round_id and r.get('status') == 'COMPLETE']
    require(len(records) == 1, 'one completed candidate capture is required for the selected round')
    snapshot = records[0]['snapshot']
    captures = {capture['index']: capture for capture in snapshot['captures']}
    rows = []
    for check in checks:
        index = check['target'].get('capture_index', 0)
        require(index in captures, 'capture index ' + str(index) + ' is not in the candidate capture')
        shot = visual_evidence.reference(captures[index]['screenshot'], manifest_path.parent)
        view = visual_evidence.reference(captures[index].get('view_tree') or captures[index].get('view_xml'), manifest_path.parent)
        png = ui_evidence.image_check_reference(check)
        try:
            row, crop = image_parity.evaluate(check, check_ref(png) if png else None, Path(shot['path']), Path(view['path']).read_text())
        except image_parity.ParityError as exc:
            raise RuntimeError(str(exc)) from exc
        row.update(capture_index=index, screenshot_ref=shot, view_ref=view)
        if png:
            row.update(reference_ref=png, render_ref=check['reference']['render_ref'])
        if crop is not None:
            crop_path = run_storage.checked_path(out / 'crops' / (check['id'] + '.png'), out)
            crop_path.parent.mkdir(parents=True, exist_ok=True)
            crop.save(crop_path, format='PNG')
            row['crop_ref'] = file_ref(crop_path)
        rows.append(row)
    import PIL
    execution = read_json(check_ref(snapshot['capture_execution_ref']))
    report = {'schema_version': 1, 'producer': 'sdd-image-parity', 'run_id': run_id, 'module_id': module['module_id'],
              'path_id': path['path_id'], 'assignment_id': task['assignment_id'], 'code_baseline': module['code_baseline'],
              'coverage': path['coverage'], 'manifest_ref': manifest_ref, 'capture_round': round_id,
              'hap_ref': execution['artifact_ref'], 'pillow': PIL.__version__, 'checks': rows}
    statuses = {row['status'] for row in rows}
    return {'status': 'MEASURED', 'report_ref': save(out / 'image-parity.json', report),
            'quality_candidate': 'red-bug' if 'MISMATCH' in statuses else 'green-passed' if statuses == {'MATCH'} else 'yellow-blocked',
            'acceptance': 'measurement-is-evidence-not-a-visual-verdict'}


def run(operation, args, *, root, out, module, task, actor, config):
    require(operation in OPERATIONS and actor.get('role') in ('test-runner', 'auditor'), 'visual capability outside role')
    root, out = Path(root).resolve(), Path(out).resolve()
    runner_storage.harmony_output(root, out, 'sandbox')
    path = path_context(args, module, task)
    if operation != 'visual-install':
        require(path['kind'] == 'visual', 'capture/semantic inspection require a visual PATH')
    contract, settings = configuration(root, path)
    if contract is None:
        return blocked('frozen visual_execution.environment_ref missing; prepare run environment and review the PATH configuration')
    if operation == 'semantic-inspect':
        return semantic(args, settings, path, out, root, module)
    device_settings = settings.get('visual_capture')
    if not isinstance(device_settings, dict) or not device_settings.get('device_id'):
        return blocked('explicit run visual_capture backend and device_id required')
    device_lock(actor, device_settings, task)
    backend = device_settings.get('backend')
    require(backend in ('hdc', 'adb', 'browser'), 'visual capture requires explicitly configured hdc, adb or browser backend')
    artifact = accepted_artifact(args, module, path, backend)
    app = token(contract.get('app_id'), 'app_id')
    if backend == 'browser':  # a web target: the host that serves it is the device, the page is the screen
        url = device_settings.get('url')
        require(isinstance(url, str) and url.startswith(('http://', 'https://')) and urlparse(url).netloc == app, 'visual_capture.url names the served web target at app_id')
        device = BrowserDevice(url, out, viewport=device_settings.get('viewport'))
    else:
        device = Device(device_settings, out) if backend == 'hdc' else AndroidDevice(device_settings.get('device_id'), device_settings.get('tool', 'adb'), out)
    try:
        if backend != 'browser':
            lines = (device.call('-v') if backend == 'hdc' else device.call('version')).strip().splitlines()
            device.version = lines[0] if lines else ''
            if not device.version:
                raise DeviceFailure('environment-unavailable', backend.upper() + ' version could not be observed')
        if operation == 'visual-install' and backend == 'browser':  # the deployed page declares the accepted build; nothing is installed by the worker
            identity = web_identity(device, contract, artifact, args['artifact_ref']['sha256'])
            result = {'producer': 'lean-visual-worker', 'operation': operation, 'status': 'INSTALLED',
                      'artifact_ref': args['artifact_ref'], 'code_baseline': module['code_baseline'],
                      'device_id': device.device, 'app_id': app, 'assignment_id': task['assignment_id'],
                      'fencing_token': task.get('fencing_token'), 'installed_metadata': {'url': identity['url'], 'title': identity['title']},
                      'artifact_identity': identity,
                      'acceptance': 'installation-is-evidence-not-a-test-verdict'}
        elif operation == 'visual-install' and backend == 'adb':  # the candidate APK: installed, then hashed on the device against the accepted bytes
            device.call('install', '-r', artifact, timeout=240)
            identity = android_identity(device, app, args['artifact_ref']['sha256'])
            installed = identity['installed']
            result = {'producer': 'lean-visual-worker', 'operation': operation, 'status': 'INSTALLED',
                      'artifact_ref': args['artifact_ref'], 'code_baseline': module['code_baseline'],
                      'device_id': device.device, 'app_id': app, 'assignment_id': task['assignment_id'],
                      'fencing_token': task.get('fencing_token'), 'installed_metadata': installed,
                      'artifact_identity': identity,
                      'acceptance': 'installation-is-evidence-not-a-test-verdict'}
        elif operation == 'visual-install':
            identity = hap_identity(artifact)
            if identity['bundleName'] != app:
                raise DeviceFailure('artifact-identity-unverified', 'accepted HAP bundleName differs from frozen app_id')
            device.call('install', '-r', artifact, timeout=240)
            installed = device.call('shell', 'bm', 'dump', '-n', app)
            if not installed_identity(installed, identity):
                raise DeviceFailure('artifact-identity-unverified', 'installed app bundle/version differs from accepted HAP')
            result = {'producer': 'lean-visual-worker', 'operation': operation, 'status': 'INSTALLED',
                      'artifact_ref': args['artifact_ref'], 'code_baseline': module['code_baseline'],
                      'device_id': device.device, 'app_id': app, 'assignment_id': task['assignment_id'],
                      'fencing_token': task.get('fencing_token'), 'installed_metadata': installed,
                      'artifact_identity': identity,
                      'acceptance': 'installation-is-evidence-not-a-test-verdict'}
        else:
            result = {'adb': capture_android, 'browser': capture_web}.get(backend, capture)(device, contract, args, path, module, task, out, root)
    except DeviceFailure as exc:
        result = blocked(str(exc), exc.kind)
    finally:
        evidence = device.finish()
    result.update(evidence)
    if result.get('status') == 'CAPTURED':
        manifest = read_json(check_ref(result['manifest_ref']))
        record = manifest['targets'][-1]
        execution = {'schema_version': 1, 'producer': 'sdd-visual-capture', 'status': 'CAPTURED',
            'executed': True, 'coverage': path['coverage'], 'capture_round': args['round'],
            'artifact_ref': args['artifact_ref'], 'code_baseline': module['code_baseline'],
            'assignment_id': task['assignment_id'], 'fencing_token': task.get('fencing_token'),
            'device_id': device.device, 'app_id': app, 'install_ref': args['install_ref'],
            'observations': visual_evidence.observations(record, out),
            'command_log_ref': evidence['command_log_ref']}
        record['snapshot']['capture_execution_ref'] = save(out / 'capture-execution.json', execution)
        result['manifest_ref'] = save(out / 'manifest.json', manifest)
        result['capture_execution_ref'] = record['snapshot']['capture_execution_ref']
    return result
