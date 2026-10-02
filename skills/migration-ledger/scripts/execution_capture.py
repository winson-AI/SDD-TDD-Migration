"""Bounded-memory pipe capture. Observations never change Ledger or worker state."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from contracts import check_ref, file_ref, read_json, require
from run_storage import atomic_bytes, checked_path


def now():
    return datetime.now(timezone.utc).isoformat()


class Capture:
    def __init__(self, directory, identity):
        self.directory = Path(directory)
        self.selector = selectors.DefaultSelector()
        self.files = {}
        self.state = {**identity, 'schema_version': 1, 'status': 'running', 'output_complete': False,
                      'started_at': now(), 'last_output_at': None, 'chunks': 0,
                      'bytes': {'stdout': 0, 'stderr': 0}}
        try:
            for name in ('stdout.log', 'stderr.log', 'execution.log', 'output-events.jsonl'):
                self.files[name] = checked_path(self.directory / name, self.directory).open('xb', buffering=0)
            self.save()
        except BaseException:
            self.close()
            raise

    def save(self):
        atomic_bytes(self.directory / 'execution-state.json', json.dumps(self.state).encode())

    def attach(self, proc):
        self.state.update(pid=proc.pid, process_group_id=proc.pid)
        for name, stream in (('stdout', proc.stdout), ('stderr', proc.stderr)):
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, name)
        self.save()

    def wait(self, proc, timeout):
        deadline = time.monotonic() + timeout
        while self.selector.get_map() or proc.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            for key, _ in self.selector.select(min(.1, remaining)):
                try:
                    data = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not data:
                    self.selector.unregister(key.fileobj)
                    continue
                stream, stamp = key.data, now()
                offset = self.state['bytes'][stream]
                self.files[stream + '.log'].write(data)
                self.files['execution.log'].write(f'\n[{stamp} {stream}] '.encode() + data)
                event = {'sequence': self.state['chunks'] + 1, 'at': stamp, 'stream': stream,
                         'offset': offset, 'bytes': len(data)}
                self.files['output-events.jsonl'].write((json.dumps(event) + '\n').encode())
                self.state['bytes'][stream] += len(data)
                self.state.update(chunks=event['sequence'], last_output_at=stamp)
            # Refresh at most once per second; logs themselves are unbuffered.
            if time.monotonic() - getattr(self, '_saved', 0) >= 1:
                self.save(); self._saved = time.monotonic()
        proc.wait(timeout=max(.01, deadline - time.monotonic()))

    def finish(self, status, exit_code, complete, note=''):
        if note:
            self.files['execution.log'].write(f'\n[{now()} host] {note}\n'.encode())
        self.state.update(status=status, exit_code=exit_code, output_complete=complete, finished_at=now())
        self.save()

    def close(self):
        self.selector.close()
        for stream in self.files.values():
            stream.close()

    def references(self):
        return {key: file_ref(self.directory / name) for key, name in (
            ('state_ref', 'execution-state.json'), ('stdout_ref', 'stdout.log'),
            ('stderr_ref', 'stderr.log'), ('events_ref', 'output-events.jsonl'))}


def observe(root, state_file, identity):
    """Host/watchdog only: a live, non-authoritative observation, never a heartbeat."""
    root = Path(root).resolve()
    path = checked_path(state_file, root / 'runs')
    require(path.name == 'execution-state.json', 'expected execution-state.json')
    value = read_json(path)
    require(isinstance(value, dict), 'invalid execution observation')
    require(all(value.get(k) == v for k, v in identity.items()), 'execution observation identity mismatch')
    return {k: value.get(k) for k in ('status', 'output_complete', 'started_at', 'finished_at',
                                     'last_output_at', 'bytes', 'chunks', 'test_run_id')}


def validate(receipt):
    capture = receipt.get('capture')
    if capture is None:
        return  # Historical receipts predate streaming capture.
    require(isinstance(capture, dict) and set(capture) == {'state_ref', 'stdout_ref', 'stderr_ref', 'events_ref'},
            'invalid execution capture references')
    for ref in capture.values():
        check_ref(ref)
    state = read_json(capture['state_ref']['path'])
    require(isinstance(state, dict), 'invalid execution capture state')
    for key in ('run_id', 'module_id', 'assignment_id', 'actor_instance_id', 'test_run_id', 'path_id',
                'freeze_id', 'code_baseline', 'exit_code'):
        require(state.get(key) == receipt.get(key), 'execution capture identity mismatch: ' + key)
    require(state.get('finished_at') and state.get('status') != 'running', 'execution capture not finalized')
    if receipt.get('exit_code') == 0:
        require(state.get('status') == 'finished' and state.get('output_complete') is True,
                'successful execution requires complete output capture')
