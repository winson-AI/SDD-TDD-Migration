"""Screenshot utilities for capturing Android device screen."""

import base64
import os
import shutil
import signal
import stat
import subprocess
import uuid
import time
from dataclasses import dataclass
from io import BytesIO

import uiautomator2 as u2

from ...logger import logger
from ...storage import output_path, temp_directory


@dataclass
class Screenshot:
    """Represents a captured screenshot."""

    base64_data: str
    layout_data: str
    width: int
    height: int
    is_sensitive: bool = False


def get_screenshot(device: u2.Device | None = None) -> Screenshot:
    """
    Capture a screenshot from the connected Android device.

    Args:
        device: uiautomator2 device instance.

    Returns:
        Screenshot object containing base64 data and dimensions.

    Capture failure raises; generated fallback pixels cannot be test evidence.
    """
    try:
        img = device.screenshot(format="pillow")
        width, height = img.size

        buffered = BytesIO()
        img.save(buffered, format="jpeg")
        base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

        try:
            layout_data = device.dump_hierarchy()
        except Exception as e:
            logger.error(f"Layout error: {e}")
            layout_data = ""

        return Screenshot(
            base64_data=base64_data, layout_data=layout_data, width=width, height=height, is_sensitive=False
        )

    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        raise RuntimeError('Android screenshot unavailable') from e




RECORD_FILE_NAME = "testing_video_assert.mp4"
DEVICE_RECORD_PATH = f"/sdcard/{RECORD_FILE_NAME}"

# Holds per-device recording session state, keyed by device serial:
# {"mode": "native", "conn": <adb shell stream>} or
# {"mode": "scrcpy", "proc": <Popen>, "tmp_path": ...}
_recording_state: dict[str, dict] = {}


def _screenrecord_available(device: u2.Device) -> bool:
    try:
        out = device.shell("which screenrecord")
        return bool(getattr(out, 'output', out).strip())
    except Exception:
        return False


def _scrcpy_available() -> bool:
    return shutil.which("scrcpy") is not None


def start_screen_record(device: u2.Device) -> None:
    if _screenrecord_available(device):
        device.shell(f"rm -f {DEVICE_RECORD_PATH}")
        # `screenrecord` must be interrupted with SIGINT (not just closing
        # the connection) to flush a playable mp4, so keep the shell
        # connection open via adbutils' stream mode and send the signal
        # explicitly in stop().
        conn = device.adb_device.shell(f"screenrecord {DEVICE_RECORD_PATH}", stream=True)
        _recording_state[device.serial] = {"mode": "native", "conn": conn}
    elif _scrcpy_available():
        logger.warning("[screen_record] 设备无 screenrecord 命令，降级为 scrcpy 真实录屏")
        _recording_state[device.serial] = _start_scrcpy_record(device)
    else:
        logger.error(
            "[screen_record] 设备无 screenrecord 命令，本机也未安装 scrcpy（brew install scrcpy），无法录屏"
        )
        _recording_state[device.serial] = {"mode": "unavailable"}


