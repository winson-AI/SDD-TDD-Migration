"""
视频工具模块
提供视频合并、处理等功能
使用 ffmpeg-python + imageio-ffmpeg 实现
ffmpeg-python 提供 Pythonic API，imageio-ffmpeg 提供跨平台 ffmpeg 二进制
"""

import base64
import json
import mimetypes
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Union
from datetime import datetime
import ffmpeg
import imageio_ffmpeg
from ..logger import logger

# 配置 ffmpeg 使用 imageio-ffmpeg 提供的二进制文件
os.environ['FFMPEG_BINARY'] = imageio_ffmpeg.get_ffmpeg_exe()


def get_ffmpeg_path() -> str:
    """
    获取 imageio-ffmpeg 提供的 ffmpeg 可执行文件路径

    Returns:
        ffmpeg 可执行文件的绝对路径
    """
    return imageio_ffmpeg.get_ffmpeg_exe()


def get_video_duration(video_path: Union[str, Path]) -> float:
    """
    使用 ffmpeg 获取视频时长（秒）

    Args:
        video_path: 视频文件路径

    Returns:
        视频时长（秒），失败时返回 0.0
    """
    video_path = Path(video_path)
    if not video_path.exists():
        return 0.0

    try:
        ffmpeg_path = get_ffmpeg_path()
        result = subprocess.run(
            [ffmpeg_path, "-i", str(video_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30
        )
        for line in result.stderr.split("\n"):
            if "Duration" in line:
                duration_str = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = duration_str.split(":")
                return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception as e:
        logger.warning(f"获取视频时长失败: {video_path}, 错误: {e}")
    return 0.0


def get_video_size(video_path: Union[str, Path]) -> tuple:
    """
    获取视频宽高

    Args:
        video_path: 视频文件路径

    Returns:
        (宽, 高) 元组，失败时返回 (0, 0)
    """
    video_path = Path(video_path)
    if not video_path.exists():
        return 0, 0

    try:
        ffmpeg_path = get_ffmpeg_path()
        result = subprocess.run(
            [ffmpeg_path, "-i", str(video_path)],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=30
        )
        for line in result.stderr.split("\n"):
            if "Stream #0:" in line and "Video:" in line:
                m = re.search(r'(\d{2,5})x(\d{2,5})', line)
                if m:
                    return int(m.group(1)), int(m.group(2))
    except Exception as e:
        logger.warning(f"获取视频尺寸失败: {video_path}, 错误: {e}")
    return 0, 0


def is_portrait_video(video_path: Union[str, Path]) -> bool:
    """
    判断视频是否为竖屏（高 >= 宽）

    Args:
        video_path: 视频文件路径

    Returns:
        True 表示竖屏，False 表示横屏或无法判断
    """
    w, h = get_video_size(video_path)
    if w == 0 or h == 0:
        return True  # 默认按竖屏处理
    return h >= w


# ============================================================================
# 片段元数据管理
# ============================================================================

def _get_segment_metadata_path(dir_path: str) -> Path:
    """获取片段元数据文件路径"""
    return Path(dir_path) / "_segment_starts.json"


def _load_segment_metadata(dir_path: str) -> dict:
    """加载片段元数据"""
    meta_path = _get_segment_metadata_path(dir_path)
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载片段元数据失败: {e}")
    return {"segments": [], "next_segment_start": None}


def _save_segment_metadata(dir_path: str, metadata: dict) -> None:
    """保存片段元数据"""
    meta_path = _get_segment_metadata_path(dir_path)
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存片段元数据失败: {e}")


def record_segment_start(dir_path: str, segment_file: str,
                         default_start_timestamp: float,
                         next_segment_start: Optional[float] = None) -> None:
    """
    记录片段元数据：已停止片段的开始时间戳和新片段的开始时间戳

    自动使用上一片段记录的 next_segment_start 作为当前片段的开始时间，
    如果不存在则使用 default_start_timestamp。

    Args:
        dir_path: 视频目录路径
        segment_file: 已停止的片段文件名
        default_start_timestamp: 默认开始时间戳（当无上一片段记录时使用，通常是 task_start_timestamp）
        next_segment_start: 新片段录制开始的 Unix 时间戳（如果有）
    """
    meta = _load_segment_metadata(dir_path)
    segments = meta.get("segments", [])
    prev_next_segment_start = meta.get("next_segment_start")

    # 确定当前片段的开始时间戳：优先使用上一片段记录的 next_segment_start
    if prev_next_segment_start is not None:
        seg_start = prev_next_segment_start
    else:
        seg_start = default_start_timestamp

    # 避免重复记录
    if not any(s["file"] == segment_file for s in segments):
        segments.append({
            "file": segment_file,
            "start_timestamp": seg_start
        })

    meta = {
        "segments": segments,
        "next_segment_start": next_segment_start
    }
    _save_segment_metadata(dir_path, meta)
    logger.debug(f"记录片段元数据: file={segment_file}, start={seg_start}, next_start={next_segment_start}")


# ============================================================================
# 时间映射表
# ============================================================================

def build_time_mapping(segment_files: List[Path], segment_starts: dict,
                       task_start_timestamp: float) -> dict:
    """
    构建时间映射表：真实时间戳 → 合并视频中的位置（秒）

    Args:
        segment_files: 按顺序排列的片段文件路径列表
        segment_starts: {文件名: 开始时间戳} 字典
        task_start_timestamp: 任务开始时间戳（用于回退默认值）

    Returns:
        时间映射表字典
    """
    segments = []
    merged_offset = 0.0

    for seg_path in segment_files:
        seg_name = seg_path.name
        start_ts = segment_starts.get(seg_name, task_start_timestamp)
        duration = get_video_duration(seg_path)

        if duration <= 0:
            logger.warning(f"片段 {seg_name} 时长探测失败（{duration}），放弃时间映射表，回退到时间戳差值计算")
            return None

        segments.append({
            "file": seg_name,
            "start_timestamp": start_ts,
            "duration": duration,
            "merged_start": merged_offset,
            "merged_end": merged_offset + duration
        })
        merged_offset += duration

    logger.info(f"构建时间映射表: {len(segments)} 个片段, 合并后总时长 {merged_offset:.2f}s")
    for seg in segments:
        logger.debug(f"  片段 {seg['file']}: 真实开始={seg['start_timestamp']:.2f}, "
                      f"时长={seg['duration']:.2f}s, 合并位置={seg['merged_start']:.2f}-{seg['merged_end']:.2f}")

    return {
        "task_start_timestamp": task_start_timestamp,
        "segments": segments
    }


def _get_mapping_sidecar_path(merged_video_path: Union[str, Path]) -> Path:
    """获取映射表 sidecar 文件路径"""
    video_path = Path(merged_video_path)
    return video_path.with_suffix(".mapping.json")


def _save_time_mapping(mapping: dict, merged_video_path: Union[str, Path]) -> None:
    """保存时间映射表到 sidecar 文件"""
    mapping_path = _get_mapping_sidecar_path(merged_video_path)
    try:
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        logger.debug(f"时间映射表已保存: {mapping_path}")
    except Exception as e:
        logger.warning(f"保存时间映射表失败: {e}")


def _load_time_mapping(merged_video_path: Union[str, Path]) -> Optional[dict]:
    """从 sidecar 文件加载时间映射表"""
    mapping_path = _get_mapping_sidecar_path(merged_video_path)
    if mapping_path.exists():
        try:
            with open(mapping_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载时间映射表失败: {e}")
    return None


def map_timestamp_to_position(timestamp: float, mapping: dict) -> float:
    """
    将真实时间戳映射到合并视频中的位置（秒）

    Args:
        timestamp: 真实 Unix 时间戳
        mapping: 时间映射表

    Returns:
        合并视频中的位置（秒）
    """
    segments = mapping.get("segments", [])
    if not segments:
        task_start = mapping.get("task_start_timestamp", 0)
        return max(0.0, timestamp - task_start)

    # 在片段内查找
    for seg in segments:
        seg_start = seg["start_timestamp"]
        seg_end = seg_start + seg["duration"]
        if seg_start <= timestamp <= seg_end:
            return seg["merged_start"] + (timestamp - seg_start)

    # 在间隙中：返回前一个片段的结束位置
    for i in range(1, len(segments)):
        prev_end = segments[i - 1]["start_timestamp"] + segments[i - 1]["duration"]
        curr_start = segments[i]["start_timestamp"]
        if prev_end < timestamp < curr_start:
            logger.debug(f"时间戳 {timestamp} 落在间隙中 (gap: {prev_end:.2f}-{curr_start:.2f})，"
                         f"使用前一片段结束位置 {segments[i - 1]['merged_end']:.2f}")
            return segments[i - 1]["merged_end"]

    # 在第一个片段之前
    if timestamp < segments[0]["start_timestamp"]:
        logger.debug(f"时间戳 {timestamp} 在第一个片段之前，使用位置 0")
        return 0.0

    # 在最后一个片段之后
    logger.debug(f"时间戳 {timestamp} 在最后一个片段之后，使用末尾位置 {segments[-1]['merged_end']:.2f}")
    return segments[-1]["merged_end"]


def encode_video_base64(video_path: Union[str, Path]) -> str:
    """
    将视频文件读取为 base64 字符串

    Args:
        video_path: 视频文件路径

    Returns:
        base64 编码后的视频内容
    """
    video_path = Path(video_path)
    if not video_path.exists():
        logger.error(f"视频文件不存在: {video_path}")
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    with open(video_path, "rb") as video_file:
        return base64.b64encode(video_file.read()).decode("utf-8")


def get_video_mime_type(video_path: Union[str, Path]) -> str:
    """
    根据文件扩展名推断视频 MIME 类型

    Args:
        video_path: 视频文件路径

    Returns:
        可用于 data URL 的 MIME 类型
    """
    mime_type, _ = mimetypes.guess_type(str(video_path))
    if mime_type and mime_type.startswith("video/"):
        return mime_type
    return "video/mp4"


def prepare_video_for_verification(
        video_path: Union[str, Path],
        start_time: Union[int, float, None] = None,
        end_time: Union[int, float, None] = None,
        task_start_timestamp: Union[int, float, None] = None,
        output_path: Union[str, Path, None] = None,
        re_encode: bool = True,
) -> str:
    """
    为视频验证准备输入视频。

    如果未提供时间范围，则直接返回原视频路径；如果提供了时间范围，则裁剪出对应片段。

    Args:
        video_path: 原始视频路径
        start_time: 裁剪开始时间，可为 Unix 时间戳或相对秒数
        end_time: 裁剪结束时间，可为 Unix 时间戳或相对秒数
        task_start_timestamp: 任务开始时间戳，用于将 Unix 时间戳转换为视频相对秒数
        output_path: 裁剪输出路径；为空时自动创建临时文件
        re_encode: 裁剪时是否重新编码

    Returns:
        可直接用于验证的视频文件路径
    """
    video_path = Path(video_path)
    if not video_path.exists():
        logger.error(f"视频文件不存在: {video_path}")
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    if start_time is None or end_time is None:
        return str(video_path.absolute())

    if output_path is None:
        with tempfile.NamedTemporaryFile(suffix=video_path.suffix or ".mp4", delete=False) as temp_file:
            output_path = temp_file.name

    if task_start_timestamp is not None:
        return trim_video_by_timestamps(
            video_path=video_path,
            output_path=output_path,
            task_start_timestamp=task_start_timestamp,
            trim_start_timestamp=start_time,
            trim_end_timestamp=end_time,
            re_encode=re_encode,
        )

    return trim_video_by_seconds(
        video_path=video_path,
        output_path=output_path,
        start_seconds=start_time,
        end_seconds=end_time,
        re_encode=re_encode,
    )


def merge_videos(
        video_paths: List[Union[str, Path]],
        output_path: Union[str, Path],
        re_encode: bool = False,
        delete_temp: bool = False
) -> str:
    """
    合并多个视频文件为一个视频
    
    Args:
        video_paths: 视频文件路径列表
        output_path: 输出视频文件路径
        re_encode: 是否重新编码（当视频编码不一致时需要设为 True）
        delete_temp: 是否在合并完成后删除源视频文件
    
    Returns:
        输出视频文件的绝对路径
    
    Raises:
        ValueError: 当视频路径列表为空或输出路径无效时
        FileNotFoundError: 当输入视频文件不存在时
        RuntimeError: 当 ffmpeg 执行失败时
    
    Example:
        >>> merge_videos(["1.mp4", "2.mp4"], "merged.mp4")
        >>> merge_videos(["1.mp4", "2.mp4", "3.mp4"], "output/merged.mp4")
    """
    if not video_paths:
        raise ValueError("视频路径列表不能为空")

    # 转换为 Path 对象
    video_paths = [Path(p) for p in video_paths]
    output_path = Path(output_path)

    logger.info(f"开始合并视频，共 {len(video_paths)} 个文件")
    logger.debug(f"输入视频: {[str(p) for p in video_paths]}")
    logger.debug(f"输出路径: {output_path}")
    logger.debug(f"重新编码: {re_encode}")

    # 验证所有输入文件是否存在
    for video_path in video_paths:
        if not video_path.exists():
            logger.error(f"视频文件不存在: {video_path}")
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        logger.debug(f"验证文件存在: {video_path}")

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug(f"输出目录已创建: {output_path.parent}")

    if re_encode:
        logger.info("使用重新编码模式合并视频")
        _merge_with_re_encode(video_paths, output_path)
    else:
        # 检测各片段方向是否一致；不一致则强制统一方向（旋转+重编码）后再合并
        orientations = [is_portrait_video(vp) for vp in video_paths]
        if len(set(orientations)) > 1:
            logger.info(f"检测到片段方向不一致（竖屏{sum(orientations)}个/横屏{len(orientations)-sum(orientations)}个混用），"
                        f"使用统一竖屏方向合并（横屏片段将旋转90度）")
            _merge_unified_orientation(video_paths, output_path, target_orientation="portrait")
        else:
            logger.info("使用无损合并模式（concat demuxer）")
            _merge_with_concat(video_paths, output_path)

    # 可选：删除源文件
    if delete_temp:
        logger.info(f"删除临时视频文件")
        for video_path in video_paths:
            video_path.unlink()
            logger.debug(f"已删除: {video_path}")

    logger.info(f"视频合并成功: {output_path.absolute()}")

    return str(output_path.absolute())


def _merge_with_concat(video_paths: List[Path], output_path: Path) -> None:
    """
    使用 concat demuxer 方法合并视频（无损，速度快）
    适用于相同编码格式的视频
    """
    # 创建临时文件列表
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        for video_path in video_paths:
            # 使用绝对路径并转义
            abs_path = video_path.absolute()
            # Windows 路径需要特殊处理
            path_str = str(abs_path).replace('\\', '/')
            f.write(f"file '{path_str}'\n")
        temp_file = f.name

    logger.debug(f"创建临时文件列表: {temp_file}")

    try:
        ffmpeg_path = get_ffmpeg_path()
        logger.debug(f"使用 ffmpeg: {ffmpeg_path}")

        # 使用 ffmpeg-python 构建 concat 命令
        (
            ffmpeg
            .input(temp_file, format='concat', safe=0)
            .output(str(output_path), c='copy')
            .overwrite_output()
            .run(cmd=ffmpeg_path, quiet=True)
        )
        logger.debug("ffmpeg 命令执行完成")
    except ffmpeg.Error as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"ffmpeg 合并视频失败: {error_msg}")
        raise RuntimeError(f"ffmpeg 合并视频失败: {error_msg}")
    finally:
        # 清理临时文件
        os.unlink(temp_file)
        logger.debug(f"已清理临时文件: {temp_file}")


def _merge_with_re_encode(video_paths: List[Path], output_path: Path) -> None:
    """
    重新编码并合并视频
    适用于不同编码格式的视频
    """
    # 创建临时文件列表
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        for video_path in video_paths:
            abs_path = video_path.absolute()
            path_str = str(abs_path).replace('\\', '/')
            f.write(f"file '{path_str}'\n")
        temp_file = f.name

    logger.debug(f"创建临时文件列表: {temp_file}")

    try:
        ffmpeg_path = get_ffmpeg_path()
        logger.debug(f"使用 ffmpeg: {ffmpeg_path}")

        # 使用 ffmpeg-python 构建重新编码命令
        (
            ffmpeg
            .input(temp_file, format='concat', safe=0)
            .output(str(output_path), vcodec='libx264', acodec='aac')
            .overwrite_output()
            .run(cmd=ffmpeg_path, quiet=True)
        )
        logger.debug("ffmpeg 命令执行完成")
    except ffmpeg.Error as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"ffmpeg 合并视频失败: {error_msg}")
        raise RuntimeError(f"ffmpeg 合并视频失败: {error_msg}")
    finally:
        # 清理临时文件
        os.unlink(temp_file)
        logger.debug(f"已清理临时文件: {temp_file}")


def _merge_unified_orientation(video_paths: List[Path], output_path: Path,
                               target_orientation: str = "portrait") -> None:
    """
    统一所有片段方向后合并（重编码模式）
    横屏片段旋转90度，统一帧率和分辨率，使用 concat 滤镜拼接

    适用于录屏过程中设备旋转导致片段方向不一致（横竖屏混用）的场景

    Args:
        video_paths: 视频片段路径列表
        output_path: 输出视频路径
        target_orientation: 目标方向，"portrait" 竖屏 或 "landscape" 横屏
    """
    # 获取每个片段的尺寸，判断方向
    seg_infos = []
    for vp in video_paths:
        w, h = get_video_size(vp)
        is_portrait = h >= w
        seg_infos.append((vp, w, h, is_portrait))
        logger.debug(f"片段 {vp.name}: {w}x{h}, {'竖屏' if is_portrait else '横屏'}")

    # 确定目标尺寸：取与目标方向一致的首个片段尺寸；若没有则用首个片段旋转后的尺寸
    target_w, target_h = 0, 0
    for vp, w, h, is_portrait in seg_infos:
        if (target_orientation == "portrait" and is_portrait) or \
           (target_orientation == "landscape" and not is_portrait):
            target_w, target_h = w, h
            break
    if target_w == 0 or target_h == 0:
        _, w0, h0, _ = seg_infos[0]
        if target_orientation == "portrait":
            target_w, target_h = min(w0, h0), max(w0, h0)
        else:
            target_w, target_h = max(w0, h0), min(w0, h0)

    target_fps = 30
    logger.info(f"统一方向合并: 目标方向={'竖屏' if target_orientation == 'portrait' else '横屏'}, "
                f"目标尺寸={target_w}x{target_h}, 目标fps={target_fps}")

    # 构造 filter_complex：对每个输入旋转+统一尺寸+统一帧率
    v_filter_parts = []
    v_labels = []
    for idx, (vp, w, h, is_portrait) in enumerate(seg_infos):
        need_rotate = (target_orientation == "portrait" and not is_portrait) or \
                      (target_orientation == "landscape" and is_portrait)
        parts = [f"[{idx}:v]"]
        if need_rotate:
            parts.append("transpose=1,")  # 顺时针旋转90度
        parts.append(f"scale={target_w}:{target_h}:flags=bicubic,setsar=1,fps={target_fps},format=yuv420p")
        v_filter_parts.append("".join(parts) + f"[v{idx}]")
        v_labels.append(f"[v{idx}]")

    # 视频拼接
    v_concat = "".join(v_labels) + f"concat=n={len(video_paths)}:v=1:a=0[vout]"

    # 音频拼接（重采样对齐，避免时间戳错乱）
    a_filter_parts = []
    a_labels = []
    for idx in range(len(video_paths)):
        a_filter_parts.append(f"[{idx}:a]aresample=async=1:first_pts=0[a{idx}]")
        a_labels.append(f"[a{idx}]")
    a_concat = "".join(a_labels) + f"concat=n={len(video_paths)}:v=0:a=1[aout]"

    filter_complex = ";".join(v_filter_parts + [v_concat] + a_filter_parts + [a_concat])

    # 构造 ffmpeg 命令
    cmd = [get_ffmpeg_path()]
    for vp in video_paths:
        cmd.extend(["-i", str(vp)])
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-crf", "23", "-preset", "medium",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(output_path), "-y",
    ])

    logger.debug(f"ffmpeg 统一方向合并命令构造完成，共 {len(video_paths)} 个输入")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1200
        )
        if result.returncode != 0:
            error_msg = result.stderr[-3000:] if result.stderr else "未知错误"
            logger.error(f"统一方向合并失败: {error_msg}")
            raise RuntimeError(f"统一方向合并失败: {error_msg[-500:]}")
        logger.debug("统一方向合并命令执行完成")
    except subprocess.TimeoutExpired:
        logger.error("统一方向合并超时")
        raise RuntimeError("统一方向合并超时")


