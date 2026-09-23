"""验证工具模块 - 提供各种验证方法用于检查执行结果。"""

import base64
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Tuple, Optional

from openai import OpenAI, AzureOpenAI

from ..config import AppConfig
from ..logger import logger
from ..storage import output_path as managed_output, temp_directory
from .video_tools import (
    encode_video_base64,
    get_video_mime_type,
    prepare_video_for_verification,
)

# ============================================================================
# 验证提示词模板
# ============================================================================

# System Prompt - 定义角色、方法论和输出格式（通用指导）

ONE_IMAGE_SYSTEM_PROMPT = """你是一位专业的UI自动化测试验证专家，负责验证截图是否符合预期。

## 你的职责
分析界面截图，验证UI元素、文本内容、组件状态、布局和视觉样式是否符合预期条件。

## 验证方法
1. **界面元素检查**：确认目标UI元素是否存在、可见、可交互
2. **文本内容检查**：验证文本显示是否正确、完整
3. **状态检查**：确认组件状态（选中/未选中、启用/禁用等）
4. **布局检查**：验证元素位置、大小、对齐方式
5. **视觉检查**：确认颜色、图标、样式是否符合预期

## 输出格式要求
- **第一行**：必须明确给出验证结论，仅输出 `通过` 或 `失败`
- **后续内容**：使用编号列表详细说明验证过程
  1. 描述观察到的实际状态
  2. 对比预期状态
  3. 说明判断依据
- 保持描述简洁、客观、基于事实
- 如发现异常，需指出具体问题所在"""

MULTI_IMAGE_SYSTEM_PROMPT = """你是一位专业的UI自动化测试验证专家，负责对比分析两张截图并验证界面变化。

## 你的职责
对比操作前后的界面截图，验证变化是否符合操作预期，识别异常变化。

## 对比分析方法
1. **变化识别**：识别两张图片之间的所有差异点
2. **变化分类**：区分预期变化和异常变化
3. **变化验证**：确认变化是否符合操作预期
4. **稳定性检查**：验证未变更区域是否保持稳定

## 图片说明
- 第一张图片：操作后的界面状态（当前图片）
- 第二张图片：操作前的界面状态（之前图片）

## 输出格式要求
- **第一行**：必须明确给出验证结论，仅输出 `通过` 或 `失败`
- **后续内容**：使用编号列表详细说明对比结果
  1. 列出检测到的所有变化
  2. 分析每个变化是否合理
  3. 确认是否有遗漏的预期变化
  4. 检查是否有非预期的异常变化
- 重点描述变化内容，而非静态内容
- 如发现异常变化，需明确指出问题"""

CROSS_STEP_SYSTEM_PROMPT = """你是一位专业的UI自动化测试验证专家，负责验证跨步骤场景的界面一致性。

## 你的职责
对比分析来自不同测试步骤的截图，验证跨步骤场景的数据传递、状态一致性和业务逻辑正确性。

## 对比分析方法
1. **场景关联分析**：理解跨步骤场景的业务逻辑关联
2. **一致性检查**：验证需要保持一致的元素或状态
3. **差异验证**：确认预期差异是否正确呈现
4. **上下文验证**：检查跨步骤数据传递是否正确

## 图片说明
- 第一张图片：当前步骤的界面状态
- 第二张图片：关联步骤的界面状态

## 输出格式要求
- **第一行**：必须明确给出验证结论，仅输出 `通过` 或 `失败`
- **后续内容**：使用编号列表详细说明验证结果
  1. 说明跨步骤场景的验证目标
  2. 对比两张图片的关键差异
  3. 分析差异是否符合场景预期
  4. 确认跨步骤数据/状态传递是否正确
- 如发现异常，需说明对跨步骤流程的影响"""

REFER_IMAGE_SYSTEM_PROMPT = """你是一位专业的UI自动化测试验证专家，负责验证界面一致性。

## 你的职责
对比当前截图与参考截图，验证界面布局、元素、内容和样式的一致性。

## 一致性验证方法
1. **整体布局对比**：验证页面结构是否一致
2. **关键元素对比**：检查重要UI元素的位置和样式
3. **内容一致性**：验证文本、图标等内容是否匹配
4. **样式一致性**：确认颜色、字体、间距等样式属性
5. **容差分析**：区分可接受的细微差异和实质性问题

## 图片说明
- 第一张图片：待验证的实际界面
- 第二张图片：预期的标准参考界面

## 输出格式要求
- **第一行**：必须明确给出验证结论，仅输出 `通过` 或 `失败`
- **后续内容**：使用编号列表详细说明对比结果
  1. 整体一致性评估
  2. 列出检测到的差异点
  3. 分析每个差异的性质（关键/次要）
  4. 说明差异是否在可接受范围内
- 对于失败情况，需明确指出需要修正的问题
- 对于通过情况，可说明存在的细微差异但不影响整体一致性"""

