"""Provider-agnostic message / tool schema.

Anthropic tool_use and OpenAI function_call both convert into these types.
Agent code only ever sees these — never provider-native structures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StopReason(str, Enum):
    END_TURN = "end_turn"        # Model finished naturally
    TOOL_USE = "tool_use"        # Model requested tool calls
    MAX_TOKENS = "max_tokens"    # Hit token limit
    STOP_SEQUENCE = "stop_sequence"
    ERROR = "error"


@dataclass
class ToolDef:
    """Provider-agnostic tool definition. Same JSON Schema for both providers."""
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema for parameters


@dataclass
class ToolCall:
    """A single tool invocation requested by the model.

    `id` is required for round-trip: the tool result must reference the same id
    so the model can correlate call → result across turns.
    """
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The outcome of executing a ToolCall, sent back to the model in the next turn."""
    tool_call_id: str
    content: str                       # Serialized (usually JSON) result
    is_error: bool = False


@dataclass
class Message:
    """One turn in the conversation.

    A single message can carry:
      - plain text (`content`)
      - tool_calls the assistant requested (assistant role)
      - tool_results the caller returns (tool role)
    """
    role: Role
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)

    @staticmethod
    def system(text: str) -> "Message":
        return Message(role=Role.SYSTEM, content=text)

    @staticmethod
    def user(text: str) -> "Message":
        return Message(role=Role.USER, content=text)

    @staticmethod
    def assistant(text: Optional[str] = None, tool_calls: Optional[list[ToolCall]] = None) -> "Message":
        return Message(role=Role.ASSISTANT, content=text, tool_calls=tool_calls or [])

    @staticmethod
    def tool(results: list[ToolResult]) -> "Message":
        return Message(role=Role.TOOL, tool_results=results)


@dataclass
class LLMUsage:
    """Token accounting reported by the provider (best-effort)."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResponse:
    """Non-streaming completion result."""
    text: str                                    # Concatenated assistant text (may be empty when tool_use)
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: StopReason = StopReason.END_TURN
    model: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw: Optional[dict] = None                   # Provider-native payload for debug

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def to_assistant_message(self) -> Message:
        """Convert this response into the assistant message to append to history."""
        return Message.assistant(text=self.text or None, tool_calls=self.tool_calls or None)


@dataclass
class LLMChunk:
    """Streaming delta. Only one of the fields is populated per chunk."""
    text_delta: Optional[str] = None
    tool_call_delta: Optional[ToolCall] = None   # Emitted when a tool_call is finalized
    stop_reason: Optional[StopReason] = None
    usage: Optional[LLMUsage] = None
