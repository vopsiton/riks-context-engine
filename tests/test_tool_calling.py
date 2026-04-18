"""Tests for the Tool Calling Abstraction Layer."""

from __future__ import annotations

import json
from typing import Any

import pytest

from riks_context_engine.abstractions.tool_calling import (
    AnthropicToolAdapter,
    CustomSchemaAdapter,
    GeminiToolAdapter,
    OpenAIToolAdapter,
    Provider,
    ToolAdapter,
    ToolCallResult,
    ToolDefinition,
    ToolParameter,
    get_adapter,
    register_adapter,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def weather_tool() -> ToolDefinition:
    """A minimal weather-fetching tool used across tests."""
    return ToolDefinition(
        name="get_weather",
        description="Fetch the current weather for a given city.",
        parameters=[
            ToolParameter(
                name="city",
                type="string",
                description="The name of the city (e.g. Istanbul).",
                required=True,
            ),
            ToolParameter(
                name="unit",
                type="string",
                description="Temperature unit: celsius or fahrenheit.",
                required=False,
                default="celsius",
                enum=["celsius", "fahrenheit"],
            ),
        ],
        required_params=["city"],
    )


@pytest.fixture
def calculator_tool() -> ToolDefinition:
    """A tool with integer parameters."""
    return ToolDefinition(
        name="calculate",
        description="Perform a basic arithmetic operation.",
        parameters=[
            ToolParameter(name="a", type="integer", description="First operand.", required=True),
            ToolParameter(name="b", type="integer", description="Second operand.", required=True),
            ToolParameter(
                name="operation",
                type="string",
                description="One of add, subtract, multiply, divide.",
                required=True,
                enum=["add", "subtract", "multiply", "divide"],
            ),
        ],
        required_params=["a", "b", "operation"],
    )


# ---------------------------------------------------------------------------
# ToolParameter
# ---------------------------------------------------------------------------

class TestToolParameter:
    def test_to_openai(self) -> None:
        param = ToolParameter(
            name="city",
            type="string",
            description="City name",
            required=True,
            enum=["Istanbul", "Ankara"],
        )
        result = param.to_openai()
        assert result["type"] == "string"
        assert result["description"] == "City name"
        assert result["enum"] == ["Istanbul", "Ankara"]

    def test_to_anthropic(self) -> None:
        param = ToolParameter(name="age", type="integer", description="User age")
        result = param.to_anthropic()
        assert result["type"] == "integer"
        assert result["description"] == "User age"

    def test_to_gemini(self) -> None:
        param = ToolParameter(name="query", type="string", description="Search query")
        result = param.to_gemini()
        assert result["type"] == "string"
        assert result["description"] == "Search query"

    def test_schema_extra_passed_through(self) -> None:
        param = ToolParameter(
            name="limit",
            type="integer",
            description="Max results",
            schema_extra={"minimum": 1, "maximum": 100},
        )
        result = param.to_openai()
        assert result["minimum"] == 1
        assert result["maximum"] == 100


# ---------------------------------------------------------------------------
# ToolDefinition
# ---------------------------------------------------------------------------

class TestToolDefinition:
    def test_required_params_inferred_from_parameters(self) -> None:
        tool = ToolDefinition(
            name="test",
            description="A test tool",
            parameters=[
                ToolParameter(name="req", type="string", required=True),
                ToolParameter(name="opt", type="string", required=False),
            ],
        )
        assert tool.required_params == ["req"]

    def test_required_params_explicit(self) -> None:
        tool = ToolDefinition(
            name="test",
            description="A test tool",
            parameters=[
                ToolParameter(name="x", type="string", required=True),
                ToolParameter(name="y", type="string", required=True),
            ],
            required_params=["x"],
        )
        assert tool.required_params == ["x"]

    def test_to_openai(self, weather_tool: ToolDefinition) -> None:
        result = weather_tool.to_openai()
        assert result["type"] == "function"
        assert result["function"]["name"] == "get_weather"
        assert result["function"]["description"] == "Fetch the current weather for a given city."
        params = result["function"]["parameters"]
        assert params["type"] == "object"
        assert "city" in params["properties"]
        assert params["properties"]["city"]["type"] == "string"
        assert "unit" in params["properties"]
        assert params["properties"]["unit"]["enum"] == ["celsius", "fahrenheit"]
        assert params["required"] == ["city"]

    def test_to_anthropic(self, weather_tool: ToolDefinition) -> None:
        result = weather_tool.to_anthropic()
        assert result["name"] == "get_weather"
        assert result["description"] == "Fetch the current weather for a given city."
        schema = result["input_schema"]
        assert schema["type"] == "object"
        assert "city" in schema["properties"]
        assert schema["required"] == ["city"]

    def test_to_gemini(self, weather_tool: ToolDefinition) -> None:
        result = weather_tool.to_gemini()
        assert result["name"] == "get_weather"
        assert result["description"] == "Fetch the current weather for a given city."
        params = result["parameters"]
        assert params["type"] == "object"
        assert "city" in params["properties"]
        assert params["required"] == ["city"]

    def test_to_custom(self, calculator_tool: ToolDefinition) -> None:
        result = calculator_tool.to_custom()
        assert result["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert result["type"] == "object"
        assert "a" in result["properties"]
        assert "b" in result["properties"]
        assert "operation" in result["properties"]
        assert result["required"] == ["a", "b", "operation"]

    def test_to_openai_with_raw_schema(self) -> None:
        raw = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
        tool = ToolDefinition(
            name="search",
            description="Search the web",
            parameters=[],
            provider=Provider.CUSTOM,
            raw_schema=raw,
        )
        result = tool.to_openai()
        assert result["function"]["name"] == "search"
        assert result["function"]["parameters"] == raw

    def test_from_openai(self) -> None:
        payload = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"},
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["city"],
                },
            },
        }
        tool = ToolDefinition.from_openai(payload)
        assert tool.name == "get_weather"
        assert tool.description == "Get weather"
        assert tool.provider == Provider.OPENAI
        assert len(tool.parameters) == 2
        city_param = next(p for p in tool.parameters if p.name == "city")
        assert city_param.type == "string"
        assert city_param.required is True
        unit_param = next(p for p in tool.parameters if p.name == "unit")
        assert unit_param.enum == ["celsius", "fahrenheit"]

    def test_from_anthropic(self) -> None:
        payload = {
            "name": "calculate",
            "description": "Math",
            "input_schema": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["x"],
            },
        }
        tool = ToolDefinition.from_anthropic(payload)
        assert tool.name == "calculate"
        assert tool.provider == Provider.ANTHROPIC
        x_param = next(p for p in tool.parameters if p.name == "x")
        assert x_param.required is True
        y_param = next(p for p in tool.parameters if p.name == "y")
        assert y_param.required is False

    def test_from_gemini(self) -> None:
        payload = {
            "name": "search",
            "description": "Web search",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        }
        tool = ToolDefinition.from_gemini(payload)
        assert tool.name == "search"
        assert tool.provider == Provider.GEMINI
        assert len(tool.parameters) == 1


