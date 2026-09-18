import json
import time
import datetime
from pathlib import Path
from typing import Tuple, Dict, Any

from openai import OpenAI, AzureOpenAI
from ..devices.hdc_device import HDCDevice
from ..reporter.generator import ReportGenerator
from ..config import AppConfig
from ..logger import logger
from ..utils.utils import retry_on_exception
from .verify_tools import (
    one_image_assert,
    multi_image_assert,
    cross_step_image_assert,
    refer_image_assert,
    video_assert_tool
)
from .video_tools import find_video_and_merge, record_segment_start
from ..layered_agent_cli.agent_registry import agent_registry
from ..layered_agent_cli.mcp_tools import collect_function_tool


@collect_function_tool
def verify(description: str):
    """
    通用验证接口 - 调用验证代理执行验证逻辑

    Args:
        description: 验证描述，包含验证的具体要求和预期结果

    Returns:
        JSON格式的字符串，包含验证结果:
        {
            "result": bool,  # True表示验证通过，False表示验证失败
            "reason": str    # 验证结果说明或失败原因
        }
    """
    verify_agent = agent_registry.get_verify_agent()
    result, msg = verify_agent.verify(description)
    json_msg = {
        "result": result,
        "reason": msg
    }
    return json.dumps(json_msg, ensure_ascii=False)


BASE_SYSTEM_PROMPT = """你是一个验证工具选择助手，需要根据用户的验证描述和时间线，选择合适的验证工具和步骤。

可用工具：
1. one_image_assert(description, image_path): 验证单个图片，适用于描述中只涉及当前页面，如"页面展示正常"、"当前页面包含xxx"
2. multi_image_assert(description, image_path, prev_image_path): 验证两张图片的变化，适用于描述中涉及前后对比，如"点击后页面有变化"、"验证操作前后是否改变"
3. cross_step_image_assert(description, image_path, cross_step_image_path, cross_step_scene_name): 跨步骤验证，适用于描述中涉及跨步骤或跨场景的对比
4. refer_image_assert(description, image_path, refer_image_path): 参考图片验证，适用于描述中需要与指定参考图片对比
{video_tool_section}
请根据用户的验证描述和时间线，选择最合适的工具和步骤，并返回JSON格式的结果。

【重要原则与优先级】
{video_priority_section}
- 静态变化：只有明确是静态页面元素的变化（如按钮状态改变、页面结构变化）才使用 `multi_image_assert`。

【重要！严格遵守输出格式】
- 只返回纯 JSON，不要任何其他文本
- 不要添加 ```json 或 ``` 等任何 Markdown 代码块标记
- 不要添加任何解释性文字或说明
- 不需要的字段直接省略，不要设为 null

【JSON 格式示例】
{{
  "tool": "工具名称",
  "current_step_index": 要验证的当前步骤index,
  "reason": "选择理由"
}}

【字段说明】
- tool（必填）：工具名称，从 {allowed_tools} 中选择
- current_step_index（必填）：要验证的当前步骤 index
- prev_step_index（仅 multi_image_assert 需要）：上一张图片的步骤 index，通常是 current_step_index - 1
- refer_step_index（仅 refer_image_assert 需要）：参考图片的步骤 index
- cross_step_index（仅 cross_step_image_assert 需要）：要对比的跨步骤 index
- cross_step_scene_name（仅 cross_step_image_assert 需要）：跨步骤场景名称
{video_field_section}
- reason（必填）：选择理由

只返回 JSON，不要有其他文本！"""


