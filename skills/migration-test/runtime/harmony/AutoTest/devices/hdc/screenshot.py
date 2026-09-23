"""Screenshot utilities for capturing HarmonyOS device screen."""

import base64
import os
from dataclasses import dataclass
from io import BytesIO

from PIL import Image
from hypium import UiDriver
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


def get_screenshot(driver: UiDriver | None = None) -> Screenshot:
    """
    Capture a screenshot from the connected HarmonyOS device.

    Args:
        driver: Optional HDC device ID for multi-device setups

    Returns:
        Screenshot object containing base64 data and dimensions.

    Note:
        If the screenshot fails (e.g., on sensitive screens like payment pages),
        a black fallback image is returned with is_sensitive=True.
    """
    temporary = temp_directory()
    try:
        page = driver.UiTree.dump_page_info(str(temporary))
        output_path(page.screenshot_path, boundary=temporary)
        output_path(page.layout_path, boundary=temporary)

        if not os.path.exists(page.screenshot_path):
            return _create_fallback_screenshot(is_sensitive=False)

        # Read JPEG image and convert to PNG for model inference
        # PIL automatically detects the image format from file content
        img = Image.open(page.screenshot_path)
        width, height = img.size

        buffered = BytesIO()
        img.save(buffered, format="jpeg")
        base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

        # Cleanup
        os.remove(page.screenshot_path)

        try:
            with open(page.layout_path, "r", encoding="utf-8") as f:
                layout_data = f.read()
        except Exception as e:
            logger.error(f"Layout error: {e}")
            layout_data = ""

        os.remove(page.layout_path)

        return Screenshot(
            base64_data=base64_data, layout_data=layout_data, width=width, height=height, is_sensitive=False
        )

    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        return _create_fallback_screenshot(is_sensitive=False)


def _create_fallback_screenshot(is_sensitive: bool) -> Screenshot:
    """Create a black fallback image when screenshot fails."""
    default_width, default_height = 1080, 2400

    black_img = Image.new("RGB", (default_width, default_height), color="black")
    buffered = BytesIO()
    black_img.save(buffered, format="PNG")
    base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return Screenshot(
        base64_data=base64_data,
        layout_data="",
        width=default_width,
        height=default_height,
        is_sensitive=is_sensitive,
    )


RECORD_FILE_NAME = "testing_video_assert.mp4"
TMP_DIR = "/data/local/tmp"


def _query_record_uris(driver: UiDriver) -> list[str]:
    """通过 mediatool query 查询录屏文件的 uri 列表。"""
    output = driver.shell(f"mediatool query {RECORD_FILE_NAME} -u")
    if not output:
        return []
    uris = []
    for line in output.strip().split("\n"):
        line = line.strip().strip('"')
        if line.startswith("file://media/"):
            uris.append(line)
    return uris


def _delete_record_by_uri(driver: UiDriver, uri: str) -> None:
    """通过 mediatool delete 删除指定 uri 的录屏文件。"""
    driver.shell(f"mediatool delete {uri}")


def start_screen_record(driver: UiDriver) -> None:
    # 启动录屏前，先停止一下，防止之前还残留录屏未结束
    driver.shell(
        'aa stop-service -b com.huawei.hmos.screenrecorder -a com.huawei.hmos.screenrecorder.ServiceExtAbility')
    driver.wait(1)

    # 启动录屏前，先查询是否有同名文件残留并删除
    for uri in _query_record_uris(driver):
        try:
            _delete_record_by_uri(driver, uri)
            logger.info(f"[screen_record] 清理残留录屏文件: {uri}")
        except Exception as e:
            logger.warning(f"[screen_record] 清理残留录屏文件失败: {uri}, 错误: {e}")

    driver.shell('aa start -b com.huawei.hmos.screenrecorder'
                 ' -a com.huawei.hmos.screenrecorder.ServiceExtAbility --ps "CustomizedFileName" "'
                 + RECORD_FILE_NAME + '"')


def stop_screen_record(driver: UiDriver, path: str = None) -> None:
    if path:
        path = str(output_path(path))
    driver.shell('aa stop-service -b com.huawei.hmos.screenrecorder -a com.huawei.hmos.screenrecorder.ServiceExtAbility')
    driver.wait(1)

    if path:
        # 通过 mediatool query 获取录屏文件 uri
        uris = _query_record_uris(driver)
        if not uris:
            logger.error(f"[screen_record] 未找到录屏文件: {RECORD_FILE_NAME}")
            return

        # 使用最后一个 uri（最新的录屏）
        uri = uris[-1]

        try:
            # 通过 mediatool recv 将文件复制到 /data/local/tmp
            driver.shell(f"mediatool recv {uri} {TMP_DIR}")
            # 从 tmp 目录拉取到本地
            tmp_file_path = f"{TMP_DIR}/{RECORD_FILE_NAME}"
            driver.pull_file(tmp_file_path, path)
            # 删除设备端媒体库中的源文件
            _delete_record_by_uri(driver, uri)
            # 删除 tmp 目录下的临时副本
            driver.shell(f"rm -rf {tmp_file_path}")
            logger.info(f"[screen_record] 录屏文件已保存到: {path}")
        except Exception as e:
            logger.error(f"[screen_record] 获取录屏文件失败: {e}")
            # 尝试清理 tmp 目录残留
            driver.shell(f"rm -rf {TMP_DIR}/{RECORD_FILE_NAME}")
    else:
        # 没有指定保存路径，直接清理设备端文件
        for uri in _query_record_uris(driver):
            _delete_record_by_uri(driver, uri)
