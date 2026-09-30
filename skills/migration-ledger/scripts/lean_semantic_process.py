"""Private, bounded subprocess transport for the visual model call.

The authenticated visual worker validates paths/configuration before calling this helper.
Credentials travel through stdin only; no request body or raw provider error is persisted.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

sys.dont_write_bytecode = True
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def stop(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=2)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        if process.poll() is None:
            raise RuntimeError('semantic process stop unconfirmed; Host must verify termination')


def call(model, visual_id, reference, candidate, score, timeout):
    payload = {'model': model, 'visual_id': visual_id, 'reference': str(reference),
               'candidate': str(candidate), 'score': score, 'timeout': timeout}
    process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--internal-call'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, _ = process.communicate(json.dumps(payload), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stop(process)
        raise TimeoutError('semantic process exceeded total time limit') from exc
    except BaseException:
        stop(process)
        raise
    if process.returncode or len(stdout.encode()) > MAX_RESPONSE_BYTES:
        raise RuntimeError('semantic process failed or exceeded response limit')
    result = json.loads(stdout)
    if not isinstance(result, dict) or 'error_type' in result:
        raise RuntimeError('semantic provider returned no usable result')
    if model.get('api_key') and model['api_key'] in json.dumps(result):
        raise RuntimeError('semantic provider returned credential material')
    return result


def main():
    if sys.argv[1:] != ['--internal-call']:
        raise SystemExit('Internal helper; invoke authenticated lean_worker semantic-inspect')
    try:
        from lean_tools.semantic_visual_inspect import call_model
        request = json.load(sys.stdin)
        result = call_model(request['model'], request['visual_id'], Path(request['reference']),
                            Path(request['candidate']), request['score'], request['timeout'])
        encoded = json.dumps(result)
        if len(encoded.encode()) > MAX_RESPONSE_BYTES:
            raise ValueError('response too large')
        print(encoded)
    except Exception as exc:
        # A provider can echo Authorization, image payloads or prompts in its error body.
        print(json.dumps({'error_type': type(exc).__name__}))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
