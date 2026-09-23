import random
import os
import asyncio
from PIL import Image, ImageDraw
from hypium import UiDriver
import cv2
import numpy as np
import time
from AutoTest.logger import logger
from AutoTest.storage import output_path as managed_output, temp_directory
from AutoTest.layered_agent_cli.mcp_tools import collect_function_tool, get_driver


def generate_random_gradient_image(width=1920, height=1080, output_path="gradient_image.jpg"):
    """
    Generates an image with a random vertical gradient.
    """
    output_path = str(managed_output(output_path))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    r1, g1, b1 = [random.randint(0, 255) for _ in range(3)]
    r2, g2, b2 = [random.randint(0, 255) for _ in range(3)]

    # Draw the gradient line by line
    for i in range(height):
        r = int(r1 + (r2 - r1) * i / height)
        g = int(g1 + (g2 - g1) * i / height)
        b = int(b1 + (b2 - b1) * i / height)
        draw.line([(0, i), (width, i)], fill=(r, g, b))

    image.save(output_path)
    logger.info(f"Image saved to {output_path}")


def generate_random_gradient_video(width=1920, height=1080, duration=5, fps=30, output_path="gradient_video.mp4"):
    """
    Generates a video with a changing random vertical gradient.
    Requires opencv-python and numpy.
    """

    output_path = str(managed_output(output_path))
    # Check if output directory exists, if not create it (based on path)
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    # Initial colors
    c1 = np.array([random.randint(0, 255) for _ in range(3)], dtype=float)
    c2 = np.array([random.randint(0, 255) for _ in range(3)], dtype=float)

    # Target colors to shift towards
    t1 = np.array([random.randint(0, 255) for _ in range(3)], dtype=float)
    t2 = np.array([random.randint(0, 255) for _ in range(3)], dtype=float)

    frames = duration * fps

    # Pre-compute vertical gradient factor
    # y shape: (height, 1, 1) to broadcast against color arrays (3,) -> (height, 1, 3)
    y = np.linspace(0, 1, height).reshape(height, 1, 1)

    logger.info(f"Generating video: {width}x{height}, {duration}s, {fps}fps")

    for f in range(frames):
        # Interpolate current colors towards target
        # Using a sine wave or just linear? Linear is fine for "random change"
        # Let's make it more dynamic by using sine wave for interpolation factor
        # to create a smooth back-and-forth or loop effect if needed, 
        # but linear transition to a new random color is also fine.

        alpha = f / frames

        curr_c1 = c1 + (t1 - c1) * alpha
        curr_c2 = c2 + (t2 - c2) * alpha

        # Create 1-pixel wide vertical gradient column
        # Formula: (1 - y) * top_color + y * bottom_color
        col_gradient = ((1 - y) * curr_c1 + y * curr_c2).astype(np.uint8)

        # Resize to full width (stretches horizontally)
        # cv2.resize expects (width, height)
        frame = cv2.resize(col_gradient, (width, height))

        # Convert RGB to BGR for OpenCV
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        out.write(frame_bgr)

    out.release()
    logger.info(f"Video saved to {output_path}")


def clear_media_file(driver: UiDriver) -> None:
    ls_result = driver.shell("ls /mnt/data/100/media_fuse/Photo")
    ls_result_list = ls_result.split("\n")
    for i in ls_result_list:
        ret = driver.shell("rm -rf /mnt/data/100/media_fuse/Photo/{}".format(i))
        logger.info("delete ret: {}".format(ret))


def send_file_to_media(driver: UiDriver, file_path: str):
    file_name = os.path.basename(file_path)
    ret = driver.push_file(file_path, "/mnt/data/100/media_fuse/Photo/相机/{}".format(file_name))
    logger.info("push ret: {}".format(ret))


def _generate_random_gradient_image_to_device() -> str:
    driver = get_driver()
    tmp_file = str(temp_directory() / f"{time.time_ns()}.jpeg")
    try:
        generate_random_gradient_image(output_path=tmp_file)
        if os.path.exists(tmp_file):
            clear_media_file(driver)
            send_file_to_media(driver, tmp_file)
    finally:
        if os.path.exists(tmp_file):
            os.unlink(tmp_file)

    return "send image to media successfully"


@collect_function_tool
async def generate_random_gradient_image_to_device() -> str:
    """创建一个渐变的图片到手机相册"""
    return await asyncio.to_thread(_generate_random_gradient_image_to_device)


def _generate_random_gradient_video_to_device() -> str:
    driver = get_driver()
    tmp_file = str(temp_directory() / f"{time.time_ns()}.mp4")
    try:
        generate_random_gradient_video(output_path=tmp_file)
        if os.path.exists(tmp_file):
            clear_media_file(driver)
            send_file_to_media(driver, tmp_file)
    finally:
        if os.path.exists(tmp_file):
            os.unlink(tmp_file)

    return "send video to media successfully"


@collect_function_tool
async def generate_random_gradient_video_to_device() -> str:
    """创建一个渐变的视频到手机相册"""
    return await asyncio.to_thread(_generate_random_gradient_video_to_device)


if __name__ == "__main__":
    generate_random_gradient_image()
    generate_random_gradient_video()
