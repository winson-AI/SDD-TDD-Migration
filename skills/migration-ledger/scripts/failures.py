"""Where a failed command broke, grepped from its log: the compiler and tool error lines with their file, line and column.
A model reads these locations, not the log; the log stays on disk for a bounded grep when the locations are not enough."""
import json
from pathlib import Path
import re

MAX_FAILURES = 50
MAX_MESSAGE = 400
STAMP = re.compile(r'^\[[^\]]* (?:stdout|stderr)\] ')  # the build runner's per-line stamp
# (name, pattern): each names `path` and `line` when the tool prints a location, and `message`.
PATTERNS = (
    ('kotlin', re.compile(r'^e: (?:file://)?(?P<path>/[^\s:]+):(?P<line>\d+):(?P<col>\d+)\s+(?P<message>.+)$')),
    ('kotlin-legacy', re.compile(r'^e: (?P<path>/[^\s:]+): \((?P<line>\d+), (?P<col>\d+)\): (?P<message>.+)$')),
    ('javac', re.compile(r'^(?P<path>/\S+?\.java):(?P<line>\d+): error: (?P<message>.+)$')),
    ('arkts', re.compile(r'(?:ERROR|Error).*?File: (?P<path>/\S+?):(?P<line>\d+):(?P<col>\d+)\s*(?P<message>.*)$')),
    ('tsc', re.compile(r'^(?P<path>\S+?\.(?:ts|tsx|ets)):?\((?P<line>\d+),(?P<col>\d+)\): error (?P<message>.+)$')),
    ('python', re.compile(r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+)(?P<message>.*)$')),
    ('cc', re.compile(r'^(?P<path>/\S+?):(?P<line>\d+):(?:(?P<col>\d+):)? (?:fatal )?error: (?P<message>.+)$')),
    ('gradle', re.compile(r'^\* What went wrong:\s*(?P<message>.*)$')),
    ('error', re.compile(r'^(?:.*\s)?(?:error|ERROR|Error)(?::|\s-)\s*(?P<message>\S.*)$')),
)


def extract(log):
    """The failure locations of one log, in log order, at most MAX_FAILURES; a location-less tool error (Gradle's "What
    went wrong", a bare `error:`) is kept only when it is not the text of a located one."""
    rows, pending = [], None
    with Path(log).open(errors='replace') as lines:
        for number, text in enumerate(lines, 1):
            text = STAMP.sub('', text.rstrip('\n'))
            if pending is not None:  # Gradle and ArkTS put the message on the line after the marker
                if text.strip():
                    pending['message'] = text.strip()[:MAX_MESSAGE]
                    pending = None
                continue
            for name, pattern in PATTERNS:
                match = pattern.search(text)
                if not match:
                    continue
                found = match.groupdict()
                row = {'kind': name, 'log_line': number, 'message': (found.get('message') or '').strip()[:MAX_MESSAGE]}
                if found.get('path'):
                    row.update(path=found['path'], line=int(found['line']), **({'col': int(found['col'])} if found.get('col') else {}))
                if name == 'python' and rows and rows[-1]['kind'] == 'python':
                    rows.pop()  # the innermost frame of a traceback is where it broke
                elif not row.get('path') and any(r['message'] and r['message'] in row['message'] for r in rows if r.get('path')):
                    break
                rows.append(row)
                if not row['message']:
                    pending = row
                break
            if len(rows) >= MAX_FAILURES:
                break
    return rows


def inside(rows, roots):
    """Whether every located failure is in a file under one of `roots` (the module's write scope)."""
    located = [r for r in rows if r.get('path')]
    roots = [Path(root).resolve() for root in roots]
    return bool(located) and all(any(Path(r['path']).resolve().is_relative_to(root) for root in roots) for r in located)


def summary(rows):
    first = next((r for r in rows if r.get('path')), rows[0] if rows else None)
    if not first:
        return 'no error line found in the log; grep it'
    where = '%s:%s' % (first['path'], first['line']) if first.get('path') else first['kind']
    return '%d error location(s); first %s: %s' % (len(rows), where, first['message'])


def write(log, path):
    """The grepped locations written to `path` (a failures.json); None when the log names none."""
    rows = extract(log)
    if not rows:
        return None, rows
    path = Path(path)
    path.write_text(json.dumps({'log': str(log), 'failures': rows}, ensure_ascii=False, indent=2) + '\n')
    return path, rows
