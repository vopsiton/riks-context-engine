"""Tool Calling Abstraction Layer.

Provides a unified interface for tool-calling across multiple AI providers:
- OpenAI function calling
- Anthropic tool use
- Google Gemini function declarations
- Custom JSON schemas

Uses the adapter pattern to normalise inputs and outputs so tools
defined once work with any supported provider.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Shared data classes
# ---------------------------------------------------------------------------


class Provider(Enum):
    """Supported AI providers with tool-calling capabilities."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    CUSTOM = "custom"


@dataclass
class ToolParameter:
    """A single parameter for a tool / function."""

    name: str
    type: str
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[str] | None = None
    schema_extra: dict[str, Any] = field(default_factory=dict)

    def to_openai(self) -> dict[str, Any]:
        """Render as an OpenAI ``functions`` / ``tools`` parameter."""
        prop: dict[str, Any] = {"type": self.type}
        if self.description:
            prop["description"] = self.description
        if self.enum:
            prop["enum"] = self.enum
        prop.update(self.schema_extra)
        return prop

    def to_anthropic(self) -> dict[str, Any]:
        """Render as an Anthropic tool ``input_schema`` property."""
        spec: dict[str, Any] = {"type": self.type}
        if self.description:
            spec["description"] = self.description
        if self.enum:
            spec["enum"] = self.enum
        spec.update(self.schema_extra)
        return spec

    def to_gemini(self) -> dict[str, Any]:
        """Render as a Gemini function declaration parameter."""
        spec: dict[str, Any] = {"type": self.type}
        if self.description:
            spec["description"] = self.description
        if self.enum:
            spec["enum"] = self.enum
        spec.update(self.schema_extra)
        return spec

    def to_custom(self) -> dict[str, Any]:
        """Render as a raw JSON Schema property."""
        spec: dict[str, Any] = {"type": self.type}
        if self.description:
            spec["description"] = self.description
        if self.required:
            spec["minLength"] = 1  # sentinel; callers should check required list
        if self.enum:
            spec["enum"] = self.enum
        spec.update(self.schema_extra)
        return spec