def merge_videos_simple(
        video_paths: List[Union[str, Path]],
        output_path: Union[str, Path]
) -> str:
    """
    简单合并视频的便捷方法
    
    Args:
        video_paths: 视频文件路径列表
        output_path: 输出视频文件路径
    
    Returns:
        输出视频文件的绝对路径
    """
    return merge_videos(video_paths, output_path, re_encode=False)


def trim_video_by_timestamp(
        video_path: Union[str, Path],
        output_path: Union[str, Path],
        start_timestamp: Union[int, float],
        end_timestamp: Union[int, float],
        video_start_timestamp: Union[int, float, None] = None,
        re_encode: bool = False
) -> str:
    """
    根据 Unix 时间戳裁剪视频
    
    Args:
        video_path: 输入视频文件路径
        output_path: 输出视频文件路径
        start_timestamp: 裁剪开始的 Unix 时间戳（秒）
        end_timestamp: 裁剪结束的 Unix 时间戳（秒）
        video_start_timestamp: 视频开始的 Unix 时间戳，如果不提供则从视频元数据中获取创建时间
        re_encode: 是否重新编码（默认 False，使用无损裁剪）
    
    Returns:
        输出视频文件的绝对路径
    
    Raises:
        FileNotFoundError: 当输入视频文件不存在时
        ValueError: 当时间戳无效时
        RuntimeError: 当 ffmpeg 执行失败时
    
    Example:
        >>> # 裁剪视频从时间戳 1710844800 到 1710845100
        >>> trim_video_by_timestamp("input.mp4", "output.mp4", 1710844800, 1710845100)
        >>> 
        >>> # 指定视频开始时间戳
        >>> trim_video_by_timestamp("input.mp4", "output.mp4", 1710844800, 1710845100, video_start_timestamp=1710844700)
    """
    video_path = Path(video_path)
    output_path = Path(output_path)

    logger.info(f"开始裁剪视频: {video_path}")
    logger.debug(f"输出路径: {output_path}")
    logger.debug(f"开始时间戳: {start_timestamp}")
    logger.debug(f"结束时间戳: {end_timestamp}")
    logger.debug(f"视频开始时间戳: {video_start_timestamp}")

    # 验证输入文件存在
    if not video_path.exists():
        logger.error(f"视频文件不存在: {video_path}")
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    # 验证时间戳有效性
    if end_timestamp <= start_timestamp:
        logger.error(f"结束时间戳必须大于开始时间戳: {end_timestamp} <= {start_timestamp}")
        raise ValueError("结束时间戳必须大于开始时间戳")

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug(f"输出目录已创建: {output_path.parent}")

    # 计算相对于视频开始的秒数
    if video_start_timestamp is not None:
        relative_start = start_timestamp - video_start_timestamp
        relative_end = end_timestamp - video_start_timestamp
    else:
        # 如果没有提供视频开始时间戳，假设视频从时间 0 开始
        # 这种情况下 start_timestamp 和 end_timestamp 应该是相对于视频开始的秒数
        relative_start = start_timestamp
        relative_end = end_timestamp
        logger.warning("未提供 video_start_timestamp，假设时间戳为相对于视频开始的秒数")

    # 验证相对时间有效性
    if relative_start < 0:
        logger.warning(f"开始时间戳在视频开始之前，调整为 0")
        relative_start = 0

    if relative_end < 0:
        logger.error(f"结束时间戳在视频开始之前，无法裁剪")
        raise ValueError("结束时间戳在视频开始之前，无法裁剪")

    duration = relative_end - relative_start
    logger.info(f"裁剪时间段: {relative_start:.2f}s - {relative_end:.2f}s (时长: {duration:.2f}s)")

    # 执行裁剪
    _trim_video(video_path, output_path, relative_start, relative_end, re_encode)

    logger.info(f"视频裁剪成功: {output_path.absolute()}")
    return str(output_path.absolute())


