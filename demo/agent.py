"""A minimal tool-calling loop: a Qwen model (OpenAI-compatible API) driving the Perspective MCP tools."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.types import Tool
from openai import AsyncOpenAI

MAX_TOOL_ROUNDS = 5
SYSTEM_PROMPT = """You are a markets assistant. Today is {today}.
Use the tools to fetch Yahoo Finance data. Every chart, table and dashboard they create is shown to the user automatically,
so reply with a short commentary on the key numbers and never repeat links, tables or raw data.
{instructions}"""


@dataclass
class Settings:
    model: str
    base_url: str
    api_key: str
    mcp_url: str
    thinking: Literal["auto", "on", "off"] = "auto"

    @property
    def extra_body(self) -> dict | None:
        return None if self.thinking == "auto" else {"enable_thinking": self.thinking == "on"}


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[str] = field(default_factory=list)
    visualizations: list[dict] = field(default_factory=list)


def as_openai_tool(tool: Tool) -> dict:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description or "", "parameters": tool.input_schema},
    }


def text_of(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if block.type == "text")


async def respond(
    history: list[dict], settings: Settings, on_tool_call: Callable[[str], None] = lambda call: None
) -> Turn:
    turn = Turn()
    async with (
        Client(settings.mcp_url) as mcp,
        AsyncOpenAI(base_url=settings.base_url, api_key=settings.api_key) as llm,
    ):
        tools = [as_openai_tool(tool) for tool in await mcp.list_tools()]
        system = SYSTEM_PROMPT.format(today=date.today(), instructions=mcp.instructions or "")
        messages = [{"role": "system", "content": system}, *history]

        for _ in range(MAX_TOOL_ROUNDS):
            completion = await llm.chat.completions.create(
                model=settings.model, messages=messages, tools=tools, extra_body=settings.extra_body
            )
            message = completion.choices[0].message
            if not message.tool_calls:
                turn.text = message.content or ""
                return turn

            messages.append(message.model_dump(include={"role", "content", "tool_calls"}))
            for call in message.tool_calls:
                arguments = json.loads(call.function.arguments or "{}")
                label = f"{call.function.name}({json.dumps(arguments)})"
                turn.tool_calls.append(label)
                on_tool_call(label)
                result = await mcp.call_tool(call.function.name, arguments, raise_on_error=False)
                if result.structured_content and "url" in result.structured_content:
                    turn.visualizations.append(result.structured_content)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": text_of(result)})

    turn.text = "I stopped after too many tool calls, try a more specific question."
    return turn
