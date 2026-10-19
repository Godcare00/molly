from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from pydantic import BaseModel, Field
import inspect
import json


class RiskLevel:
    READ = "READ"
    LOW_RISK = "LOW_RISK"
    MODERATE = "MODERATE"
    HIGH_RISK = "HIGH_RISK"
    DANGEROUS = "DANGEROUS"
    CRITICAL = "CRITICAL"

    ALL = [READ, LOW_RISK, MODERATE, HIGH_RISK, DANGEROUS, CRITICAL]

    @classmethod
    def requires_approval(cls, level: str) -> bool:
        return level in (cls.MODERATE, cls.HIGH_RISK, cls.DANGEROUS, cls.CRITICAL)

    @classmethod
    def always_requires_approval(cls, level: str) -> bool:
        """Risk levels that stay gated even under a conversation's allow_all
        setting or a task's "approve all" trust for a tool. This is the hard
        floor: nothing bypasses approval for these."""
        return level in (cls.DANGEROUS, cls.CRITICAL)

    @classmethod
    def from_string(cls, s: str) -> str:
        s = s.upper()
        if s in cls.ALL:
            return s
        return cls.MODERATE


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: list[Any] = field(default_factory=list)


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: list[ToolParameter]
    risk_level: str = RiskLevel.READ
    timeout_seconds: int = 30
    output_limit_chars: int = 10000

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function calling schema."""
        properties = {}
        required = []

        for param in self.parameters:
            param_schema = {"type": param.type, "description": param.description}
            if param.enum:
                param_schema["enum"] = param.enum
            properties[param.name] = param_schema
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }

    def to_anthropic_schema(self) -> dict:
        """Convert to Anthropic Messages API tool schema."""
        properties = {}
        required = []

        for param in self.parameters:
            param_schema = {"type": param.type, "description": param.description}
            if param.enum:
                param_schema["enum"] = param.enum
            properties[param.name] = param_schema
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def to_gemini_schema(self) -> dict:
        """Convert to a Gemini `FunctionDeclaration` dict (Live API tool use).

        Same shape as the Anthropic schema minus the `input_schema` wrapper
        name - Gemini expects `parameters` directly, uppercase JSON-schema
        `type` values, and does not accept `additionalProperties`.
        """
        properties = {}
        required = []

        for param in self.parameters:
            param_schema = {"type": param.type.upper(), "description": param.description}
            if param.enum:
                param_schema["enum"] = param.enum
            properties[param.name] = param_schema
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "OBJECT",
                "properties": properties,
                "required": required,
            },
        }


class ToolResult(BaseModel):
    success: bool
    output: Any = None
    error: Optional[str] = None
    truncated: bool = False
    metadata: dict = Field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all tools."""

    name: str = ""
    description: str = ""
    risk_level: str = RiskLevel.READ
    timeout_seconds: int = 30
    output_limit_chars: int = 10000

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        pass

    def get_schema(self) -> ToolSchema:
        """Generate schema from execute method signature."""
        sig = inspect.signature(self.execute)
        parameters = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            param_type = "string"
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    param_type = "integer"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif param.annotation == float:
                    param_type = "number"
                elif param.annotation == list:
                    param_type = "array"
                elif param.annotation == dict:
                    param_type = "object"

            default = None
            required = True
            if param.default != inspect.Parameter.empty:
                default = param.default
                required = False

            parameters.append(
                ToolParameter(
                    name=param_name,
                    type=param_type,
                    description=f"Parameter {param_name}",
                    required=required,
                    default=default,
                )
            )

        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=parameters,
            risk_level=self.risk_level,
            timeout_seconds=self.timeout_seconds,
            output_limit_chars=self.output_limit_chars,
        )


class ToolRegistry:
    """Central tool registry - single source of truth for all tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._schemas: dict[str, ToolSchema] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        self._schemas[tool.name] = tool.get_schema()

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_schema(self, name: str) -> Optional[ToolSchema]:
        """Get a tool schema by name."""
        return self._schemas.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_all_schemas(self) -> list[dict]:
        """Get all tool schemas in OpenAI format."""
        return [schema.to_openai_schema() for schema in self._schemas.values()]

    def get_all_gemini_schemas(self) -> list[dict]:
        """Get all tool schemas as Gemini `FunctionDeclaration` dicts."""
        return [schema.to_gemini_schema() for schema in self._schemas.values()]

    def get_tool_names_by_risk(self, risk_level: str) -> list[str]:
        """Get tool names filtered by risk level."""
        return [
            name
            for name, schema in self._schemas.items()
            if schema.risk_level == risk_level
        ]


# Global registry instance
registry = ToolRegistry()