@dataclass
class ToolDefinition:
    """A complete tool / function definition that can be converted to any
    supported provider format."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    required_params: list[str] = field(default_factory=list)
    provider: Provider = Provider.CUSTOM
    raw_schema: dict[str, Any] | None = None  # bypass constructor for custom schemas

    def __post_init__(self) -> None:
        # If required_params not supplied, infer from ToolParameter.required
        if not self.required_params:
            self.required_params = [p.name for p in self.parameters if p.required]

    # -- Conversions ---------------------------------------------------------

    def to_openai(self) -> dict[str, Any]:
        """Render as an OpenAI ``functions`` item or ``tools`` entry."""
        properties: dict[str, Any] = {}
        required: list[str] = list(self.required_params)

        if self.raw_schema and self.provider == Provider.CUSTOM:
            # Honour a pre-built custom schema verbatim
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.raw_schema,
                },
            }

        for param in self.parameters:
            properties[param.name] = param.to_openai()

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        """Render as an Anthropic tool-use ``tools`` entry."""
        if self.raw_schema and self.provider == Provider.CUSTOM:
            return {
                "name": self.name,
                "description": self.description,
                "input_schema": self.raw_schema,
            }

        properties: dict[str, Any] = {}
        required: list[str] = list(self.required_params)

        for param in self.parameters:
            properties[param.name] = param.to_anthropic()

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def to_gemini(self) -> dict[str, Any]:
        """Render as a Gemini ``function_declaration``."""
        if self.raw_schema and self.provider == Provider.CUSTOM:
            return {
                "name": self.name,
                "description": self.description,
                "parameters": self.raw_schema,
            }

        properties: dict[str, Any] = {}
        required: list[str] = list(self.required_params)

        for param in self.parameters:
            properties[param.name] = param.to_gemini()

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def to_custom(self) -> dict[str, Any]:
        """Render as a raw JSON Schema (no provider wrapping)."""
        if self.raw_schema:
            return self.raw_schema

        properties: dict[str, Any] = {}
        required: list[str] = list(self.required_params)

        for param in self.parameters:
            properties[param.name] = param.to_custom()

        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": properties,
            "required": required,
        }

    # -- Factory helpers ------------------------------------------------------

    @classmethod
    def from_openai(cls, payload: dict[str, Any]) -> ToolDefinition:
        """Reconstruct a ``ToolDefinition`` from an OpenAI ``functions`` item."""
        fn = payload.get("function", payload)
        raw_schema = fn.get("parameters")
        params = []
        if raw_schema and "properties" in raw_schema:
            required = set(raw_schema.get("required", []))
            for name, prop in raw_schema["properties"].items():
                params.append(
                    ToolParameter(
                        name=name,
                        type=prop.get("type", "string"),
                        description=prop.get("description", ""),
                        required=name in required,
                        enum=prop.get("enum"),
                        schema_extra={
                            k: v
                            for k, v in prop.items()
                            if k not in ("type", "description", "enum")
                        },
                    )
                )
        return cls(
            name=fn["name"],
            description=fn.get("description", ""),
            parameters=params,
            required_params=list(raw_schema.get("required", [])) if raw_schema else [],
            provider=Provider.OPENAI,
            raw_schema=raw_schema,
        )

    @classmethod
    def from_anthropic(cls, payload: dict[str, Any]) -> ToolDefinition:
        """Reconstruct from an Anthropic ``tools`` entry."""
        raw_schema = payload.get("input_schema")
        params = []
        if raw_schema and "properties" in raw_schema:
            required = set(raw_schema.get("required", []))
            for name, prop in raw_schema["properties"].items():
                params.append(
                    ToolParameter(
                        name=name,
                        type=prop.get("type", "string"),
                        description=prop.get("description", ""),
                        required=name in required,
                        enum=prop.get("enum"),
                        schema_extra={
                            k: v
                            for k, v in prop.items()
                            if k not in ("type", "description", "enum")
                        },
                    )
                )
        return cls(
            name=payload["name"],
            description=payload.get("description", ""),
            parameters=params,
            required_params=list(raw_schema.get("required", [])) if raw_schema else [],
            provider=Provider.ANTHROPIC,
            raw_schema=raw_schema,
        )

    @classmethod
    def from_gemini(cls, payload: dict[str, Any]) -> ToolDefinition:
        """Reconstruct from a Gemini ``function_declaration``."""
        raw_schema = payload.get("parameters")
        params = []
        if raw_schema and "properties" in raw_schema:
            required = set(raw_schema.get("required", []))
            for name, prop in raw_schema["properties"].items():
                params.append(
                    ToolParameter(
                        name=name,
                        type=prop.get("type", "string"),
                        description=prop.get("description", ""),
                        required=name in required,
                        enum=prop.get("enum"),
                        schema_extra={
                            k: v
                            for k, v in prop.items()
                            if k not in ("type", "description", "enum")
                        },
                    )
                )
        return cls(
            name=payload["name"],
            description=payload.get("description", ""),
            parameters=params,
            required_params=list(raw_schema.get("required", [])) if raw_schema else [],
            provider=Provider.GEMINI,
            raw_schema=raw_schema,
        )


@dataclass
class ToolCallResult:
    """The result of a resolved tool call (i.e. what the model saw)."""

    tool_name: str
    arguments: dict[str, Any]
    raw: dict[str, Any]  # provider-native representation
    provider: Provider

    def to_openai(self) -> dict[str, Any]:
        """Render as an OpenAI ``tool_call`` / ``function`` message."""
        args_str = json.dumps(self.arguments)
        return {
            "id": self.raw.get("id", "call_0"),
            "type": "function",
            "function": {
                "name": self.tool_name,
                "arguments": args_str,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        """Render as an Anthropic ``tool_use`` content block."""
        return {
            "tool": self.tool_name,
            "input": self.arguments,
        }

    def to_gemini(self) -> dict[str, Any]:
        """Render as a Gemini ``function_call``."""
        return {
            "name": self.tool_name,
            "args": self.arguments,
        }


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class ToolAdapter(ABC):
    """Abstract base for provider-specific tool adapters."""

    provider: Provider

    @abstractmethod
    def wrap_tools(self, tools: list[ToolDefinition]) -> Any:
        """Convert a list of ``ToolDefinition`` to the provider's native format."""

    @abstractmethod
    def unwrap_results(self, raw_results: list[Any]) -> list[ToolCallResult]:
        """Parse provider-native tool call results into ``ToolCallResult`` objects."""

    @abstractmethod
    def wrap_result_message(self, results: list[ToolCallResult]) -> Any:
        """Package resolved tool results into the format expected by the
        provider's chat completion API."""

    # -- Shared helpers ------------------------------------------------------

    def _ensure_list(self, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return [value]
        return list(value)


class OpenAIToolAdapter(ToolAdapter):
    """Adapter for OpenAI function-calling / tool-use API."""

    provider = Provider.OPENAI

    def wrap_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [tool.to_openai() for tool in tools]

    def unwrap_results(self, raw_results: list[dict[str, Any]]) -> list[ToolCallResult]:
        results: list[ToolCallResult] = []
        for item in self._ensure_list(raw_results):
            fn = item.get("function", item)
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, str):
                arguments = json.loads(raw_args)
            else:
                arguments = raw_args
            results.append(
                ToolCallResult(
                    tool_name=fn["name"],
                    arguments=arguments,
                    raw=item,
                    provider=self.provider,
                )
            )
        return results

    def wrap_result_message(self, results: list[ToolCallResult]) -> dict[str, Any]:
        tool_calls = [r.to_openai() for r in results]
        return {"role": "tool", "tool_calls": tool_calls}