# User Prompt - 具体的验证任务描述（动态内容）

ONE_IMAGE_USER_PROMPT = """请验证当前截图是否符合以下描述：

{description}"""

MULTI_IMAGE_USER_PROMPT = """请对比以下两张截图，验证界面变化是否符合预期：

**图片顺序说明**：
- 图片1：当前截图（操作后状态）
- 图片2：之前截图（操作前状态）

**验证描述**：
{description}"""

CROSS_STEP_USER_PROMPT = """请验证跨步骤场景「{scene_name}」是否符合以下描述：

**图片顺序说明**：
- 图片1：当前步骤截图
- 图片2：跨步骤关联截图

**验证描述**：
{description}"""

REFER_IMAGE_USER_PROMPT = """请验证当前截图与参考图片的一致性是否符合以下描述：

**图片顺序说明**：
- 图片1：当前截图（待验证）
- 图片2：参考截图（预期标准）

**验证描述**：
{description}"""

# 视频验证提示词

VIDEO_SYSTEM_PROMPT = """你是一位专业的UI自动化测试视频验证专家，负责分析操作视频并验证用户交互流程。

## 你的职责
分析视频内容，验证用户操作流程、界面状态转换、系统响应和异常情况是否符合预期。

## 注意全屏播放视频的方位
- 如果播放器处于全屏播放状态，由于视频为竖屏录制会导致横屏视频全屏后观测方向旋转，验证描述中的播放器位置注意映射：
  - "播放器顶部" → 视频画面右侧
  - "播放器底部" → 视频画面左侧
  - "播放器左侧" → 视频画面上方
  - "播放器右侧" → 视频画面下方

## 步骤操作理解
- 触发某个状态变化的操作（如滑动、点击等）可能已在之前的步骤中执行，当前视频片段中不一定能看到该操作过程本身
- 只要视频中呈现的界面状态与验证描述一致，即应判定为通过，不要因为未观察到操作过程本身而判定失败

## 验证方法
1. **操作流程分析**：若视频中可见用户交互，验证其是否按预期顺序执行
2. **UI状态转换**：检查界面变化是否匹配预期行为
3. **响应验证**：确认系统响应时机和内容是否正确
4. **错误检测**：识别异常、崩溃、错误提示等问题
5. **视觉一致性**：验证动画、过渡效果和视觉反馈

## 输出格式要求
- **第一行**：必须明确给出验证结论，仅输出 `PASS` 或 `FAIL`
- **后续内容**：使用编号列表详细说明验证结果
  1. 描述观察到的操作和结果
  2. 对比实际行为与预期行为
  3. 说明时序或顺序问题
  4. 指出任何异常或问题
- 保持描述简洁、基于视频中的事实"""

VIDEO_USER_PROMPT = """请验证视频内容是否符合以下描述：

{description}"""


# ============================================================================
# 工具函数
# ============================================================================

def _load_image_base64(image_path: str) -> str:
    """
    加载图片并转换为 base64 编码
    
    Args:
        image_path: 图片文件路径
        
    Returns:
        base64 编码的图片数据
    """
    if not image_path:
        return ""

    try:
        path = Path(image_path)
        if path.exists():
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8')
        else:
            logger.error(f"图片文件不存在: {image_path}")
    except Exception as e:
        logger.error(f"加载图片失败: {image_path}, 错误: {e}")

    return ""


def _create_client(config: AppConfig) -> Tuple[OpenAI | AzureOpenAI, str]:
    """
    创建 OpenAI 客户端
    
    Args:
        config: 应用配置
        
    Returns:
        (client, model_name) 元组
    """
    if config.verify_api_version:
        client = AzureOpenAI(
            azure_endpoint=config.verify_base_url,
            api_key=config.verify_api_key,
            api_version=config.verify_api_version,
            timeout=300,
            max_retries=2
        )
    else:
        client = OpenAI(
            base_url=config.verify_base_url,
            api_key=config.verify_api_key,
            timeout=300,
            max_retries=2
        )

    return client, config.verify_model_name


