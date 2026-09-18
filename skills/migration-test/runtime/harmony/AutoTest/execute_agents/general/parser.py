import ast
import json
import re
from typing import Any
from ...logger import logger


class GeneralParser:
    @property
    def coordinate_scale(self) -> int:
        return 1000

    def parse(self, raw_response: str, screen_width: int, screen_height: int) -> dict[str, Any]:
        content = raw_response.strip()

        complete = self._extract_complete_goal(content)
        if complete is not None:
            return {"_metadata": "finish", "message": complete}

        error_message = self._extract_tag_content(content, "error")
        if error_message:
            return {"_metadata": "finish", "message": error_message}

        # Extract optional log
        log_content = self._extract_tag_content(content, "log")

        action_type = self._extract_tag_content(content, "action-type")
        if not action_type:
            raise ValueError("Missing action-type")

        action_params = self._extract_tag_content(content, "action-param-json")
        params = self._parse_params(action_params)

        action = self._map_action(
            action_type.strip(),
            params,
            screen_width,
            screen_height,
        )
        if action is None:
            logger.warning("content: {}".format(content))
            return {"_metadata": "finish", "message": f"Unsupported action: {action_type}"}

        # Attach log to action if present
        if log_content:
            action["log"] = log_content.strip()

        return action

    def _extract_complete_goal(self, content: str) -> str | None:
        match = re.search(
            r"<complete-goal\b[^>]*>([\s\S]*?)</complete-goal>",
            content,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        message = match.group(1).strip()
        return message or "Task completed"

    def _extract_tag_content(self, content: str, tag: str) -> str | None:
        pattern = rf"<{tag}>([\s\S]*?)</{tag}>"
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

    def _parse_params(self, text: str | None) -> dict[str, Any]:
        if not text:
            return {}
        text = text.strip()
        text = re.sub(r'//.*?$', '', text, flags=re.MULTILINE)
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                prev_text = None
                while prev_text != text:
                    prev_text = text
                    text = re.sub(r'(\d+)\s+(\d+)', r'\1, \2', text)
                value = ast.literal_eval(text)
                if isinstance(value, dict):
                    return value
            except Exception:
                return {}
        return {}

    def _map_action(
            self,
            action_type: str,
            params: dict[str, Any],
            screen_width: int,
            screen_height: int,
    ) -> dict[str, Any] | None:
        if action_type == "Tap":
            point = self._resolve_point(params.get("element") or params.get("locate"), screen_width, screen_height)
            if point:
                return {"_metadata": "do", "action": "Tap", "element": point}
            return None

        if action_type == "Double Tap":
            point = self._resolve_point(params.get("element") or params.get("locate"), screen_width, screen_height)
            if point:
                return {"_metadata": "do", "action": "Double Tap", "element": point}
            return None

        if action_type == "Long Press":
            point = self._resolve_point(params.get("element") or params.get("locate"), screen_width, screen_height)
            if point:
                duration = int(params.get("duration", 2))
                return {"_metadata": "do", "action": "Long Press", "element": point, "duration": duration}
            return None

        if action_type == "Type":
            text = params.get("text") or params.get("value", "")
            return {"_metadata": "do", "action": "Type", "text": text}

        if action_type == "Swipe":
            start = self._resolve_point(params.get("start"), screen_width, screen_height)
            end = self._resolve_point(params.get("end"), screen_width, screen_height)
            if start and end:
                return {
                    "_metadata": "do",
                    "action": "Swipe",
                    "start": start,
                    "end": end,
                }
            return None
        if action_type == "Drag":
            start = self._resolve_point(params.get("start"), screen_width, screen_height)
            end = self._resolve_point(params.get("end"), screen_width, screen_height)
            if start and end:
                return {
                    "_metadata": "do",
                    "action": "Drag",
                    "start": start,
                    "end": end,
                    "press_time": float(params.get("press_time", 1.5)),
                    "drag_time": float(params.get("drag_time", 1)),
                }
            return None

        if action_type == "Back":
            return {"_metadata": "do", "action": "Back"}

        if action_type == "Home":
            return {"_metadata": "do", "action": "Home"}

        if action_type == "Launch":
            app = params.get("app") or params.get("uri")
            if app:
                return {"_metadata": "do", "action": "Launch", "app": app}
            return None

        if action_type == "Wait":
            duration = params.get("duration", "1 seconds")
            return {"_metadata": "do", "action": "Wait", "duration": duration}

        if action_type == "Clear Text":
            return {"_metadata": "do", "action": "Clear Text"}

        if action_type == "Pinch In":
            rect = self._resolve_rect(params.get("rect"), screen_width, screen_height)
            if rect:
                return {
                    "_metadata": "do",
                    "action": "Pinch In",
                    "rect": rect,
                    "scale": float(params.get("scale", 0.4)),
                    "direction": params.get("direction", "diagonal"),
                }
            # If rect is missing, try to resolve from element (backward compatibility)
            if params.get("element"):
                rect = self._resolve_rect(params.get("element"), screen_width, screen_height)
                if rect:
                    return {
                        "_metadata": "do",
                        "action": "Pinch In",
                        "rect": rect,
                        "scale": float(params.get("scale", 0.4)),
                        "direction": params.get("direction", "diagonal"),
                    }
            return None

        if action_type == "Pinch Out":
            rect = self._resolve_rect(params.get("rect"), screen_width, screen_height)
            if rect:
                return {
                    "_metadata": "do",
                    "action": "Pinch Out",
                    "rect": rect,
                    "scale": float(params.get("scale", 1.6)),
                    "direction": params.get("direction", "diagonal"),
                }
            # If rect is missing, try to resolve from element (backward compatibility)
            if params.get("element"):
                rect = self._resolve_rect(params.get("element"), screen_width, screen_height)
                if rect:
                    return {
                        "_metadata": "do",
                        "action": "Pinch Out",
                        "rect": rect,
                        "scale": float(params.get("scale", 1.6)),
                        "direction": params.get("direction", "diagonal"),
                    }
            return None

        return None

    def _resolve_point(
            self, value: Any, screen_width: int, screen_height: int
    ) -> list[int] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            if "bbox" in value and isinstance(value["bbox"], (list, tuple)):
                bbox = value["bbox"]
                if len(bbox) == 4:
                    x1 = self._normalize_coord(bbox[0], screen_width)
                    y1 = self._normalize_coord(bbox[1], screen_height)
                    x2 = self._normalize_coord(bbox[2], screen_width)
                    y2 = self._normalize_coord(bbox[3], screen_height)
                    if None not in (x1, y1, x2, y2):
                        return [int((x1 + x2) / 2), int((y1 + y2) / 2)]
            if "x" in value and "y" in value:
                x = self._normalize_coord(value["x"], screen_width)
                y = self._normalize_coord(value["y"], screen_height)
                if x is not None and y is not None:
                    return [x, y]
            return None
        if isinstance(value, (list, tuple)):
            if len(value) == 2:
                x = self._normalize_coord(value[0], screen_width)
                y = self._normalize_coord(value[1], screen_height)
                if x is not None and y is not None:
                    return [x, y]
            if len(value) == 4:
                return self._resolve_point({"bbox": value}, screen_width, screen_height)
        return None

    def _resolve_rect(
            self, value: Any, screen_width: int, screen_height: int
    ) -> list[int] | None:
        """Resolve a rectangle from element/rect parameter to [left, top, right, bottom]."""
        if value is None:
            return None
        if isinstance(value, dict):
            if "bbox" in value and isinstance(value["bbox"], (list, tuple)):
                bbox = value["bbox"]
                if len(bbox) == 4:
                    x1 = self._normalize_coord(bbox[0], screen_width)
                    y1 = self._normalize_coord(bbox[1], screen_height)
                    x2 = self._normalize_coord(bbox[2], screen_width)
                    y2 = self._normalize_coord(bbox[3], screen_height)
                    if None not in (x1, y1, x2, y2):
                        return [int(x1), int(y1), int(x2), int(y2)]
            if "left" in value and "top" in value and "right" in value and "bottom" in value:
                left = self._normalize_coord(value["left"], screen_width)
                top = self._normalize_coord(value["top"], screen_height)
                right = self._normalize_coord(value["right"], screen_width)
                bottom = self._normalize_coord(value["bottom"], screen_height)
                if None not in (left, top, right, bottom):
                    return [int(left), int(top), int(right), int(bottom)]
            return None
        if isinstance(value, (list, tuple)):
            if len(value) == 4:
                left = self._normalize_coord(value[0], screen_width)
                top = self._normalize_coord(value[1], screen_height)
                right = self._normalize_coord(value[2], screen_width)
                bottom = self._normalize_coord(value[3], screen_height)
                if None not in (left, top, right, bottom):
                    return [int(left), int(top), int(right), int(bottom)]
        return None

    def _normalize_coord(self, value: Any, total: int) -> int | None:
        try:
            coord = float(value)
        except (TypeError, ValueError):
            return None
        if coord <= 1:
            return int(coord * total)
        if coord <= self.coordinate_scale:
            return int(coord / self.coordinate_scale * total)
        return int(coord)

    def _build_swipe_by_direction(
            self,
            direction: str | None,
            distance: Any,
            screen_width: int,
            screen_height: int,
    ) -> tuple[list[int] | None, list[int] | None]:
        if direction not in {"up", "down", "left", "right"}:
            return None, None
        center_x = int(screen_width * 0.5)
        center_y = int(screen_height * 0.5)
        if direction in {"up", "down"}:
            dist = self._normalize_distance(distance, screen_height, 0.4)
            if direction == "up":
                start = [center_x, int(center_y + dist / 2)]
                end = [center_x, int(center_y - dist / 2)]
            else:
                start = [center_x, int(center_y - dist / 2)]
                end = [center_x, int(center_y + dist / 2)]
        else:
            dist = self._normalize_distance(distance, screen_width, 0.4)
            if direction == "left":
                start = [int(center_x + dist / 2), center_y]
                end = [int(center_x - dist / 2), center_y]
            else:
                start = [int(center_x - dist / 2), center_y]
                end = [int(center_x + dist / 2), center_y]
        start = [self._clamp(start[0], 0, screen_width), self._clamp(start[1], 0, screen_height)]
        end = [self._clamp(end[0], 0, screen_width), self._clamp(end[1], 0, screen_height)]
        return start, end

    def _normalize_distance(self, value: Any, total: int, fallback_ratio: float) -> float:
        if value is None:
            return total * fallback_ratio
        try:
            dist = float(value)
        except (TypeError, ValueError):
            return total * fallback_ratio
        if dist <= 1:
            return total * dist
        if dist <= self.coordinate_scale:
            return total * (dist / self.coordinate_scale)
        return dist

    def _clamp(self, value: int, min_value: int, max_value: int) -> int:
        return max(min_value, min(value, max_value))