def trim_video_by_timestamps(
        video_path: Union[str, Path],
        output_path: Union[str, Path],
        task_start_timestamp: Union[int, float],
        trim_start_timestamp: Union[int, float],
        trim_end_timestamp: Union[int, float],
        re_encode: bool = False
) -> str:
    """
    根据三个 Unix 时间戳裁剪视频
    
    Args:
        video_path: 输入视频文件路径
        output_path: 输出视频文件路径
        task_start_timestamp: 任务开始时间的 Unix 时间戳（对应视频的 0 秒）
        trim_start_timestamp: 需要裁剪开始的 Unix 时间戳
        trim_end_timestamp: 需要裁剪结束的 Unix 时间戳
        re_encode: 是否重新编码（默认 False，使用无损裁剪）
    
    Returns:
        输出视频文件的绝对路径
    
    Raises:
        FileNotFoundError: 当输入视频文件不存在时
        ValueError: 当时间戳无效时
        RuntimeError: 当 ffmpeg 执行失败时
    
    Example:
        >>> # 任务从时间戳 1710844700 开始（视频 0 秒）
        >>> # 裁剪从时间戳 1710844800 到 1710845100 的片段
        >>> trim_video_by_timestamps("input.mp4", "output.mp4", 1710844700, 1710844800, 1710845100)
    """
    logger.info(f"开始根据时间戳裁剪视频: {video_path}")
    logger.debug(f"任务开始时间戳: {task_start_timestamp}")
    logger.debug(f"裁剪开始时间戳: {trim_start_timestamp}")
    logger.debug(f"裁剪结束时间戳: {trim_end_timestamp}")

    # 尝试加载时间映射表（用于合并视频的正确时间映射）
    mapping = _load_time_mapping(video_path)
    if mapping:
        # 使用映射表将真实时间戳转换为合并视频中的正确位置
        start_seconds = map_timestamp_to_position(trim_start_timestamp, mapping)
        end_seconds = map_timestamp_to_position(trim_end_timestamp, mapping)
        logger.info(f"使用时间映射表计算裁剪位置: {start_seconds:.2f}s - {end_seconds:.2f}s "
                    f"(原简单计算: {(trim_start_timestamp - task_start_timestamp):.2f}s - "
                    f"{(trim_end_timestamp - task_start_timestamp):.2f}s)")
    else:
        # 无映射表时回退到简单计算（适用于单视频无合并场景）
        start_seconds = trim_start_timestamp - task_start_timestamp
        end_seconds = trim_end_timestamp - task_start_timestamp
        logger.debug(f"无映射表，使用简单计算: 开始秒数={start_seconds:.2f}s, 结束秒数={end_seconds:.2f}s")

    # 验证时间戳有效性
    if start_seconds < 0:
        logger.warning(f"裁剪开始时间戳在任务开始之前，调整为 0 秒")
        start_seconds = 0

    if end_seconds <= start_seconds:
        logger.error(f"结束时间戳必须大于开始时间戳")
        raise ValueError("结束时间戳必须大于开始时间戳")

    # 调用 trim_video_by_seconds
    return trim_video_by_seconds(video_path, output_path, start_seconds, end_seconds, re_encode)