def _call_vision_model(
        config: AppConfig,
        system_prompt: str,
        user_prompt: str,
        images: list[str],
) -> Tuple[bool, str]:
    """
    调用视觉模型进行验证
    
    Args:
        config: 应用配置
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        images: base64 编码的图片列表
        
    Returns:
        (是否通过, 验证摘要) 元组
    """
    try:
        client, model_name = _create_client(config)

        # 构建消息内容
        content = [{"type": "text", "text": user_prompt}]

        for i, image_base64 in enumerate(images):
            if image_base64:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ]

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=config.verify_temperature,
            top_p=config.verify_top_p,
            frequency_penalty=config.verify_frequency_penalty,
            max_tokens=2048
        )

        result_text = response.choices[0].message.content.strip()
        logger.info(f"[VerifyTools] 模型返回: {result_text}")

        # 解析结果
        passed = _parse_verification_result(result_text)

        return passed, result_text

    except Exception as e:
        logger.error(f"[VerifyTools] 调用视觉模型失败: {e}")
        return False, f"验证调用失败: {str(e)}"


def _parse_verification_result(result_text: str) -> bool:
    """SDD patch: explicit conclusion only; negative/ambiguous text never passes."""
    first = next((line.strip() for line in result_text.splitlines() if line.strip()), '')
    first = first.replace('**', '').strip()
    match = re.match(r'^(?:(?:结论|结果|验证结果|验证)[：:]\s*)?(不通过|未通过|不成功|失败|FAIL(?:ED)?|通过|PASS(?:ED)?|[✓√✗×])(?=$|[\s,，。:：;；.!！])', first, re.I)
    if not match:
        raise ValueError('无法解析明确验证结论')
    word = match.group(1).upper()
    if word in ('不通过', '未通过', '不成功', '失败', 'FAIL', 'FAILED', '✗', '×'):
        return False
    # A contradictory first line is unknown, never a successful observation.
    if re.search(r'不通过|未通过|失败|\bFAIL(?:ED)?\b', first, re.I):
        raise ValueError('无法解析矛盾验证结论')
    return True


def call_video_verify_api(
        video_path: str,
        prompt: str,
        config: Optional[AppConfig] = None,
        system_prompt: Optional[str] = None,
) -> str:
    """
    直接调用视频验证模型 API。

    Args:
        video_path: 待验证的视频文件路径
        prompt: 发送给模型的文本提示词（用户提示词）
        config: 应用配置
        system_prompt: 系统提示词（可选，默认使用 VIDEO_SYSTEM_PROMPT）

    Returns:
        模型返回的原始文本
    """
    if system_prompt is None:
        system_prompt = VIDEO_SYSTEM_PROMPT
    if config is None:
        from ..config import config_manager
        config = config_manager.get_effective_config()

    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video file does not exist: {video_file}")

    client, model_name = _create_client(config)
    base64_video = encode_video_base64(video_file)
    mime_type = get_video_mime_type(video_file)

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {
                            "url": f"data:{mime_type};base64,{base64_video}"
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            },
        ],
        temperature=config.verify_temperature,
        top_p=config.verify_top_p,
        frequency_penalty=config.verify_frequency_penalty,
        max_tokens=2048,
    )

    result_text = response.choices[0].message.content
    if isinstance(result_text, list):
        return "\n".join(
            item.get("text", "") for item in result_text if isinstance(item, dict)
        ).strip()
    return str(result_text).strip()


def one_image_assert(
        description: str,
        image_path: str,
        config: Optional[AppConfig] = None
) -> Tuple[bool, str]:
    """
    单图验证 - 验证单个图片是否符合预期描述
    
    Args:
        description: 验证描述
        image_path: 图片路径
        config: 应用配置（可选，用于测试时传入）
        
    Returns:
        (是否通过, 验证摘要) 元组
    """
    logger.info(f"[one_image_assert] 开始验证: {description}")
    logger.info(f"[one_image_assert] 图片路径: {image_path}")

    # 加载图片
    image_base64 = _load_image_base64(image_path)
    if not image_base64:
        return False, f"无法加载图片: {image_path}"

    # 如果没有传入配置，使用全局配置
    if config is None:
        from ..config import config_manager
        config = config_manager.get_effective_config()

    # 构建提示词
    system_prompt = ONE_IMAGE_SYSTEM_PROMPT
    user_prompt = ONE_IMAGE_USER_PROMPT.format(description=description)

    # 调用视觉模型
    return _call_vision_model(config, system_prompt, user_prompt, [image_base64])