# ---------------------------------------------------------------------------
# ToolCallResult
# ---------------------------------------------------------------------------

class TestToolCallResult:
    def test_to_openai(self) -> None:
        raw = {"id": "call_1", "type": "function",
               "function": {"name": "get_weather", "arguments": '{"city": "Istanbul"}'}}
        result = ToolCallResult(
            tool_name="get_weather",
            arguments={"city": "Istanbul"},
            raw=raw,
            provider=Provider.OPENAI,
        )
        output = result.to_openai()
        assert output["id"] == "call_1"
        assert output["function"]["name"] == "get_weather"
        assert json.loads(output["function"]["arguments"]) == {"city": "Istanbul"}

    def test_to_anthropic(self) -> None:
        raw = {"name": "get_weather", "input": {"city": "Istanbul"}}
        result = ToolCallResult(
            tool_name="get_weather",
            arguments={"city": "Istanbul"},
            raw=raw,
            provider=Provider.ANTHROPIC,
        )
        output = result.to_anthropic()
        assert output["tool"] == "get_weather"
        assert output["input"] == {"city": "Istanbul"}

    def test_to_gemini(self) -> None:
        raw = {"functionCall": {"name": "get_weather", "args": {"city": "Istanbul"}}}
        result = ToolCallResult(
            tool_name="get_weather",
            arguments={"city": "Istanbul"},
            raw=raw,
            provider=Provider.GEMINI,
        )
        output = result.to_gemini()
        assert output["name"] == "get_weather"
        assert output["args"] == {"city": "Istanbul"}


