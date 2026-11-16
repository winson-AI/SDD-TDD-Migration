"""WDA screen capture and MobileAgenticOperator's simctl/AVFoundation recording."""
import base64
import json
import plistlib
import re
import signal
import subprocess
import time
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from ...storage import output_path, temp_directory
from ..device_protocol import Screenshot


def get_screenshot(client, width, height):
    # Preserve the native image. The executor uses WDA points, including on Retina devices.
    try:
        image = client.screenshot(format="pillow")
        buffered = BytesIO()
        image.convert("RGB").save(buffered, format="JPEG", quality=95)
        layout = client.source(format="xml")
        if not isinstance(layout, str) or not layout.lstrip().startswith("<"):
            raise ValueError("WDA did not return a UI tree")
    except Exception as exc:
        raise RuntimeError("iOS screenshot or UI tree unavailable") from exc
    return Screenshot(base64.b64encode(buffered.getvalue()).decode("ascii"), layout, width, height)


def _device_table(args):
    capture = subprocess.run(["xcrun", *args], capture_output=True, text=True, timeout=15, check=True)
    return json.loads(capture.stdout)


def physical_device(udid, *, capture=False):
    devices = _device_table(["devicectl", "list", "devices", "--json-output", "-"])["result"]["devices"]
    matching = [row for row in devices if str(row.get("hardwareProperties", {}).get("udid") or "").lower() == udid.lower()]
    if len(matching) != 1 or not matching[0].get("identifier"):
        raise ValueError("one physical iOS device with the provisioned hardware UDID is required")
    if capture:
        name = matching[0].get("deviceProperties", {}).get("name")
        if not name or sum(row.get("deviceProperties", {}).get("name") == name for row in devices) != 1:
            raise ValueError("unambiguous CoreDevice capture name required for this hardware UDID")
    return matching[0]


def physical_installation(device, bundle_id):
    reply = _device_table(["devicectl", "device", "info", "apps", "--device", device["identifier"],
                           "--bundle-id", bundle_id, "--json-output", "-"])["result"]
    installed = [app for app in reply["apps"] if app.get("bundleIdentifier") == bundle_id]
    if len(installed) != 1 or not installed[0].get("bundleVersion"):
        raise ValueError("iOS device must have the provisioned App with an observable build version")
    return {"udid": device["hardwareProperties"]["udid"], "bundle_id": bundle_id, "core_device_id": device["identifier"],
            "build_version": str(installed[0]["bundleVersion"]),
            "os_version": device.get("deviceProperties", {}).get("osVersionNumber")}


