"""MobileAgenticOperator's WebDriverAgent backend for the shared device protocol."""
import json
import time
from urllib.parse import urlsplit

import wda

from . import ios
from .device_protocol import DeviceProtocol
from ..logger import logger
from ..storage import output_path
from project_context import wda_endpoint
from run_storage import atomic_bytes


class IosDevice(DeviceProtocol):
    platform = "ios"

    def __init__(self, endpoint, report_generator=None, config=None, *, udid=None, observation=None, execution=None):
        self._endpoint = wda_endpoint(endpoint)
        self._url = urlsplit(self._endpoint)
        self._client = wda.Client(self._endpoint)
        self._udid = udid
        self._report_generator = report_generator
        self._recording = None
        self._teardown_callbacks = []
        self._execution = execution
        self._physical = None
        if not self._client.is_ready():
            raise ValueError("a reachable WebDriverAgent is required on the stated iOS device")
        self._info = (self._client.http.get("/wda/device/info", timeout=3).value if execution is not None
                      else self._client.device_info())
        identity = self._info.get("uuid")
        if not isinstance(identity, str) or identity in ("", "unknown"):
            raise ValueError("WebDriverAgent device UUID is required for iOS evidence")
        evidence = {"endpoint": self._endpoint, "wda_uuid": identity, "configured_udid": udid,
                    "model": self._info.get("model"), "is_simulator": self._info.get("isSimulator")}
        if execution is not None:
            from ios_evidence import check_device, deployment
            binding, baseline = execution
            if binding.get("profile") and evidence["is_simulator"] is not (binding["profile"] == "simulator"):
                raise ValueError("iOS device does not match the frozen profile")
            if evidence["is_simulator"] is False or binding.get("deployment_ref"):
                receipt = deployment(binding, baseline)
                if identity != receipt["wda_uuid"] or self._endpoint != wda_endpoint(receipt["wda_url"]):
                    raise ValueError("WDA is not attached to the provisioned iOS deployment")
                from .ios.screenshot import physical_device, physical_installation, simulator_installation
                if evidence["is_simulator"]:
                    evidence["installed"] = simulator_installation(receipt["udid"], receipt["bundle_id"])
                else:
                    self._physical = physical_device(receipt["udid"])
                    evidence["installed"] = physical_installation(self._physical, receipt["bundle_id"])
                evidence["deployment_ref"] = binding["deployment_ref"]
            check_device(binding, baseline, evidence)
        if observation:
            atomic_bytes(output_path(observation), json.dumps(evidence).encode() + b"\n")
        # Device state comes from the authorized fixture and frozen steps.
        if config and config.verify_video_enable:
            self.start_screen_record()
            if report_generator and report_generator.step_content:
                report_generator.step_content[0].timestamp = time.time()

    @property
    def device_id(self):
        return self._endpoint

    @property
    def ip(self):
        return self._url.hostname

    @property
    def port(self):
        return self._url.port or (443 if self._url.scheme == "https" else 80)

    @property
    def driver(self):
        return self._client

    def get_display_size(self):
        # facebook-wda's public fallback accepts alerts and may launch Settings.
        width, height = self._client._unsafe_window_size()
        if width <= 0 or height <= 0:
            raise RuntimeError("iOS logical screen size unavailable")
        return width, height

    def get_screenshot(self, timeout=10, save_to_report=True, *, checkpoint=False):
        bundle = self._foreground_bundle() if checkpoint and self._execution is not None else None
        screenshot = ios.get_screenshot(self._client, *self.get_display_size())
        if bundle:
            if self._foreground_bundle() != bundle:
                raise RuntimeError("iOS foreground App changed during checkpoint capture")
            screenshot.foreground_bundle_id = bundle
        if save_to_report and self._report_generator:
            events = self._report_generator.events
            screenshot.screenshot_path = self._report_generator.save_screenshot(
                screenshot.base64_data, layout_data=screenshot.layout_data,
                prefix=f"step_{events[-1].step_number if events else 0}")
        return screenshot

    def _foreground_bundle(self):
        info = self._client.app_current()
        bundle = info.get("bundleId") if info else None
        if not isinstance(bundle, str) or not bundle:
            raise RuntimeError("iOS checkpoint foreground bundle ID unavailable")
        return bundle

    def tap(self, x, y, delay=None):
        ios.tap(self._client, x, y, delay)

    def double_tap(self, x, y, delay=None):
        ios.double_tap(self._client, x, y, delay)

    def long_press(self, x, y, duration=3, delay=None):
        ios.long_press(self._client, x, y, duration, delay)

    def swipe(self, start_x, start_y, end_x, end_y, duration_s=None, delay=None):
        ios.swipe(self._client, start_x, start_y, end_x, end_y, duration_s, delay)

    def drag(self, start_x, start_y, end_x, end_y, press_time=1.5, drag_time=1):
        ios.drag(self._client, start_x, start_y, end_x, end_y, press_time, drag_time)

    def type_text(self, text):
        ios.type_text(self._client, text)

    def clear_text(self):
        ios.clear_text(self._client)

    def back(self, delay=None):
        ios.back(self._client, delay)

    def home(self, delay=None):
        ios.home(self._client, delay)

    def launch_app(self, app_name, delay=None):
        return ios.launch_app(self._client, app_name, delay)

    def stop_app(self, app_name):
        ios.stop_app(self._client, app_name)

    def get_current_app(self):
        return ios.get_current_app(self._client)

    def clear_app_data(self, app_name):
        raise NotImplementedError("use the approved iOS fixture for app data reset")

    def reset_status(self):
        ios.reset_status(self._client)

    def set_always_screen_on_enable(self):
        pass

    def set_always_screen_on_disable(self):
        pass

    def pinch_in(self, left, top, right, bottom, scale=0.4, direction="diagonal", delay=None):
        ios.pinch_in(self._client, left, top, right, bottom, scale, direction, delay, wda_url=self._endpoint)

    def pinch_out(self, left, top, right, bottom, scale=1.6, direction="diagonal", delay=None):
        ios.pinch_out(self._client, left, top, right, bottom, scale, direction, delay, wda_url=self._endpoint)

    def start_screen_record(self):
        if self._recording is not None:
            raise RuntimeError("iOS screen recording already active")
        if self._url.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("a local WDA endpoint and its attached iOS device are required for recording")
        self._recording = ios.start_screen_record(self._udid, self._info, self._physical)

    def stop_screen_record(self, path=None):
        if self._recording is None:
            raise RuntimeError("iOS screen recording was not started")
        if path is not None:
            output_path(path)
        state, self._recording = self._recording, None
        ios.stop_screen_record(state, path)

    def register_teardown_callback(self, callback):
        self._teardown_callbacks.append(callback)

    def teardown(self):
        try:
            if self._recording is not None:
                report = self._report_generator
                final = report.video_dir / "final.mp4" if report and report.video_dir else None
                self.stop_screen_record(final)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("iOS screen recording unavailable: %s", exc)
        finally:
            for callback in self._teardown_callbacks:
                try:
                    callback()
                except Exception as exc:
                    logger.warning("iOS teardown callback failed: %s", exc)
            self._teardown_callbacks.clear()