# ---------------------------------------------------------------------------
# OpenAIToolAdapter
# ---------------------------------------------------------------------------

class TestOpenAIToolAdapter:
    def test_wrap_tools(self, weather_tool: ToolDefinition) -> None:
        adapter = OpenAIToolAdapter()
        wrapped = adapter.wrap_tools([weather_tool])
        assert len(wrapped) == 1
        assert wrapped[0]["type"] == "function"
        assert wrapped[0]["function"]["name"] == "get_weather"

    def test_unwrap_results(self) -> None:
        adapter = OpenAIToolAdapter()
        raw = [
            {
                "id": "call_0",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"city": "Ankara"}',
                },
            }
        ]
        results = adapter.unwrap_results(raw)
        assert len(results) == 1
        assert results[0].tool_name == "get_weather"
        assert results[0].arguments == {"city": "Ankara"}
        assert results[0].provider == Provider.OPENAI

    def test_unwrap_results_dict_args(self) -> None:
        adapter = OpenAIToolAdapter()
        raw = [{"id": "call_0", "type": "function",
                "function": {"name": "get_weather", "arguments": {"city": "Ankara"}}}]
        results = adapter.unwrap_results(raw)
        assert results[0].arguments == {"city": "Ankara"}

    def test_wrap_result_message(self) -> None:
        adapter = OpenAIToolAdapter()
        results = [
            ToolCallResult(
                tool_name="get_weather",
                arguments={"city": "Istanbul"},
                raw={},
                provider=Provider.OPENAI,
            )
        ]
        msg = adapter.wrap_result_message(results)
        assert msg["role"] == "tool"
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["function"]["name"] == "get_weather"


# ---------------------------------------------------------------------------
# AnthropicToolAdapter
# ---------------------------------------------------------------------------

class TestAnthropicToolAdapter:
    def test_wrap_tools(self, weather_tool: ToolDefinition) -> None:
        adapter = AnthropicToolAdapter()
        wrapped = adapter.wrap_tools([weather_tool])
        assert len(wrapped) == 1
        assert wrapped[0]["name"] == "get_weather"
        assert "input_schema" in wrapped[0]

    def test_unwrap_results(self) -> None:
        adapter = AnthropicToolAdapter()
        raw = [{"name": "get_weather", "input": {"city": "Izmir"}}]
        results = adapter.unwrap_results(raw)
        assert len(results) == 1
        assert results[0].tool_name == "get_weather"
        assert results[0].arguments == {"city": "Izmir"}
        assert results[0].provider == Provider.ANTHROPIC

    def test_wrap_result_message(self) -> None:
        adapter = AnthropicToolAdapter()
        results = [
            ToolCallResult(
                tool_name="get_weather",
                arguments={"city": "Istanbul"},
                raw={},
                provider=Provider.ANTHROPIC,
            )
        ]
        msg = adapter.wrap_result_message(results)
        assert isinstance(msg, list)
        assert msg[0]["type"] == "tool_use"
        assert msg[0]["tool"] == "get_weather"


# ---------------------------------------------------------------------------
# GeminiToolAdapter
# ---------------------------------------------------------------------------