def multi_image_assert(
        description: str,
        current_image_path: str,
        prev_image_path: str,
        config: Optional[AppConfig] = None
) -> Tuple[bool, str]:
    """
    双图对比验证 - 验证两张图片的变化是否符合预期
    
    Args:
        description: 验证描述
        current_image_path: 当前图片路径
        prev_image_path: 之前图片路径
        config: 应用配置（可选）
        
    Returns:
        (是否通过, 验证摘要) 元组
    """
    logger.info(f"[multi_image_assert] 开始验证: {description}")
    logger.info(f"[multi_image_assert] 当前图片: {current_image_path}")
    logger.info(f"[multi_image_assert] 之前图片: {prev_image_path}")

    # 加载图片
    current_image = _load_image_base64(current_image_path)
    prev_image = _load_image_base64(prev_image_path)

    if not current_image:
        return False, f"无法加载当前图片: {current_image_path}"
    if not prev_image:
        return False, f"无法加载之前图片: {prev_image_path}"

    # 如果没有传入配置，使用全局配置
    if config is None:
        from ..config import config_manager
        config = config_manager.get_effective_config()

    # 构建提示词
    system_prompt = MULTI_IMAGE_SYSTEM_PROMPT
    user_prompt = MULTI_IMAGE_USER_PROMPT.format(description=description)

    # 调用视觉模型（先传当前图片，再传之前图片）
    return _call_vision_model(config, system_prompt, user_prompt, [current_image, prev_image])


def cross_step_image_assert(
        description: str,
        current_image_path: str,
        cross_step_image_path: str,
        cross_step_scene_name: str,
        config: Optional[AppConfig] = None
) -> Tuple[bool, str]:
    """
    跨步骤验证 - 验证跨步骤/跨场景的图片对比
    
    Args:
        description: 验证描述
        current_image_path: 当前图片路径
        cross_step_image_path: 跨步骤图片路径
        cross_step_scene_name: 跨步骤场景名称
        config: 应用配置（可选）
        
    Returns:
        (是否通过, 验证摘要) 元组
    """
    logger.info(f"[cross_step_image_assert] 开始验证: {description}")
    logger.info(f"[cross_step_image_assert] 当前图片: {current_image_path}")
    logger.info(f"[cross_step_image_assert] 跨步骤图片: {cross_step_image_path}")
    logger.info(f"[cross_step_image_assert] 场景名称: {cross_step_scene_name}")

    # 加载图片
    current_image = _load_image_base64(current_image_path)
    cross_step_image = _load_image_base64(cross_step_image_path)

    if not current_image:
        return False, f"无法加载当前图片: {current_image_path}"
    if not cross_step_image:
        return False, f"无法加载跨步骤图片: {cross_step_image_path}"

    # 如果没有传入配置，使用全局配置
    if config is None:
        from ..config import config_manager
        config = config_manager.get_effective_config()

    # 构建提示词
    system_prompt = CROSS_STEP_SYSTEM_PROMPT
    user_prompt = CROSS_STEP_USER_PROMPT.format(
        description=description,
        scene_name=cross_step_scene_name
    )

    # 调用视觉模型
    return _call_vision_model(config, system_prompt, user_prompt, [current_image, cross_step_image])


