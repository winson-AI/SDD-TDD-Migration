"""Machine-wide device exclusion shared by scheduling and the mobile runtime."""
from contextlib import ExitStack, contextmanager
from errno import EADDRINUSE
import socket
import time
from urllib.parse import urlsplit

from contracts import digest


class Busy(ValueError):
    pass


def ports(device, platform, udid=None, ip=None, port=None):
    if platform == 'ios':
        endpoint = urlsplit(device)
        host = 'loopback' if endpoint.hostname in ('localhost', '127.0.0.1', '::1') else endpoint.hostname
        keys = [['ios', host, endpoint.port or (443 if endpoint.scheme == 'https' else 80)]]
        if udid:
            keys.append(['ios-udid', udid.lower()])
    else:
        keys = [[platform, device]]
        if platform == 'harmony' and ip is not None:
            keys.append([device, ip, port])  # overlap with runners pinned to an older package
    return sorted({20000 + int(digest(key)[:8], 16) % 30000 for key in keys})


@contextmanager
def lock(device, platform, udid=None, ip=None, port=None, *, wait=False, still_waiting=None):
    with ExitStack() as leases:
        for number in ports(device, platform, udid, ip, port):
            lease = leases.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            while True:
                try:
                    lease.bind(('127.0.0.1', number))
                    break
                except OSError as exc:
                    if exc.errno != EADDRINUSE:
                        raise
                    if not wait:
                        raise Busy('device busy: local device lease unavailable') from exc
                    if still_waiting:
                        still_waiting()
                    time.sleep(0.2)
        yield


def available(state, path):
    """Order frozen PATHs by known leases. The runner checks its resolved device again."""
    from execute_test import builtin_platform
    from project_context import device_inputs, path_device

    platform = builtin_platform(state, path)
    if platform not in ('android', 'ios', 'harmony'):
        return True
    devices = (state.get('test_adapter') or {}).get('device') or {}
    preview = device_inputs(devices).get(path_device(path)) or {}
    device = preview.get('wda_url' if platform == 'ios' else 'serial')
    if not device:
        return True
    try:
        with lock(device, platform, preview.get('udid')):
            return True
    except Busy:
        return False