class VerifyAgent:
    def __init__(self, report: ReportGenerator, config: AppConfig, device: HDCDevice) -> None:
        self.report = report
        self.config = config
        self.device = device

        # 根据配置生成系统提示词
        if self.config.verify_video_enable:
            video_tool_section = "5. video_assert(description, start_time, end_time): 视频验证，适用于需要验证一段时间内的操作变化或时效性控件变化，例如\"滑动现象（滑动中亮度条变化、滑动或拖动中进度条变化）\"、\"toast验证\"、\"弹出提示\"、\"倒数\"，使用Unix时间戳指定开始和结束时间\n"
            video_priority_section = ("- 动态元素最高优先级：如果验证描述属于以下情况之一，无论是否包含\"点击后\"等前后对比字眼，**必须且只能**使用 `video_assert`，严禁使用图片对比。\n"
                                      "   - （1）验证描述中包含\"toast\"、\"提示\"、\"弹出\"、\"消失\"、\"闪动\"、\"倒数\"等短暂出现的动态元素\n"
                                      "   - （2）验证描述中包含\"滑动\"、\"拖动\"、\"长按\"等需要一段时间的操作\n"
                                      "   - （3）验证描述中包含播控控件校验如\"播控展示\"、\"进度条展示\"（播控具有时效性，唤起播控后控件才短暂出现）\n"
                                      "   - （4）验证描述中涉及播放器展示，例如：播放器暂停播放中间出现xxx、播放器全屏左上角展示xxx")
            video_field_section = ("- start_step_index（仅 video_assert 需要）：视频开始时间对应的步骤 index\n- end_step_index（仅 video_assert 需要）：视频结束时间对应的步骤 index\n"
                                   "- 注意start_step_index与end_step_index的选择，遵从以下要求：\n"
                                   "   - （1）start_step_index必须小于end_step_index\n"
                                   "   - （2）尽量缩小end_step_index，聚焦验证动作与结果。start_step_index与end_step_index步骤差一般不会超过10，如果超过，核对end_step_index相邻步骤是否存在重复，可以减少重复将end_step_index往前选择\n"
                                   "   - （3）如果start_step_index选择“调用run_skill_script工具”对应步骤，需要选择开始tool_start，而不是结束tool_end\n")
            allowed_tools = "one_image_assert, multi_image_assert, cross_step_image_assert, refer_image_assert, video_assert"
        else:
            video_tool_section = ""
            video_priority_section = ""
            video_field_section = ""
            allowed_tools = "one_image_assert, multi_image_assert, cross_step_image_assert, refer_image_assert"

        self.SYSTEM_PROMPT = BASE_SYSTEM_PROMPT.format(
            video_tool_section=video_tool_section,
            video_priority_section=video_priority_section,
            video_field_section=video_field_section,
            allowed_tools=allowed_tools
        )

    @staticmethod
    def _should_skip_verify_timeline_step(step) -> bool:
        title = (getattr(step, "title", "") or "").strip()
        if not title:
            return False
        return any(tool_name in title for tool_name in
                   ("execute工具", "summary工具", "load_skill工具", "wait工具"))

    def _get_verify_timeline_steps(self):
        return [
            step for step in self.report.step_content
            if not self._should_skip_verify_timeline_step(step)
        ]

    def _get_current_verify_step_index(self) -> int:
        steps = self._get_verify_timeline_steps()
        if steps:
            return steps[-1].index
        return self.report.step_content[-1].index if self.report.step_content else 0

    @retry_on_exception(max_retries=2)
    def get_respond(self, user_prompt):
        if self.config.verify_api_version:
            client = AzureOpenAI(
                azure_endpoint=self.config.verify_base_url,
                api_key=self.config.verify_api_key,
                api_version=self.config.verify_api_version,
                timeout=300,
                max_retries=2
            )
        else:
            client = OpenAI(
                base_url=self.config.verify_base_url,
                api_key=self.config.verify_api_key,
                timeout=300,
                max_retries=2
            )

        response = client.chat.completions.create(
            model=self.config.verify_model_name,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=self.config.verify_temperature,
            top_p=self.config.verify_top_p,
            frequency_penalty=self.config.verify_frequency_penalty,
            max_tokens=2048
        )
        content = response.choices[0].message.content.strip()
        return content

    def _get_image_path(self, step_index: int) -> str:
        for step in self.report.step_content:
            if step.index == step_index and step.screenshot_path:
                return step.screenshot_path
        return ""

    def _get_video_path(self, task_start_timestamp: float = None) -> str:
        # 生成时间戳作为文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        # 停止幕录制并保存视频
        output_path = Path(self.report.video_dir) / f"screen_record_{timestamp}.mp4"
        try:
            self.device.stop_screen_record(str(output_path))
            logger.info(f"[VerifyAgent] 停止屏幕录制，视频已保存到: {output_path}")
            self.device.start_screen_record()

            # 记录片段元数据：当前片段的开始时间戳 + 新片段的开始时间戳
            new_segment_start = time.time()
            record_segment_start(
                dir_path=str(self.report.video_dir),
                segment_file=output_path.name,
                default_start_timestamp=task_start_timestamp if task_start_timestamp else 0.0,
                next_segment_start=new_segment_start
            )
        except Exception as e:
            logger.warning(f"[VerifyAgent] 停止屏幕录制失败: {str(e)}")

        return find_video_and_merge(
            str(self.report.video_dir),
            keep_raw=self.config.keep_raw_video,
            task_start_timestamp=task_start_timestamp
        )

    def _select_tool_and_steps(self, description: str) -> Dict[str, Any]:
        logger.info(f"[VerifyAgent] 开始选择验证工具和步骤，描述: {description}")

        try:
            timeline_steps = self._get_verify_timeline_steps()
            if len(timeline_steps) > 50:
                timeline_steps = timeline_steps[-50:]
            timeline_str = "时间线：\n"
            for step in timeline_steps:
                timeline_str += f"- index: {step.index}, step_type: {step.step_type}, title: {step.title}\n"

            user_prompt = f"{timeline_str}\n验证描述：{description}"

            logger.info("verify: {}".format(user_prompt))

            content = self.get_respond(user_prompt)

            logger.info("select content: {}".format(content))
            try:
                content = content.strip()
                if content.startswith('```json'):
                    content = content[7:]
                if content.startswith('```'):
                    content = content[3:]
                if content.endswith('```'):
                    content = content[:-3]
                content = content.strip()
                result = json.loads(content)
                logger.info(f"[VerifyAgent] 选择结果: {result}")
                self.report.verify_start(description=description, content=result, mode="llm")
                return result
            except json.JSONDecodeError:
                result = self._fallback_select(description)
                logger.info(f"[VerifyAgent] LLM返回解析失败，使用降级方案")
                self.report.verify_start(description=description, content=result, mode="rule")
                return result
        except Exception as e:
            logger.info(f"[VerifyAgent] LLM调用失败: {str(e)}，使用降级方案")
            return self._fallback_select(description)

    def _fallback_select(self, description: str) -> Dict[str, Any]:
        description_lower = description.lower()
        current_step_index = self._get_current_verify_step_index()

        if self.config.verify_video_enable and any(keyword in description_lower for keyword in
                                                   ['视频', '录像', 'video', 'record', '一段时间', '全程', '过程',
                                                    'toast', '提示', '弹出']):
            return {
                "tool": "video_assert",
                "current_step_index": current_step_index,
                "start_step_index": current_step_index - 10 if current_step_index > 10 else 0,
                "end_step_index": current_step_index,
                "reason": "关键词匹配，视频验证"
            }

        if any(keyword in description_lower for keyword in
               ['前后', '变化', '对比', '是否改变', 'before', 'after', 'change', 'compare']):
            return {
                "tool": "multi_image_assert",
                "current_step_index": current_step_index,
                "prev_step_index": current_step_index - 1 if current_step_index > 0 else 0,
                "reason": "关键词匹配，需要对比前后变化"
            }

        if any(keyword in description_lower for keyword in ['跨步骤', '跨场景', 'cross_step', 'cross_scene']):
            return {
                "tool": "cross_step_image_assert",
                "current_step_index": current_step_index,
                "cross_step_index": 0,
                "cross_step_scene_name": "初始场景",
                "reason": "关键词匹配，跨步骤验证"
            }

        if any(keyword in description_lower for keyword in ['参考', '参照', 'reference', 'refer']):
            return {
                "tool": "refer_image_assert",
                "current_step_index": current_step_index,
                "refer_step_index": 0,
                "reason": "关键词匹配，参考图片验证"
            }

        return {
            "tool": "one_image_assert",
            "current_step_index": current_step_index,
            "reason": "关键词匹配，单图验证"
        }

    def _verify(self, description: str) -> Tuple[bool, str, str, list[str]]:
        logger.info(f"[VerifyAgent] 开始验证: {description}")

        select_result = self._select_tool_and_steps(description)
        tool_name = select_result.get("tool", "one_image_assert")
        logger.info(f"[VerifyAgent] 调用工具: {tool_name}")

        try:
            if tool_name == 'video_assert':
                start_step_index = select_result.get("start_step_index", 0)
                end_step_index = select_result.get("end_step_index",
                                                   self.report.step_content[
                                                       -1].index if self.report.step_content else 0)

                start_time = None
                end_time = None

                for step in self.report.step_content:
                    if step.index == start_step_index:
                        start_time = step.timestamp
                    if step.index == end_step_index:
                        end_time = step.timestamp

                if start_time is None or end_time is None:
                    error_msg = f"无法找到视频时间戳，start_step_index: {start_step_index}, end_step_index: {end_step_index}"
                    logger.error(f"[VerifyAgent] {error_msg}")
                    return False, error_msg, tool_name, []

                task_start_timestamp = self.report.step_content[0].timestamp if self.report.step_content else start_time

                video_path = self._get_video_path(task_start_timestamp=task_start_timestamp)
                if not video_path:
                    error_msg = "没有视频文件"
                    logger.error(f"[VerifyAgent] {error_msg}")
                    return False, error_msg, tool_name, []

                conclusion, summary = video_assert_tool(
                    description=description,
                    start_time=start_time,
                    end_time=end_time,
                    video_path=video_path,
                    task_start_timestamp=task_start_timestamp,
                )
                logger.info(f"[VerifyAgent] 验证完成，结论: {conclusion}, 摘要: {summary}")
                return conclusion, summary, tool_name, [video_path]

            current_step_index = select_result.get("current_step_index",
                                                   self.report.step_content[
                                                       -1].index if self.report.step_content else 0)
            current_image_path = self._get_image_path(current_step_index)

            if not current_image_path:
                error_msg = "无法获取当前图片路径"
                logger.error(f"[VerifyAgent] {error_msg}")
                return False, error_msg, tool_name, []

            if tool_name == 'one_image_assert':
                conclusion, summary = one_image_assert(description, current_image_path)
                logger.info(f"[VerifyAgent] 验证完成，结论: {conclusion}, 摘要: {summary}")
                return conclusion, summary, tool_name, [current_image_path]

            elif tool_name == 'multi_image_assert':
                prev_step_index = select_result.get("prev_step_index",
                                                    current_step_index - 1 if current_step_index > 0 else 0)
                prev_image_path = self._get_image_path(prev_step_index)

                if not prev_image_path:
                    error_msg = f"无法找到上一个截图用于对比: {description}"
                    logger.error(f"[VerifyAgent] {error_msg}")
                    return False, error_msg, tool_name, []

                conclusion, summary = multi_image_assert(description, current_image_path, prev_image_path)
                logger.info(f"[VerifyAgent] 验证完成，结论: {conclusion}, 摘要: {summary}")
                return conclusion, summary, tool_name, [prev_image_path, current_image_path]

            elif tool_name == 'cross_step_image_assert':
                cross_step_index = select_result.get("cross_step_index")
                cross_step_scene_name = select_result.get("cross_step_scene_name")

                if cross_step_index is None or not cross_step_scene_name:
                    error_msg = f"跨步骤验证需要提供 cross_step_index 和 cross_step_scene_name: {description}"
                    logger.error(f"[VerifyAgent] {error_msg}")
                    return False, error_msg, tool_name, []

                cross_step_image_path = self._get_image_path(cross_step_index)
                if not cross_step_image_path:
                    error_msg = f"无法获取跨步骤图片路径: {description}"
                    logger.error(f"[VerifyAgent] {error_msg}")
                    return False, error_msg, tool_name, []

                conclusion, summary = cross_step_image_assert(description, current_image_path, cross_step_image_path,
                                                              cross_step_scene_name)
                logger.info(f"[VerifyAgent] 验证完成，结论: {conclusion}, 摘要: {summary}")
                return conclusion, summary, tool_name, [cross_step_image_path, current_image_path]

            elif tool_name == 'refer_image_assert':
                refer_step_index = select_result.get("refer_step_index", 0)
                refer_image_path = self._get_image_path(refer_step_index)

                if not refer_image_path:
                    error_msg = f"参考图片验证需要提供 refer_image_path: {description}"
                    logger.error(f"[VerifyAgent] {error_msg}")
                    return False, error_msg, tool_name, []

                conclusion, summary = refer_image_assert(description, current_image_path, refer_image_path)
                logger.info(f"[VerifyAgent] 验证完成，结论: {conclusion}, 摘要: {summary}")
                return conclusion, summary, tool_name, [refer_image_path, current_image_path]

            error_msg = f"未知的验证工具: {tool_name}"
            logger.error(f"[VerifyAgent] {error_msg}")
            return False, error_msg, tool_name, []

        except Exception as e:
            error_msg = f"验证执行异常: {str(e)}"
            logger.exception(f"[VerifyAgent] Verification error: {e}")
            return False, error_msg, tool_name, []

    def verify(self, description: str) -> Tuple[bool, str]:
        """执行验证任务

        根据用户的验证描述和历史执行记录，智能选择合适的验证工具和对应的步骤图片，
        然后调用验证工具执行验证并返回结果。

        支持的验证工具：
        - one_image_assert: 验证单个图片，适用于描述中只涉及当前页面
        - multi_image_assert: 验证两张图片的变化，适用于描述中涉及前后对比
        - cross_step_image_assert: 跨步骤验证，适用于描述中涉及跨步骤或跨场景的对比
        - refer_image_assert: 参考图片验证，适用于描述中需要与指定参考图片对比
        - video_assert: 视频验证，适用于描述中需要验证一段时间内的操作或场景变化

        Args:
            description: 验证描述，例如"页面展示正常"、"点击后页面有变化吗"

        Returns:
            Tuple[bool, str]: (是否通过, 验证摘要)
        """
        result, msg, tool_name, image_paths = self._verify(description)
        return result, msg
