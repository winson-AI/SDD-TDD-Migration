import json
import re
from locale import normalize
from typing import Optional, List
from lxml import etree

from ..logger import logger


class LayoutElement:
    """Represents a UI element from layout."""

    def __init__(
        self,
        element_type: str,
        text: str,
        id: str,
        key: str,
        bounds: str,
        hierarchy: str,
        depth: int
    ):
        self.element_type = element_type
        self.text = text
        self.id = id
        self.key = key
        self.bounds = bounds
        self.hierarchy = hierarchy
        self.depth = depth

        match = re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
        if match:
            self.x1 = int(match.group(1))
            self.y1 = int(match.group(2))
            self.x2 = int(match.group(3))
            self.y2 = int(match.group(4))
            self.center_x = (self.x1 + self.x2) // 2
            self.center_y = (self.y1 + self.y2) // 2
        else:
            self.x1 = self.y1 = self.x2 = self.y2 = self.center_x = self.center_y = 0

    def contains_point(self, x: int, y: int) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def contains_point_with_tolerance(self, x: int, y: int, tolerance: int) -> bool:
        """判断点是否在元素 bounds 外扩 tolerance 像素范围内。

        用于点击坐标轻微偏移目标元素时的容差命中。
        """
        return (self.x1 - tolerance) <= x <= (self.x2 + tolerance) and \
               (self.y1 - tolerance) <= y <= (self.y2 + tolerance)

    def distance_to_bounds(self, x: int, y: int) -> float:
        """点到元素 bounds 矩形的最短距离（点在内部时为 0）。

        相比 distance_to_point（到中心距离），此度量对"点击坐标
        轻微偏出目标元素"的场景更合理：紧邻元素边缘外的点距离很小。
        """
        if self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2:
            return 0.0
        dx = max(self.x1 - x, 0, x - self.x2)
        dy = max(self.y1 - y, 0, y - self.y2)
        return (dx * dx + dy * dy) ** 0.5

    def distance_to_point(self, x: int, y: int) -> float:
        return ((self.center_x - x) ** 2 + (self.center_y - y) ** 2) ** 0.5