class AnthropicToolAdapter(ToolAdapter):
    """Adapter for Anthropic tool-use API."""

    provider = Provider.ANTHROPIC

    def wrap_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [tool.to_anthropic() for tool in tools]

    def unwrap_results(self, raw_results: list[dict[str, Any]]) -> list[ToolCallResult]:
        results: list[ToolCallResult] = []
        for item in self._ensure_list(raw_results):
            results.append(
                ToolCallResult(
                    tool_name=item.get("name", item.get("tool", "")),
                    arguments=item.get("input", item.get("parameters", {})),
                    raw=item,
                    provider=self.provider,
                )
            )
        return results

    def wrap_result_message(self, results: list[ToolCallResult]) -> list[dict[str, Any]]:
        return [{"type": "tool_use", **r.to_anthropic()} for r in results]


class GeminiToolAdapter(ToolAdapter):
    """Adapter for Google Gemini function calling."""

    provider = Provider.GEMINI

    def wrap_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [{"function_declarations": [tool.to_gemini() for tool in tools]}]

    def unwrap_results(self, raw_results: list[dict[str, Any]]) -> list[ToolCallResult]:
        results: list[ToolCallResult] = []
        for item in self._ensure_list(raw_results):
            fc = item.get("functionCall", item)
            results.append(
                ToolCallResult(
                    tool_name=fc.get("name", ""),
                    arguments=fc.get("args", fc.get("arguments", {})),
                    raw=item,
                    provider=self.provider,
                )
            )
        return results

    def wrap_result_message(self, results: list[ToolCallResult]) -> list[dict[str, Any]]:
        return [
            {"functionResponse": {"name": r.tool_name, "response": r.arguments}} for r in results
        ]


class CustomSchemaAdapter(ToolAdapter):
    """Adapter for raw JSON Schema / custom tool definitions."""

    provider = Provider.CUSTOM

    def wrap_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {"name": tool.name, "description": tool.description, "parameters": tool.to_custom()}
            for tool in tools
        ]

    def unwrap_results(self, raw_results: list[dict[str, Any]]) -> list[ToolCallResult]:
        results: list[ToolCallResult] = []
        for item in self._ensure_list(raw_results):
            results.append(
                ToolCallResult(
                    tool_name=item.get("name", item.get("tool_name", "")),
                    arguments=item.get("arguments", item.get("input", {})),
                    raw=item,
                    provider=self.provider,
                )
            )
        return results

    def wrap_result_message(self, results: list[ToolCallResult]) -> list[dict[str, Any]]:
        return [{"tool": r.tool_name, "arguments": r.arguments} for r in results]


# ---------------------------------------------------------------------------
# Unified registry
# ---------------------------------------------------------------------------

_ADAPTERS: dict[Provider, ToolAdapter] = {
    Provider.OPENAI: OpenAIToolAdapter(),
    Provider.ANTHROPIC: AnthropicToolAdapter(),
    Provider.GEMINI: GeminiToolAdapter(),
    Provider.CUSTOM: CustomSchemaAdapter(),
}


def get_adapter(provider: Provider | str) -> ToolAdapter:
    """Return the adapter for the given provider."""
    if isinstance(provider, str):
        try:
            provider = Provider(provider)
        except ValueError:
            raise ValueError(
                f"Unknown provider {provider!r}. Supported: {[p.value for p in Provider]}"
            )
    if provider not in _ADAPTERS:
        raise ValueError(
            f"No adapter registered for provider {provider!r}. "
            f"Supported: {[p.value for p in Provider]}"
        )
    return _ADAPTERS[provider]


def register_adapter(adapter: ToolAdapter) -> None:
    """Register (or override) an adapter for a custom provider."""
    _ADAPTERS[adapter.provider] = adapter


__all__ = [
    "ToolAdapter",
    "ToolCallResult",
    "ToolDefinition",
    "ToolParameter",
    "Provider",
    "OpenAIToolAdapter",
    "AnthropicToolAdapter",
    "GeminiToolAdapter",
    "CustomSchemaAdapter",
    "get_adapter",
    "register_adapter",
]