def _start_scrcpy_record(device: u2.Device) -> dict:
    """
    Real screen recording via scrcpy, for devices/ROMs that strip the
    `screenrecord` binary (e.g. some Huawei/Honor EMUI builds - confirmed on
    a real LEM-AL00: their own com.huawei.screenrecorder system app exists
    but its Start/Stop service and launcher activity are both locked behind
    signature|privileged / HW_SIGNATURE_OR_SYSTEM permissions, inaccessible
    from `adb shell`).

    scrcpy captures through the same underlying framework capture path
    `screenrecord` itself uses (not the missing CLI tool), so it works
    regardless of that OEM restriction, and writes an actual continuous
    H.264 recording straight to a local file - not a synthesized slideshow.
    """
    tmp_path = str(output_path(temp_directory() / ('scrcpy_record_' + uuid.uuid4().hex + '.mp4')))
    proc = subprocess.Popen(
        ["scrcpy", "-s", device.serial, "--no-window", "--no-audio", f"--record={tmp_path}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    # brief health check: catch an immediate failure (bad serial, scrcpy-server
    # push failure, codec unavailable, ...) rather than discovering it only at
    # stop time with an empty file and no clue why.
    time.sleep(1)
    if proc.poll() is not None:
        stderr = proc.stderr.read() if proc.stderr else ""
        logger.error(f"[screen_record] scrcpy 启动失败 (exit={proc.returncode}): {stderr[-500:]}")
    return {"mode": "scrcpy", "proc": proc, "tmp_path": tmp_path}


def _wait_for_stable_file(device: u2.Device, remote_path: str, timeout: float = 5.0) -> bool:
    """
    Poll until `remote_path` is a regular file with a size that has stopped
    growing, or `timeout` elapses.

    `screenrecord` needs a moment after SIGINT to flush the mp4 container;
    pulling before that finishes hits a real adbutils footgun: its `pull()`
    stats the remote path first and, if it doesn't exist yet (or isn't a
    regular file), silently falls back to `pull_dir()` - which creates a
    *local directory* at the destination instead of raising an error. That
    corrupted directory then surfaces much later as a confusing ffmpeg
    "Is a directory" failure in the verify step. Confirming the file is
    real and stable here avoids ever calling pull() on a bad path.
    """
    deadline = time.time() + timeout
    last_size = -1
    while time.time() < deadline:
        try:
            info = device.adb_device.sync.stat(remote_path)
            is_regular_file = bool(info.mode & stat.S_IFREG)
        except Exception:
            is_regular_file = False
            info = None

        if is_regular_file and info.size > 0 and info.size == last_size:
            return True
        last_size = info.size if info else -1
        time.sleep(0.3)
    return False


def _stop_native_record(device: u2.Device, state: dict, path: str = None) -> None:
    if path: path = str(output_path(path))
    conn = state.get("conn")
    try:
        device.shell("killall -INT screenrecord")
    except Exception as e:
        logger.warning(f"[screen_record] 停止录屏失败: {e}")
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass

    if path:
        if _wait_for_stable_file(device, DEVICE_RECORD_PATH):
            try:
                # pull_file (not pull()) - never falls back to directory
                # creation if the source path turns out not to be a file.
                device.adb_device.sync.pull_file(DEVICE_RECORD_PATH, path)
                logger.info(f"[screen_record] 录屏文件已保存到: {path}")
            except Exception as e:
                logger.error(f"[screen_record] 获取录屏文件失败: {e}")
        else:
            logger.error(
                f"[screen_record] 录屏文件未能在超时内就绪，跳过拉取: {DEVICE_RECORD_PATH}"
            )

    try:
        device.shell(f"rm -f {DEVICE_RECORD_PATH}")
    except Exception as e:
        logger.warning(f"[screen_record] 清理设备端录屏文件失败: {e}")


def _stop_scrcpy_record(state: dict, path: str = None) -> None:
    if path: path = str(output_path(path))
    proc = state["proc"]
    tmp_path = str(output_path(state["tmp_path"]))

    if proc.poll() is None:
        try:
            # SIGINT (not kill) lets scrcpy finalize the mp4 container, same
            # as screenrecord's own graceful-stop contract.
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("[screen_record] scrcpy 未在超时内退出，强制终止")
            proc.kill()
            proc.wait(timeout=5)
        except Exception as e:
            logger.warning(f"[screen_record] 停止 scrcpy 录制失败: {e}")

    if path:
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            try:
                shutil.move(tmp_path, path)
                logger.info(f"[screen_record] scrcpy 录屏文件已保存到: {path}")
            except Exception as e:
                logger.error(f"[screen_record] 保存录屏文件失败: {e}")
        else:
            stderr = proc.stderr.read() if proc.stderr else ""
            logger.error(f"[screen_record] scrcpy 录屏文件未生成: {tmp_path}. {stderr[-500:]}")

    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def stop_screen_record(device: u2.Device, path: str = None) -> None:
    if path: path = str(output_path(path))
    state = _recording_state.pop(device.serial, None)
    if state is None:
        logger.warning("[screen_record] 停止录屏时未找到活跃录制会话")
        return
    if state["mode"] == "native":
        _stop_native_record(device, state, path)
    elif state["mode"] == "scrcpy":
        _stop_scrcpy_record(state, path)
    else:
        logger.error("[screen_record] 停止录屏时发现该设备录屏能力不可用，跳过")
