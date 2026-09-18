"""HypiumMCP device extension for agent."""
import traceback,os
from typing import List, Any, Optional
from dataclasses import dataclass
from ...devices.device_protocol import DeviceProtocol
from ...logger import logger


@dataclass
class ToolDefine:
    """Tool definition from MCP."""
    name: str
    description: str
    input_schema: dict
    output_schema: dict = None


@dataclass
class ToolCallResult:
    """Result of a tool call."""
    output: str
    success: bool
    error_msg: str = None


class MCPExtension:
    """HypiumMCP device extension for providing UI automation tools."""

    def __init__(self, device: DeviceProtocol,  special_test: bool = False):
        """
        Initialize HypiumMCP device.

        Args:
            device: Device
            special_test: Whether to enable special test.
        """
        self.device = device
        self.device_sn = device.device_id
        self.ip = device.ip
        self.port = device.port
        try:
            from hypium_mcp.config.config import get_config
            config = get_config()
            get_config().include_module = "app_manager,basic,general_gesture,plugins,screen"
            config.device_id = self.device_sn
            config.hdc_host = self.ip
            config.hdc_port = self.port
            from hypium_mcp.device import Device as HypiumMCPDevice
            self._mcp_device = HypiumMCPDevice(device_sn=self.device_sn, ip=self.ip, port=self.port)
            self.device.register_teardown_callback(self.clean_up)

            from hypium_mcp.device.device_manager import DeviceManager
            DeviceManager.get_instance()._devices[self.device_sn] = self._mcp_device._get_current_driver()

        except ImportError as e:
            logger.warning("HypiumMCP Extension load failed: %s", str(e))
            self._mcp_device = None

        self._tool_schema_cache: dict[str, dict] = {}
        self.include_prefixes = []
        self.exclude_names = [
            "get_current_app",
            "has_app",
            "install_app",
            "stop_all_app",
            "uninstall_app",
            "clear_recent_task",
            "get_app_bundle_name",
            "start_app",
            "stop_app",
            "rotate",
            "pinch_in",
            "pinch_out",
            "start_data_collect",
            "stop_data_collect",
            "generate_report"
        ]
        self._enable_special_test = special_test
        self._setup_special_checker()

    def _setup_special_checker(self):
        """
        Check if HypiumMCP device is initialized.

        Returns:
            bool: True if initialized, False otherwise.
        """
        if not self._enable_special_test:
            os.environ["HYPIUM_MCP_COLLECT_ENABLE"] = "False"
            return
        try:
            os.environ["HYPIUM_MCP_COLLECT_ENABLE"] = "True"
            self._mcp_device.call_tool("start_data_collect", {})
        except Exception as e:
            logger.warning("collector start failed: %s", str(e))
            logger.exception(e)

    def _teardown_special_checker(self):
        """
        Check if HypiumMCP device is teardown.

        Returns:
            bool: True if teardown, False otherwise.
        """
        if not self._enable_special_test:
            return
        try:
            self._mcp_device.call_tool("stop_data_collect", {})
        except Exception as e:
            logger.warning("collector stop failed: %s", str(e))

        try:
            self._mcp_device.call_tool("generate_report", {})
        except Exception as e:
            logger.warning("generate report failed: %s", str(e))

    def list_tools(
            self,
    ) -> List[ToolDefine]:
        """
        List available tools from HypiumMCP with optional filtering.

        Returns:
            List of ToolDefine objects matching the filter criteria.

        Raises:
            RuntimeError: If hypium_mcp SDK is not available.
        """
        if not self._mcp_device:
            raise RuntimeError("Fail to load hypium_mcp sdk, please install it")

        result = self._mcp_device.list_tools()
        tools = [
            ToolDefine(
                name=item.name,
                description=item.description,
                input_schema=item.parameters,
                output_schema=item.output_schema
            )
            for item in result
        ]

        if self.include_prefixes:
            tools = [t for t in tools if any(t.name.startswith(prefix) for prefix in self.include_prefixes)]

        if self.exclude_names:
            tools = [t for t in tools if t.name not in self.exclude_names]

        # Cache schema for coercion in call_tool
        for t in tools:
            self._tool_schema_cache[t.name] = t.input_schema or {}

        return tools

    @staticmethod
    def _coerce_value(value: Any, schema: dict) -> Any:
        """Coerce a value to the type declared in schema.

        Handles JSON Schema primitive types (integer, number, boolean,
        string), array (including `prefixItems` form produced by Pydantic
        for Tuple), object (nested), and `anyOf`/`oneOf` unions.

        Unknown/unmappable types keep the original value. Values that
        cannot be converted are kept as-is with a warning.
        """
        if value is None or not schema:
            return value

        # Resolve union types: pick the first sub-schema whose declared
        # type matches the value's shape, otherwise try each in order and
        # return the first successful coercion.
        for key in ("anyOf", "oneOf"):
            subs = schema.get(key)
            if subs:
                # Fast path: if value already matches a sub-schema type, keep it.
                for sub in subs:
                    sub_type = sub.get("type")
                    if sub_type == "null":
                        continue
                    if MCPExtension._type_matches(value, sub_type):
                        return MCPExtension._coerce_value(value, sub)
                # Slow path: try coercing to each non-null sub-schema.
                for sub in subs:
                    if sub.get("type") == "null":
                        continue
                    try:
                        return MCPExtension._coerce_value(value, sub)
                    except (ValueError, TypeError):
                        continue
                return value

        declared_type = schema.get("type")
        if not declared_type:
            return value

        try:
            if declared_type == "integer":
                if isinstance(value, bool):
                    # bool is subclass of int in Python; keep as-is to avoid surprises
                    return value
                if isinstance(value, (int, float)):
                    return int(value)
                if isinstance(value, str):
                    return int(float(value))
            elif declared_type == "number":
                if isinstance(value, bool):
                    return value
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    return float(value)
            elif declared_type == "boolean":
                if isinstance(value, bool):
                    return value
                if isinstance(value, (int, float)):
                    return bool(value)
                if isinstance(value, str):
                    low = value.strip().lower()
                    if low in ("true", "1", "yes", "y"):
                        return True
                    if low in ("false", "0", "no", "n", ""):
                        return False
            elif declared_type == "string":
                if not isinstance(value, str):
                    return str(value)
            elif declared_type == "array":
                if isinstance(value, (list, tuple)):
                    # Pydantic emits Tuple as `prefixItems` (fixed-length).
                    prefix = schema.get("prefixItems")
                    if prefix and len(prefix) == len(value):
                        return [MCPExtension._coerce_value(v, prefix[i]) for i, v in enumerate(value)]
                    item_schema = schema.get("items")
                    if item_schema:
                        return [MCPExtension._coerce_value(v, item_schema) for v in value]
                    return list(value)
                # LLM may pass a single value where an array is expected
                item_schema = schema.get("items")
                if item_schema:
                    return [MCPExtension._coerce_value(value, item_schema)]
            elif declared_type == "object":
                if isinstance(value, dict):
                    props = schema.get("properties", {})
                    return {k: MCPExtension._coerce_value(v, props.get(k, {})) for k, v in value.items()}
        except (ValueError, TypeError) as e:
            logger.warning(
                "[MCPExtension] Failed to coerce value %r to %s: %s; keeping original",
                value, declared_type, e
            )
            return value

        return value

    @staticmethod
    def _type_matches(value: Any, declared_type: Optional[str]) -> bool:
        """Check whether a Python value already matches a JSON Schema type."""
        if declared_type is None:
            return False
        if declared_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if declared_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if declared_type == "boolean":
            return isinstance(value, bool)
        if declared_type == "string":
            return isinstance(value, str)
        if declared_type == "array":
            return isinstance(value, (list, tuple))
        if declared_type == "object":
            return isinstance(value, dict)
        return False

    def _coerce_args(self, tool_name: str, tool_args: dict) -> dict:
        """Coerce tool arguments to match the tool's input schema types.

        Falls back to the schema cache populated by list_tools(); if the
        tool is unknown (e.g. excluded or dynamic), args are returned
        unchanged.
        """
        if not tool_args:
            return tool_args

        schema = self._tool_schema_cache.get(tool_name)
        if not schema:
            return tool_args

        properties = schema.get("properties")
        if not properties:
            return tool_args

        coerced = {}
        for key, value in tool_args.items():
            prop_schema = properties.get(key)
            if prop_schema:
                coerced[key] = self._coerce_value(value, prop_schema)
            else:
                coerced[key] = value
        return coerced

    def call_tool(self, tool_name: str, tool_args: dict) -> ToolCallResult:
        """
        Call a tool by name with arguments.

        Args:
            tool_name: Name of the tool to call.
            tool_args: Dictionary of tool arguments.

        Returns:
            ToolCallResult object containing the output and success status.

        Raises:
            RuntimeError: If hypium_mcp SDK is not available.
        """
        if not self._mcp_device:
            raise RuntimeError("Fail to load hypium_mcp sdk, please install it")

        # Lazily populate schema cache if empty (e.g. ToolPlayer path that
        # never called list_tools before call_tool).
        if not self._tool_schema_cache:
            try:
                self.list_tools()
            except Exception as e:
                logger.warning("[MCPExtension] lazy list_tools failed: %s", e)

        tool_args = self._coerce_args(tool_name, tool_args or {})
        try:
            result = self._mcp_device.call_tool(tool_name, tool_args)
            return ToolCallResult(
                output=result.content[0].text,
                success=True
            )
        except Exception as e:
            return ToolCallResult(
                output=repr(e),
                success=False,
                error_msg=traceback.format_exc()
            )

    def clean_up(self):
        """Clean up HypiumMCP resources."""
        if self._mcp_device:
            self._teardown_special_checker()
            self._mcp_device.clean_up()
