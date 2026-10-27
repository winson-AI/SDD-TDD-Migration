#!/usr/bin/env python3
"""Run a command for a role or the host and hand back its result, never its log.

    run   --log <file> [--cwd] [--timeout] -- <argv...>   run it, the output going to the log; print the result
    start --log <file> [--cwd] [--timeout] -- <argv...>   the same, detached; print the pid and return at once
    wait  --log <file> [--timeout]                         follow the log's end until the command exits; print the result
    grep  --log <file> --pattern <regex> [--max]           the matching lines with their numbers, each cut short

The result is one JSON line: exit code, the log's reference, and on a failure the error locations grepped from the log
(failures.json: file, line, column, message) with their count and the first one. Read the locations; grep the log only
when they are not enough; do not read the log whole.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
sys.dont_write_bytecode = True

import failures
from contracts import file_ref

POLL_SECONDS = 1


def marker(log):
    return Path(str(log) + '.exit.json')


def result(log):
    log = Path(log)
    ended = json.loads(marker(log).read_text())
    out = {'exit_code': ended['exit_code'], 'log_ref': file_ref(log), 'seconds': ended['seconds']}
    if ended['exit_code'] != 0:
        path, rows = failures.write(log, str(log) + '.failures.json')
        out.update(failure_count=len(rows), summary=failures.summary(rows), **({'failures_ref': file_ref(path)} if path else {}))
    return out


def run(argv, log, cwd=None, timeout=None):
    log = Path(log).resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    marker(log).unlink(missing_ok=True)
    started = time.monotonic()
    with log.open('wb') as sink:
        try:
            code = subprocess.run(argv, cwd=cwd, stdout=sink, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
        except OSError as exc:
            sink.write(f'error: cannot start {argv[0]}: {exc}\n'.encode())
            code = 127
    marker(log).write_text(json.dumps({'exit_code': code, 'seconds': round(time.monotonic() - started, 1)}))
    return result(log)


def start(argv, log, cwd=None, timeout=None):
    log = Path(log).resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    marker(log).unlink(missing_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), 'run', '--log', str(log), *(['--cwd', cwd] if cwd else []),
               *(['--timeout', str(timeout)] if timeout else []), '--', *argv]
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    return {'started': child.pid, 'log': str(log)}


def wait(log, timeout=None):
    """Follow the end of the log, as `tail -f` would, until the command's exit is recorded; the lines are not read."""
    deadline = time.monotonic() + timeout if timeout else None
    while not marker(log).is_file():
        if deadline and time.monotonic() > deadline:
            return {'running': True, 'log': str(log), 'log_bytes': Path(log).stat().st_size if Path(log).is_file() else 0}
        time.sleep(POLL_SECONDS)
    return result(log)


def grep(log, pattern, limit=50):
    rx, rows = re.compile(pattern), []
    with Path(log).open(errors='replace') as lines:
        for number, text in enumerate(lines, 1):
            if rx.search(text):
                rows.append({'line': number, 'text': text.rstrip('\n')[:failures.MAX_MESSAGE]})
                if len(rows) >= limit:
                    break
    return {'log': str(log), 'pattern': pattern, 'matches': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('run', 'start', 'wait', 'grep'))
    parser.add_argument('--log', required=True)
    parser.add_argument('--cwd')
    parser.add_argument('--timeout', type=float)
    parser.add_argument('--pattern')
    parser.add_argument('--max', type=int, default=50)
    words = sys.argv[1:]
    cut = words.index('--') if '--' in words else len(words)  # what follows -- is the command, untouched
    args, argv = parser.parse_args(words[:cut]), words[cut + 1:]
    if args.command in ('run', 'start') and not argv:
        parser.error('a command to run follows --')
    if args.command == 'grep' and not args.pattern:
        parser.error('grep needs --pattern')
    out = (run(argv, args.log, args.cwd, args.timeout) if args.command == 'run' else
           start(argv, args.log, args.cwd, args.timeout) if args.command == 'start' else
           wait(args.log, args.timeout) if args.command == 'wait' else grep(args.log, args.pattern, args.max))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get('exit_code', 0) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