def refer_image_assert(
        description: str,
        current_image_path: str,
        refer_image_path: str,
        config: Optional[AppConfig] = None
) -> Tuple[bool, str]:
    """
    参考图片验证 - 验证当前图片与参考图片的一致性
    
    Args:
        description: 验证描述
        current_image_path: 当前图片路径
        refer_image_path: 参考图片路径
        config: 应用配置（可选）
        
    Returns:
        (是否通过, 验证摘要) 元组
    """
    logger.info(f"[refer_image_assert] 开始验证: {description}")
    logger.info(f"[refer_image_assert] 当前图片: {current_image_path}")
    logger.info(f"[refer_image_assert] 参考图片: {refer_image_path}")

    # 加载图片
    current_image = _load_image_base64(current_image_path)
    refer_image = _load_image_base64(refer_image_path)

    if not current_image:
        return False, f"无法加载当前图片: {current_image_path}"
    if not refer_image:
        return False, f"无法加载参考图片: {refer_image_path}"

    # 如果没有传入配置，使用全局配置
    if config is None:
        from ..config import config_manager
        config = config_manager.get_effective_config()

    # 构建提示词
    system_prompt = REFER_IMAGE_SYSTEM_PROMPT
    user_prompt = REFER_IMAGE_USER_PROMPT.format(description=description)

    # 调用视觉模型
    return _call_vision_model(config, system_prompt, user_prompt, [current_image, refer_image])


def video_assert_tool(
        description: str,
        start_time: float,
        end_time: float,
        video_path: Optional[str] = None,
        task_start_timestamp: Optional[float] = None,
        config: Optional[AppConfig] = None
) -> Tuple[bool, str]:
    """
    Video verification via the openai client using video_url + text input.
    """
    logger.info(f"[video_assert_tool] Start verify: {description}")
    logger.info(f"[video_assert_tool] Time range: {start_time} - {end_time}")
    logger.info(f"[video_assert_tool] Video path: {video_path}")

    if config is None:
        from ..config import config_manager
        config = config_manager.get_effective_config()

    temp_clip_path = None
    video_file = None
    try:
        if not video_path:
            return False, "Video file not found for verification"

        video_file = Path(video_path)
        if not video_file.exists():
            return False, f"Video file does not exist: {video_file}"

        if end_time <= start_time:
            return False, "end_time must be greater than start_time"

        temp_clip_path: Optional[Path] = None

        with tempfile.NamedTemporaryFile(dir=temp_directory(video_file), suffix=video_file.suffix or ".mp4", delete=False) as temp_file:
            temp_clip_path = Path(temp_file.name)

        clip_path = Path(
            prepare_video_for_verification(
                video_path=video_file,
                start_time=start_time,
                end_time=end_time,
                task_start_timestamp=task_start_timestamp,
                output_path=temp_clip_path,
                re_encode=True,
            )
        )

        # 构建提示词
        user_prompt = VIDEO_USER_PROMPT.format(description=description)
        result_text = call_video_verify_api(
            video_path=str(clip_path),
            prompt=user_prompt,
            config=config,
        )

        logger.info(f"[video_assert_tool] Model response: {result_text}")
        return _parse_verification_result(result_text), result_text
    except Exception as e:
        logger.exception(f"[video_assert_tool] Video verification failed: {e}")
        return False, f"Video verification failed: {str(e)}"
    finally:
        # 将裁剪后的视频移动到 videoPath 目录
        if temp_clip_path and temp_clip_path.exists():
            try:
                clip_output = managed_output(temp_directory(video_file).parent / "reports/videoPath" / f"clip_{int(start_time)}_{int(end_time)}_{temp_clip_path.stem}.mp4")
                clip_output.parent.mkdir(parents=True, exist_ok=True)
                temp_clip_path.rename(clip_output)
                logger.info(f"[video_assert_tool] 裁剪视频已保存: {clip_output}")
            except Exception as e:
                logger.warning(f"[video_assert_tool] 保存裁剪视频失败: {temp_clip_path}, 错误: {str(e)}")
                temp_clip_path.unlink(missing_ok=True)
        # merged_video 裁剪后必须删除
        if video_file and video_file.name.startswith("merged_video") and not config.keep_raw_video:
            try:
                managed_output(video_file).unlink(missing_ok=True)
                logger.info(f"[video_assert_tool] 删除合并视频: {video_file}")
            except Exception as e:
                logger.warning(f"[video_assert_tool] 删除合并视频失败: {video_file}, 错误: {e}")
            # 同时清理时间映射表 sidecar 文件
            mapping_file = video_file.with_suffix(".mapping.json")
            if mapping_file.exists():
                try:
                    managed_output(mapping_file).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"[video_assert_tool] 删除映射表失败: {mapping_file}, 错误: {e}")


# ============================================================================
# 导出所有验证工具
# ============================================================================

__all__ = [
    'one_image_assert',
    'multi_image_assert',
    'cross_step_image_assert',
    'refer_image_assert',
    'call_video_verify_api',
    'video_assert_tool',
]