def trim_video_by_seconds(
        video_path: Union[str, Path],
        output_path: Union[str, Path],
        start_seconds: Union[int, float],
        end_seconds: Union[int, float],
        re_encode: bool = False
) -> str:
    """
    根据秒数裁剪视频
    
    Args:
        video_path: 输入视频文件路径
        output_path: 输出视频文件路径
        start_seconds: 裁剪开始的秒数
        end_seconds: 裁剪结束的秒数
        re_encode: 是否重新编码（默认 False，使用无损裁剪）
    
    Returns:
        输出视频文件的绝对路径
    
    Raises:
        FileNotFoundError: 当输入视频文件不存在时
        ValueError: 当时间参数无效时
        RuntimeError: 当 ffmpeg 执行失败时
    
    Example:
        >>> # 裁剪视频从第 5 秒到第 15 秒
        >>> trim_video_by_seconds("input.mp4", "output.mp4", 5, 15)
    """
    video_path = Path(video_path)
    output_path = Path(output_path)

    logger.info(f"开始裁剪视频: {video_path}")
    logger.debug(f"输出路径: {output_path}")
    logger.debug(f"开始秒数: {start_seconds}")
    logger.debug(f"结束秒数: {end_seconds}")

    # 验证输入文件存在
    if not video_path.exists():
        logger.error(f"视频文件不存在: {video_path}")
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    # 验证时间参数有效性
    if start_seconds < 0:
        logger.error(f"开始秒数不能为负数: {start_seconds}")
        raise ValueError("开始秒数不能为负数")

    if end_seconds <= start_seconds:
        logger.error(f"结束秒数必须大于开始秒数: {end_seconds} <= {start_seconds}")
        raise ValueError("结束秒数必须大于开始秒数")

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug(f"输出目录已创建: {output_path.parent}")

    duration = end_seconds - start_seconds
    logger.info(f"裁剪时间段: {start_seconds:.2f}s - {end_seconds:.2f}s (时长: {duration:.2f}s)")

    # 执行裁剪
    _trim_video(video_path, output_path, start_seconds, end_seconds, re_encode)

    # 检查文件大小，如果超过18MB则压缩
    file_size = output_path.stat().st_size
    max_size = 18 * 1024 * 1024
    if file_size > max_size:
        logger.info(f"视频文件大小({file_size / 1024 / 1024:.2f}MB)超过18MB，开始压缩")
        compressed_path = output_path.with_stem(f"{output_path.stem}_compressed")
        try:
            compressed_path = compress_video(output_path, compressed_path)
            # 删除原文件，替换为压缩后的文件
            output_path.unlink()
            compressed_path.rename(output_path)
            logger.info(f"视频压缩完成，压缩后大小: {output_path.stat().st_size / 1024 / 1024:.2f}MB")
        except Exception as e:
            logger.error(f"视频压缩失败，使用原文件: {str(e)}")

    logger.info(f"视频裁剪成功: {output_path.absolute()}")
    return str(output_path.absolute())