class TestGeminiToolAdapter:
    def test_wrap_tools(self, weather_tool: ToolDefinition) -> None:
        adapter = GeminiToolAdapter()
        wrapped = adapter.wrap_tools([weather_tool])
        assert len(wrapped) == 1
        declarations = wrapped[0]["function_declarations"]
        assert len(declarations) == 1
        assert declarations[0]["name"] == "get_weather"

    def test_unwrap_results(self) -> None:
        adapter = GeminiToolAdapter()
        raw = [{"functionCall": {"name": "get_weather", "args": {"city": "Bursa"}}}]
        results = adapter.unwrap_results(raw)
        assert len(results) == 1
        assert results[0].tool_name == "get_weather"
        assert results[0].arguments == {"city": "Bursa"}
        assert results[0].provider == Provider.GEMINI

    def test_unwrap_results_flat(self) -> None:
        adapter = GeminiToolAdapter()
        raw = {"functionCall": {"name": "get_weather", "args": {"city": "Bursa"}}}
        results = adapter.unwrap_results(raw)
        assert len(results) == 1

    def test_wrap_result_message(self) -> None:
        adapter = GeminiToolAdapter()
        results = [
            ToolCallResult(
                tool_name="get_weather",
                arguments={"city": "Istanbul"},
                raw={},
                provider=Provider.GEMINI,
            )
        ]
        msg = adapter.wrap_result_message(results)
        assert isinstance(msg, list)
        assert msg[0]["functionResponse"]["name"] == "get_weather"


# ---------------------------------------------------------------------------
# CustomSchemaAdapter
# ---------------------------------------------------------------------------

class TestCustomSchemaAdapter:
    def test_wrap_tools(self, calculator_tool: ToolDefinition) -> None:
        adapter = CustomSchemaAdapter()
        wrapped = adapter.wrap_tools([calculator_tool])
        assert len(wrapped) == 1
        assert wrapped[0]["name"] == "calculate"
        assert "parameters" in wrapped[0]

    def test_unwrap_results(self) -> None:
        adapter = CustomSchemaAdapter()
        raw = [{"name": "calculate", "arguments": {"a": 1, "b": 2, "operation": "add"}}]
        results = adapter.unwrap_results(raw)
        assert len(results) == 1
        assert results[0].tool_name == "calculate"
        assert results[0].arguments == {"a": 1, "b": 2, "operation": "add"}
        assert results[0].provider == Provider.CUSTOM


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_get_adapter_openai(self) -> None:
        adapter = get_adapter(Provider.OPENAI)
        assert isinstance(adapter, OpenAIToolAdapter)

    def test_get_adapter_anthropic(self) -> None:
        adapter = get_adapter(Provider.ANTHROPIC)
        assert isinstance(adapter, AnthropicToolAdapter)

    def test_get_adapter_gemini(self) -> None:
        adapter = get_adapter(Provider.GEMINI)
        assert isinstance(adapter, GeminiToolAdapter)

    def test_get_adapter_string(self) -> None:
        adapter = get_adapter("openai")
        assert isinstance(adapter, OpenAIToolAdapter)

    def test_get_adapter_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            get_adapter("unknown_provider")

    def test_register_adapter(self) -> None:
        class CustomAdapter(ToolAdapter):
            provider = Provider.CUSTOM

            def wrap_tools(self, tools: list[ToolDefinition]) -> Any:
                return tools

            def unwrap_results(self, raw_results: list[Any]) -> list[ToolCallResult]:
                return []

            def wrap_result_message(self, results: list[ToolCallResult]) -> Any:
                return []

        register_adapter(CustomAdapter())
        adapter = get_adapter(Provider.CUSTOM)
        assert isinstance(adapter, CustomAdapter)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_openai_roundtrip(self, weather_tool: ToolDefinition) -> None:
        openai_format = weather_tool.to_openai()
        reconstructed = ToolDefinition.from_openai(openai_format)
        re_exported = reconstructed.to_openai()
        assert (
            re_exported["function"]["parameters"]["properties"]["city"]
            == openai_format["function"]["parameters"]["properties"]["city"]
        )

    def test_anthropic_roundtrip(self, weather_tool: ToolDefinition) -> None:
        anth_format = weather_tool.to_anthropic()
        reconstructed = ToolDefinition.from_anthropic(anth_format)
        re_exported = reconstructed.to_anthropic()
        assert (
            re_exported["input_schema"]["properties"]["city"]
            == anth_format["input_schema"]["properties"]["city"]
        )

    def test_gemini_roundtrip(self, weather_tool: ToolDefinition) -> None:
        gem_format = weather_tool.to_gemini()
        reconstructed = ToolDefinition.from_gemini(gem_format)
        re_exported = reconstructed.to_gemini()
        assert (
            re_exported["parameters"]["properties"]["city"]
            == gem_format["parameters"]["properties"]["city"]
        )
