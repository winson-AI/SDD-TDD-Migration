"""WDA screen capture and MobileAgenticOperator's simctl/AVFoundation recording."""
import base64
import json
import re
import signal
import subprocess
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


def _simulator_command(udid, name):
    devices = _device_table(["simctl", "list", "-j", "devices", "booted"])["devices"]
    matching = [row["udid"] for rows in devices.values() for row in rows
                if row.get("state") == "Booted" and row.get("name") == name]
    if len(matching) != 1 or matching[0].lower() != udid.lower():
        raise ValueError("a unique booted iOS simulator matching the WDA name and configured UDID is required for recording")
    return ["xcrun", "simctl", "io", matching[0], "recordVideo"]


def _physical_command(udid, name):
    import imageio_ffmpeg

    devices = _device_table(["devicectl", "list", "devices", "--json-output", "-"])["result"]["devices"]
    named = [row for row in devices if row.get("deviceProperties", {}).get("name") == name]
    if len(named) != 1 or udid.lower() not in {str(value or "").lower() for value in (
            named[0].get("identifier"), named[0].get("hardwareProperties", {}).get("udid"))}:
        raise ValueError("a unique connected iOS device matching the WDA name and configured UDID is required for recording")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    listing = subprocess.run([ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                             capture_output=True, text=True, timeout=15).stderr
    video_devices = listing.partition("AVFoundation video devices:")[2].partition("AVFoundation audio devices:")[0]
    indices = [index for index, label in re.findall(r"\[(\d+)]\s+([^\r\n]+)", video_devices) if label.strip() == name]
    if len(indices) != 1:
        raise ValueError("one matching iOS AVFoundation capture source is required for recording")
    return [ffmpeg, "-nostdin", "-f", "avfoundation", "-framerate", "30", "-i", f"{indices[0]}:none",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]


def start_screen_record(udid, info):
    dest = output_path(temp_directory() / ("ios-recording-" + uuid4().hex + ".mp4"))
    if not udid or not info.get("name") or type(info.get("isSimulator")) is not bool:
        raise ValueError("a configured iOS UDID and WDA device identity are required for recording")
    command = _simulator_command if info["isSimulator"] else _physical_command
    proc = subprocess.Popen([*command(udid, info["name"]), str(dest)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, dest


def stop_screen_record(state, path=None):
    target = output_path(Path(path)) if path is not None else None
    proc, source = state
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
        source.replace(output_path(target))
    else:
        source.unlink()