def simulator_installation(udid, bundle_id):
    reply = subprocess.run(["xcrun", "simctl", "get_app_container", udid, bundle_id, "app"],
                           capture_output=True, text=True, check=True, timeout=10)
    with (Path(reply.stdout.strip()) / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    return {"udid": udid, "bundle_id": info["CFBundleIdentifier"], "build_version": str(info["CFBundleVersion"])}


def _simulator_command(udid, name):
    devices = _device_table(["simctl", "list", "-j", "devices", "booted"])["devices"]
    matching = [row["udid"] for rows in devices.values() for row in rows
                if row.get("state") == "Booted" and row.get("name") == name]
    if len(matching) != 1 or matching[0].lower() != udid.lower():
        raise ValueError("a unique booted iOS simulator matching the WDA name and configured UDID is required for recording")
    return ["xcrun", "simctl", "io", matching[0], "recordVideo"]


def _physical_command(udid):
    import imageio_ffmpeg

    device = physical_device(udid, capture=True)
    name = device["deviceProperties"]["name"]
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    listing = subprocess.run([ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                             capture_output=True, text=True, timeout=15).stderr
    video_devices = listing.partition("AVFoundation video devices:")[2].partition("AVFoundation audio devices:")[0]
    indices = [index for index, label in re.findall(r"\[(\d+)]\s+([^\r\n]+)", video_devices) if label.strip() == name]
    if len(indices) != 1:
        raise ValueError("one matching iOS AVFoundation capture source is required for recording")
    return ([ffmpeg, "-nostdin", "-f", "avfoundation", "-framerate", "30", "-i", f"{indices[0]}:none",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"],
            {"backend": "avfoundation", "core_device_id": device["identifier"], "capture_index": int(indices[0]), "capture_name": name})


def start_screen_record(udid, info, physical=None):
    dest = output_path(temp_directory() / ("ios-recording-" + uuid4().hex + ".mp4"))
    if not udid or type(info.get("isSimulator")) is not bool:
        raise ValueError("a configured iOS UDID and WDA device identity are required for recording")
    progress = None
    if info["isSimulator"]:
        command = _simulator_command(udid, info.get("name"))
        source = {"backend": "simctl"}
    else:
        if not physical:
            raise ValueError("iOS physical recording requires a deployment-bound WDA device")
        command, source = _physical_command(udid)
        if source["core_device_id"] != physical["identifier"]:
            raise ValueError("iOS capture device differs from the deployment")
        progress = dest.with_suffix(".progress")
        command.extend(["-progress", str(progress), "-stats_period", "0.1"])
    started = time.time()
    proc = subprocess.Popen([*command, str(dest)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if progress:
        deadline = time.monotonic() + 8
        try:
            while proc.poll() is None and time.monotonic() < deadline:
                if progress.is_file():
                    times = re.findall(r"^out_time_us=(\d+)$", progress.read_text(), re.M)
                    if times and int(times[-1]) > 0:
                        started = time.time() - int(times[-1]) / 1_000_000
                        break
                time.sleep(0.05)
            else:
                raise RuntimeError("iOS AVFoundation capture did not deliver frames")
        except BaseException:
            proc.kill()
            proc.wait(timeout=5)
            raise
    return proc, dest, progress, {**source, "started_at": started, "udid": udid, "wda_uuid": info["uuid"]}


def stop_screen_record(state, path=None):
    target = output_path(Path(path)) if path is not None else None
    proc, source, progress, facts = state
    stopped_at = time.time()
    stopping = proc.poll() is None
    try:
        if stopping:
            proc.send_signal(signal.SIGINT)
        code = proc.wait(timeout=12)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait(timeout=5)
        raise RuntimeError("iOS recording did not finalize after stop") from exc
    source = output_path(source)
    if (code != 0 and not (stopping and code in (-signal.SIGINT, 255))) or not source.is_file() or not source.stat().st_size:
        raise RuntimeError("iOS recording did not produce video")
    if target:
        import cv2
        video = cv2.VideoCapture(str(source))
        try:
            frames, fps = video.get(cv2.CAP_PROP_FRAME_COUNT), video.get(cv2.CAP_PROP_FPS)
            readable, _ = video.read()
            if not readable or not frames > 0 or not fps > 0:
                raise RuntimeError("iOS recording is not decodable")
            if frames > 1:
                video.set(cv2.CAP_PROP_POS_FRAMES, int(frames) - 1)
                if not video.read()[0]:
                    raise RuntimeError("iOS recording is missing its final frame")
        finally:
            video.release()
        source.replace(output_path(target))
        from contracts import file_ref
        from run_storage import atomic_bytes
        duration = frames / fps
        if facts["backend"] == "simctl":
            # simctl can spend part of the launch interval preparing its encoder.
            facts["started_at"] = max(facts["started_at"], stopped_at - duration)
        facts.update(video_ref=file_ref(target), decoded_duration=duration,
                     ended_at=min(stopped_at, facts["started_at"] + duration))
        atomic_bytes(output_path(target.with_suffix(".ios-capture.json")), json.dumps(facts).encode() + b"\n")
    else:
        source.unlink()
    if progress:
        progress.unlink(missing_ok=True)
