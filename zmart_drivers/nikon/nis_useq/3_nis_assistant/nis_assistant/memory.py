"""The assistant's memory: the conversation made smaller now and then, and a
quoted state block taken out of a reply."""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolReturnPart,
    UserPromptPart,
)

from .settings import (
    HISTORY_COMPACT_AFTER,
    HISTORY_FULL_TURNS,
    HISTORY_KEEP_TURNS,
    HISTORY_RESULT_CHARS,
)

STATE_BLOCK = re.compile(
    r"\s*<microscope_state(_then)?>.*?(</microscope_state(_then)?>|\Z)", re.DOTALL
)


def without_state_block(reply: str) -> str:
    """The reply without a copy of the <microscope_state> block.

    Some models paste the state reading they were sent back into their answer,
    although told not to. The operator should not see it, so it is taken out
    here. The model's own copy in the history stays as it was, since editing
    an earlier answer would spoil Claude's check on its earlier reasoning.
    """
    return STATE_BLOCK.sub("", reply).strip() or "(The assistant gave no answer in words.)"


def compact(messages: list[ModelMessage]) -> list[ModelMessage]:
    """The conversation made smaller once it has grown long, else unchanged.

    Once there are more than HISTORY_COMPACT_AFTER operator turns, the oldest are
    forgotten so that HISTORY_KEEP_TURNS remain. In those, all but the newest
    HISTORY_FULL_TURNS keep a one-line reading of the microscope instead of the
    whole state block, and long tool results are cut short. What the model and
    the operator said, and which tools were called, stays.

    Why only now and then, and between turns: Claude Opus 5.5 checks that its
    earlier reasoning (its "thinking") was written for exactly the conversation
    it is sent back with. Rewriting old turns on every message would make that
    check fail each time. So the history only ever grows, except at these
    compaction points, and there the old reasoning is left out altogether,
    which the check allows.
    """
    starts = [i for i, m in enumerate(messages) if _is_operator_turn(m)]
    if len(starts) <= HISTORY_COMPACT_AFTER:
        return messages
    kept = messages[starts[-HISTORY_KEEP_TURNS] :]
    full_from = starts[-HISTORY_FULL_TURNS] - starts[-HISTORY_KEEP_TURNS]  # index in kept
    out: list[ModelMessage] = []
    for index, message in enumerate(kept):
        if isinstance(message, ModelResponse):
            parts = [p for p in message.parts if not isinstance(p, ThinkingPart)]
            message = dataclasses.replace(message, parts=parts or [TextPart("(no reply)")])
        elif index < full_from:
            message = dataclasses.replace(message, parts=[_shorten(p) for p in message.parts])
        out.append(message)
    return out


def _is_operator_turn(message: ModelMessage) -> bool:
    return isinstance(message, ModelRequest) and isinstance(message.parts[0], UserPromptPart)


def _shorten(part: Any) -> Any:
    """An older message part, made small: a one-line state reading, a cut tool result."""
    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
        match = re.search(r"<microscope_state>(.*?)</microscope_state>", part.content, re.DOTALL)
        if match:
            state = json.loads(match.group(1))
            then = {"position_um": state.get("position_um"), "objective": state.get("objective")}
            reading = f"<microscope_state_then>{json.dumps(then)}</microscope_state_then>"
            content = part.content[: match.start()] + reading + part.content[match.end() :]
            return dataclasses.replace(part, content=content)
    if isinstance(part, ToolReturnPart):
        text = part.content if isinstance(part.content, str) else json.dumps(part.content)
        if len(text) > HISTORY_RESULT_CHARS:
            return dataclasses.replace(
                part, content=text[:HISTORY_RESULT_CHARS] + " ... (shortened in memory)"
            )
    return part
