"""Real subprocess/loopback checks for model deadlines and bounded provider output."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import lean_semantic_process


class SemanticProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'test.png'; self.image.write_bytes(b'fixture; transport test only')
        self.mode = 'success'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                if owner.mode == 'error':
                    self.send_response(403); self.end_headers()
                    self.wfile.write(b'provider error with TEST_PRIVATE_CREDENTIAL')
                    return
                self.send_response(200); self.end_headers()
                try:
                    if owner.mode == 'slow':
                        # Bytes continue arriving inside the socket timeout; only the
                        # outer wall-clock deadline can end this uncompleted response.
                        for _ in range(60):
                            self.wfile.write(b' '); self.wfile.flush(); time.sleep(.05)
                        return
                    if owner.mode == 'large':
                        self.wfile.write(b'x' * (lean_semantic_process.MAX_RESPONSE_BYTES + 1))
                        return
                    data = {'status': 'COMPLETE', 'visual_id': 'home:base:viewport',
                            'overall': 99, 'comparability': 1, 'issues': []}
                    if owner.mode == 'echo-key':
                        data['issues'] = ['TEST_PRIVATE_CREDENTIAL']
                    self.wfile.write(json.dumps({'choices': [{'message': {'content': json.dumps(data)}}]}).encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The bounded parent killed its own test client.

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start(); self.addCleanup(self.close)
        self.model = {'name': 'fixture', 'base_url': f'http://127.0.0.1:{self.server.server_port}',
                      'api_key': 'TEST_PRIVATE_CREDENTIAL'}

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=1)

    def call(self, timeout=3):
        return lean_semantic_process.call(self.model, 'home:base:viewport', self.image, self.image, {}, timeout)

    def test_success_uses_real_child_without_persisting_credentials(self):
        self.assertEqual(self.call()['status'], 'COMPLETE')
        self.assertEqual(list(self.root.iterdir()), [self.image])

    def test_slow_response_is_stopped_by_total_deadline(self):
        self.mode = 'slow'; start = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, 'total time limit'):
            self.call(timeout=1)
        self.assertLess(time.monotonic() - start, 4)

    def test_provider_errors_oversized_output_and_echoed_secret_are_not_returned(self):
        for mode in ('error', 'large', 'echo-key'):
            self.mode = mode
            with self.subTest(mode=mode), self.assertRaises(RuntimeError) as raised:
                self.call()
            self.assertNotIn('TEST_PRIVATE_CREDENTIAL', str(raised.exception))
        self.assertEqual(list(self.root.iterdir()), [self.image])


if __name__ == '__main__':
    unittest.main()