class LayoutToXPath:
    """Convert HarmonyOS layout JSON to XPath."""

    def __init__(self, layout_json: str):
        self.elements: List[LayoutElement] = []
        self._xml_tree = None
        self._parse_layout(layout_json)

    def _json_to_xml(self, json_str: str) -> str:
        """Convert json layout to xml string."""
        def escape_char(raw_string):
            if raw_string is None:
                return ""
            return (str(raw_string)
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("&", "&amp;")
                    .replace("'", "&apos;")
                    .replace('"', "&quot;"))

        def json_to_xml_node(node_dict):
            if isinstance(node_dict, str):
                return ""

            attrs = node_dict.get("attributes", {})
            tag = attrs.get("type", "node")
            attrs = {attr: attrs.get(attr) for attr in attrs if attr not in {"type", "children"}}
            if "value" in node_dict:
                xml_str = "<{tag} {attrs}>{value}</{tag}>".format(
                    tag=tag,
                    attrs=" ".join('{}="{}"'.format(key, escape_char(val)) for key, val in attrs.items() if val),
                    value=escape_char(node_dict["value"])
                )
            else:
                inner_xml = ''.join(json_to_xml_node(child) for child in node_dict.get("children", []))
                xml_str = "<{tag} {attrs}>{inner_xml}</{tag}>".format(
                    tag=tag,
                    attrs=" ".join('{}="{}"'.format(key, escape_char(val)) for key, val in attrs.items() if val),
                    inner_xml=inner_xml
                )
            return xml_str

        if isinstance(json_str, str):
            try:
                json_dict = json.loads(json_str)
            except json.JSONDecodeError:
                return json_str
        else:
            json_dict = json_str

        attrs = json_dict.get("attributes", {})
        attrs = {attr: attrs.get(attr) for attr in attrs if attr not in {"type", "children"}}
        tag = attrs.get("type", "orgRoot")
        inner_xml = ''.join(json_to_xml_node(child) for child in json_dict.get("children", []))
        xml_str = "<{tag} {attrs}>{inner_xml}</{tag}>".format(
            tag=tag,
            attrs=" ".join('{}="{}"'.format(key, escape_char(val)) for key, val in attrs.items() if val),
            inner_xml=inner_xml
        )
        return xml_str

    def _parse_layout(self, layout_json: str):
        try:
            xml_str = self._json_to_xml(layout_json)
            self._xml_tree = etree.fromstring(xml_str.encode('utf-8'))
            self._extract_elements(self._xml_tree, depth=0)
        except Exception as e:
            logger.error(f"[LayoutToXPath] Failed to parse layout: {e}")

    def _extract_elements(self, node, depth: int):
        attrs = dict(node.attrib)

        text = attrs.get('text', '')
        elem_id = attrs.get('id', '')
        key = attrs.get('key', '')
        bounds = attrs.get('bounds', '')
        hierarchy = attrs.get('hierarchy', '')

        element = LayoutElement(
            element_type=node.tag,
            text=text,
            id=elem_id,
            key=key,
            bounds=bounds,
            hierarchy=hierarchy,
            depth=depth
        )

        if bounds:
            self.elements.append(element)

        for child in node:
            self._extract_elements(child, depth + 1)

    # 点击坐标偏离目标元素时的容差像素数。
    # 当 LLM 给出的坐标轻微偏出 target_text 对应元素的 bounds 时，
    # 在该容差范围内仍视为命中，避免回退到大容器。
    CLICK_TOLERANCE_PX = 30

    def find_element_at(self, x: int, y: int, target_text: str = "") -> Optional[LayoutElement]:
        candidates = [e for e in self.elements if e.contains_point(x, y)]
        # 无严格命中候选时，尝试容差命中（仅当布局中存在任意元素时才回退，
        # 避免坐标完全离谱时还强行选一个元素）
        if not candidates:
            return None

        normalized_target_text = target_text.strip()
        if normalized_target_text:
            # 1) 严格命中 + target_text 精确匹配（最优）
            text_matches = [
                e for e in candidates
                if e.text and e.text.strip() == normalized_target_text
            ]
            if text_matches:
                return max(text_matches, key=lambda e: e.depth)

            # 2) 容差命中：点击坐标轻微偏出目标元素 bounds 时，
            #    在全量元素中按 target_text 匹配，并用容差范围过滤。
            #    优先选取距离 bounds 边缘最近的元素（更贴近真实点击意图）。
            tolerance_matches = [
                e for e in self.elements
                if e.text and e.text.strip() == normalized_target_text
                and e.contains_point_with_tolerance(x, y, self.CLICK_TOLERANCE_PX)
            ]
            if tolerance_matches:
                return min(tolerance_matches, key=lambda e: e.distance_to_bounds(x, y))

        # 3) 严格命中中任意非空文本元素（按 depth 降序，同 depth 取距离中心最近）
        text_candidates = [e for e in candidates if e.text and e.text.strip()]
        if text_candidates:
            return max(text_candidates, key=lambda e: (e.depth, -e.distance_to_point(x, y)))

        # 4) 兜底：先按 depth 降序（最深/最小容器），同 depth 按 distance 升序（最近）
        return max(candidates, key=lambda e: (e.depth, -e.distance_to_point(x, y)))

    def _escape_xpath(self, value: str) -> str:
        if not value:
            return value
        return (value
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("'", "&apos;")
                .replace('"', "&quot;"))

    def _find_elements_by_xpath(self, xpath: str) -> List:
        """Find elements in local XML tree by xpath.

        NOTE: 本地 XML 树的根节点为 orgRoot，对于绝对路径 xpath（如 /root/Stack/Text）
        需要补全 /orgRoot 前缀才能在本地树上正确匹配，与 hypium 的 _convert_absolute_path 逻辑一致。
        """
        try:
            if xpath.startswith("/") and not xpath.startswith("//") and not xpath.startswith("/orgRoot"):
                xpath = "/orgRoot" + xpath
            return self._xml_tree.xpath(xpath)
        except Exception:
            return []

    def _has_index_issue(self, xpath: str, target_bounds: str) -> bool:
        """Check if xpath matches multiple elements (index issue)."""
        elements = self._find_elements_by_xpath(xpath)
        if len(elements) <= 1:
            return False

        matching_count = sum(1 for e in elements if dict(e.attrib).get('bounds', '') == target_bounds)
        return matching_count > 1

    def _is_xpath_unique(self, xpath: str, target_bounds: str) -> bool:
        """Check if xpath matches exactly one element with matching bounds."""
        if not xpath:
            return False

        elements = self._find_elements_by_xpath(xpath)
        if len(elements) != 1:
            return False

        matched_bounds = dict(elements[0].attrib).get('bounds', '')
        return matched_bounds == target_bounds

    def _try_generate_xpath(
        self,
        element: LayoutElement,
        use_id: bool = False,
        use_key: bool = False,
        use_text: bool = False,
        use_type: bool = False
    ) -> str:
        """Generate xpath with specified attribute combinations."""
        conditions = []
        tag = element.element_type if element.element_type else "*"

        if use_id and element.id:
            conditions.append(f"@id='{self._escape_xpath(element.id)}'")
        if use_key and element.key:
            conditions.append(f"@key='{self._escape_xpath(element.key)}'")
        if use_text and element.text:
            conditions.append(f"@text='{self._escape_xpath(element.text)}'")

        if not conditions:
            return ""

        cond_str = " and ".join(conditions)
        return f"//{tag}[{cond_str}]"

    def _build_simple_xpath(self, element: LayoutElement) -> str:
        """Build simple xpath using id/key/text/type."""
        conditions = []

        if element.id:
            escaped_id = self._escape_xpath(element.id)
            conditions.append(f"@id='{escaped_id}'")
        elif element.key:
            escaped_key = self._escape_xpath(element.key)
            conditions.append(f"@key='{escaped_key}'")
        elif element.text:
            escaped_text = self._escape_xpath(element.text)
            conditions.append(f"@text='{escaped_text}'")

        tag = element.element_type if element.element_type else "*"
        if conditions:
            cond_str = " and ".join(conditions)
            return f"//{tag}[{cond_str}]"
        return f"//{tag}"

    def _find_element_node(self, target_bounds: str, node=None, depth=0):
        """Find XML node with matching bounds."""
        if node is None:
            node = self._xml_tree

        current_bounds = dict(node.attrib).get('bounds', '')

        if current_bounds == target_bounds:
            return node

        for child in node:
            result = self._find_element_node(target_bounds, child, depth + 1)
            if result is not None:
                return result

        return None

    def _get_xpath_to_node(self, target_node):
        """Build full xpath from root to target node (without virtual root prefix).

        NOTE: 不包含虚拟根节点(/orgRoot)，因为 hypium 的 _convert_absolute_path
        在回放时会自动添加 /orgRoot 前缀，包含会导致双重前缀匹配失败。
        """
        xpath = ""

        current = target_node
        ancestors = []

        while current is not None and current != self._xml_tree:
            ancestors.append(current)
            current = current.getparent()

        ancestors.reverse()

        for node in ancestors[:-1] if ancestors else []:
            tag = node.tag
            parent = node.getparent()
            if parent is not None:
                siblings = [c for c in parent if c.tag == tag]
                if len(siblings) > 1:
                    tag_index = siblings.index(node)
                    xpath += f"/{tag}[{tag_index + 1}]"
                else:
                    xpath += f"/{tag}"

        if ancestors:
            tag = ancestors[-1].tag
            parent = ancestors[-1].getparent()
            if parent is not None:
                siblings = [c for c in parent if c.tag == tag]
                if len(siblings) > 1:
                    tag_index = siblings.index(ancestors[-1])
                    xpath += f"/{tag}[{tag_index + 1}]"
                else:
                    xpath += f"/{tag}"
            else:
                xpath += f"/{tag}"

        return xpath

    def _build_full_xpath(self, element: LayoutElement) -> str:
        """Build full path xpath with hierarchical indices for stability.
        
        NEVER uses bounds-based xpath to ensure cross-device compatibility.
        If no stable identifier can be generated, returns an empty string.
        """
        if not element.bounds:
            return self._try_generate_xpath(
                element,
                use_id=True, use_key=True, use_text=True
            )

        target_node = self._find_element_node(element.bounds)
        if target_node is not None:
            index_xpath = self._get_xpath_to_node(target_node)
            if index_xpath and self._is_xpath_unique(index_xpath, element.bounds):
                logger.info(f"[LayoutToXPath] Using index-based xpath: {index_xpath}")
                return index_xpath

            attributes_xpath = self._build_indexed_attributes_xpath(element, target_node)
            if attributes_xpath:
                logger.info(f"[LayoutToXPath] Using indexed-attributes xpath: {attributes_xpath}")
                return attributes_xpath

        logger.error(f"[LayoutToXPath] Cannot generate stable xpath for element with bounds: {element.bounds}")
        return ""

    def _build_indexed_attributes_xpath(self, element: LayoutElement, target_node) -> str:
        """Build xpath combining hierarchical index with available attributes."""
        tag = element.element_type if element.element_type else "*"

        if element.id:
            return f"//{tag}[@id='{self._escape_xpath(element.id)}']"

        if element.key:
            return f"//{tag}[@key='{self._escape_xpath(element.key)}']"

        if element.text:
            return f"//{tag}[@text='{self._escape_xpath(element.text)}']"

        ancestors_xpath = self._get_xpath_to_node(target_node)
        if ancestors_xpath:
            return ancestors_xpath

        return ""

    def to_xpath(self, element: LayoutElement) -> str:
        """Generate unique xpath for element with priority: text > id > key > index-based path.
        
        NEVER generates bounds-based xpath. Returns empty string if no stable xpath is possible.
        """
        if not element.bounds:
            logger.warning("[LayoutToXPath] No bounds for element")
            return ""

        xpath = self._try_generate_xpath(element, use_text=True)
        if xpath and self._is_xpath_unique(xpath, element.bounds):
            logger.info(f"[LayoutToXPath] Using text-based xpath: {xpath}")
            return xpath

        xpath = self._try_generate_xpath(element, use_id=True)
        if xpath and self._is_xpath_unique(xpath, element.bounds):
            logger.info(f"[LayoutToXPath] Using id-based xpath: {xpath}")
            return xpath

        xpath = self._try_generate_xpath(element, use_key=True)
        if xpath and self._is_xpath_unique(xpath, element.bounds):
            logger.info(f"[LayoutToXPath] Using key-based xpath: {xpath}")
            return xpath

        logger.warning("[LayoutToXPath] All simple xpaths failed, attempting index-based fallback")
        full_xpath = self._build_full_xpath(element)

        if full_xpath:
            logger.info(f"[LayoutToXPath] Successfully generated stable xpath: {full_xpath}")
        else:
            logger.error(f"[LayoutToXPath] Failed to generate stable xpath - element may not be reliably locatable")

        return full_xpath

    def to_full_xpath(self, element: LayoutElement) -> str:
        """强制生成完整层级路径 xpath（跳过 text/id/key 简单 xpath）。

        适用于搜索框/输入框场景：命中的元素通常是搜索历史/热搜/联想词等
        动态内容，其 text/id/key 在回放时不可靠，应使用结构化的完整路径
        （如 /root/.../Text，hypium 回放时自动补全虚拟根节点）以保证可定位性。

        Returns:
            完整层级路径 xpath；若无法生成稳定路径则返回空字符串。
        """
        if not element.bounds:
            logger.warning("[LayoutToXPath] No bounds for element (to_full_xpath)")
            return ""

        full_xpath = self._build_full_xpath(element)
        if full_xpath:
            logger.info(f"[LayoutToXPath] Using full-path xpath (search-box scenario): {full_xpath}")
        else:
            logger.error(
                "[LayoutToXPath] Failed to generate full-path xpath for search-box scenario"
            )
        return full_xpath