def compress_video(
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        target_size_mb: int = 18,
        crf: int = 28,
        preset: str = "medium"
) -> Path:
    """
    压缩视频文件到指定大小以下，使用H.264编码
    
    Args:
        input_path: 输入视频路径
        output_path: 输出压缩后视频路径
        target_size_mb: 目标大小，单位MB，默认18MB
        crf: 画质参数，范围0-51，数值越小画质越好，默认28
        preset: 压缩速度预设，可选：ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
                速度越慢压缩率越高，默认medium
    
    Returns:
        压缩后的视频文件路径
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    logger.info(f"开始压缩视频: {input_path}")
    logger.debug(f"输出路径: {output_path}")
    logger.debug(f"目标大小: {target_size_mb}MB")
    logger.debug(f"CRF: {crf}, Preset: {preset}")

    if not input_path.exists():
        logger.error(f"视频文件不存在: {input_path}")
        raise FileNotFoundError(f"视频文件不存在: {input_path}")

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        ffmpeg_path = get_ffmpeg_path()
        logger.debug(f"使用 ffmpeg: {ffmpeg_path}")

        # 使用H.264编码进行压缩，调整CRF参数控制画质和大小
        (
            ffmpeg
            .input(str(input_path))
            .output(
                str(output_path),
                vcodec='libx264',
                acodec='aac',
                crf=crf,
                preset=preset,
                movflags='+faststart'  # 优化web播放
            )
            .overwrite_output()
            .run(cmd=ffmpeg_path, quiet=True)
        )

        # 检查压缩后大小，如果仍然超过目标大小，自动提高CRF再次压缩
        compressed_size = output_path.stat().st_size
        target_size = target_size_mb * 1024 * 1024
        current_crf = crf

        while compressed_size > target_size and current_crf < 51:
            current_crf += 2
            logger.info(f"压缩后大小({compressed_size / 1024 / 1024:.2f}MB)仍然超过目标，提高CRF到{current_crf}再次压缩")

            (
                ffmpeg
                .input(str(input_path))
                .output(
                    str(output_path),
                    vcodec='libx264',
                    acodec='aac',
                    crf=current_crf,
                    preset=preset,
                    movflags='+faststart'
                )
                .overwrite_output()
                .run(cmd=ffmpeg_path, quiet=True)
            )

            compressed_size = output_path.stat().st_size

        logger.debug("ffmpeg 压缩命令执行完成")
        return output_path

    except ffmpeg.Error as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"ffmpeg 压缩视频失败: {error_msg}")
        raise RuntimeError(f"ffmpeg 压缩视频失败: {error_msg}")


def _trim_video(
        video_path: Path,
        output_path: Path,
        start_seconds: float,
        end_seconds: float,
        re_encode: bool = False
) -> None:
    """
    使用 ffmpeg 裁剪视频
    
    Args:
        video_path: 输入视频路径
        output_path: 输出视频路径
        start_seconds: 开始秒数
        end_seconds: 结束秒数
        re_encode: 是否重新编码
    """
    try:
        ffmpeg_path = get_ffmpeg_path()
        logger.debug(f"使用 ffmpeg: {ffmpeg_path}")

        if re_encode:
            logger.debug("使用重新编码模式裁剪")
            # 重新编码模式：先 seek 再裁剪
            (
                ffmpeg
                .input(str(video_path), ss=start_seconds, t=end_seconds - start_seconds)
                .output(str(output_path), vcodec='libx264', acodec='aac')
                .overwrite_output()
                .run(cmd=ffmpeg_path, quiet=True)
            )
        else:
            logger.debug("使用无损裁剪模式")
            # 无损裁剪模式：使用 -ss 和 -to，并复制流
            # 注意：-ss 放在 -i 前面是 fast seek，放在后面是 accurate seek
            # 这里使用 fast seek + -t 指定时长
            (
                ffmpeg
                .input(str(video_path), ss=start_seconds)
                .output(str(output_path), t=end_seconds - start_seconds, c='copy')
                .overwrite_output()
                .run(cmd=ffmpeg_path, quiet=True)
            )

        logger.debug("ffmpeg 命令执行完成")
    except ffmpeg.Error as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"ffmpeg 裁剪视频失败: {error_msg}")
        raise RuntimeError(f"ffmpeg 裁剪视频失败: {error_msg}")


def _build_and_save_mapping(candidates: list[Path], dir_path: str,
                            task_start_timestamp: Optional[float],
                            merged_video_path: str) -> None:
    """构建时间映射表并保存到 sidecar 文件"""
    if task_start_timestamp is None:
        return

    # 读取片段元数据
    segment_metadata = _load_segment_metadata(dir_path)
    segment_starts = {}
    for seg in segment_metadata.get("segments", []):
        segment_starts[seg["file"]] = seg["start_timestamp"]

    # 对未记录开始时间的片段，使用 task_start_timestamp 作为默认值
    for p in candidates:
        if p.name not in segment_starts:
            segment_starts[p.name] = task_start_timestamp
            logger.debug(f"片段 {p.name} 无元数据，使用 task_start_timestamp 作为开始时间")

    mapping = build_time_mapping(candidates, segment_starts, task_start_timestamp)
    if mapping:
        _save_time_mapping(mapping, merged_video_path)


def find_video_and_merge(dir_path: str, keep_raw: bool = False,
                         task_start_timestamp: Optional[float] = None):
    # 搜索所有 screen_record 开头的 mp4 文件
    candidates: list[Path] = []
    search_dir = Path(dir_path)

    candidates.extend(p for p in search_dir.rglob("*.mp4") if p.name.startswith("screen_record"))

    if not candidates:
        logger.error("[VerifyAgent] 未找到任何视频文件")
        return ""

    # 按修改时间排序
    candidates = sorted(candidates, key=lambda path: path.stat().st_mtime)
    logger.info(f"[VerifyAgent] 找到 {len(candidates)} 个视频文件")

    if len(candidates) == 1:
        video_path = candidates[0]
        logger.info(f"[VerifyAgent] 使用单个视频文件: {video_path}")
        if keep_raw:
            _build_and_save_mapping(candidates, dir_path, task_start_timestamp, str(video_path))
            return str(video_path)
        # 复制一份为 merged_video，保留原始 screen_record 到任务结束
        merge_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        merged_output = Path(dir_path) / f"merged_video_{merge_timestamp}.mp4"
        try:
            import shutil
            shutil.copy2(str(video_path), str(merged_output))
            logger.info(f"[VerifyAgent] 复制: {video_path} -> {merged_output}")
            _build_and_save_mapping(candidates, dir_path, task_start_timestamp, str(merged_output))
            return str(merged_output)
        except Exception as e:
            logger.error(f"[VerifyAgent] 复制失败: {str(e)}，使用原始文件")
            _build_and_save_mapping(candidates, dir_path, task_start_timestamp, str(video_path))
            return str(video_path)
    elif len(candidates) >= 2:
        # 合并所有视频文件，使用新的时间戳作为合并后的文件名
        merge_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        merge_output = Path(dir_path) / f"merged_video_{merge_timestamp}.mp4"
        try:
            merged_path = merge_videos(candidates, str(merge_output), delete_temp=False)
            logger.info(f"[VerifyAgent] 合并{len(candidates)}个视频文件成功: {merged_path}")
            _build_and_save_mapping(candidates, dir_path, task_start_timestamp, merged_path)
            # screen_record 保留到任务结束统一删除，不在此处删除
            return merged_path
        except Exception as e:
            logger.error(f"[VerifyAgent] 合并视频失败: {str(e)}，使用最新的单个视频")
            fallback_path = str(candidates[-1])
            _build_and_save_mapping(candidates, dir_path, task_start_timestamp, fallback_path)
            return fallback_path

    return ""
