import asyncio
import json
import time
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from agents.executor import ClaudeOutput

StreamEventType = Literal["assistant", "tool_use", "tool_result", "result", "system", "unknown"]


class StreamEvent(BaseModel):
    type: StreamEventType
    content: str = ""
    tool_name: str = ""
    timestamp: float


def parse_stream_line(line: str) -> StreamEvent | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    event_type = data.get("type", "")

    if event_type == "rate_limit_event":
        return None
    if event_type == "system":
        subtype = data.get("subtype", "")
        if subtype.startswith("hook_"):
            return None
        if subtype == "init":
            return StreamEvent(type="system", content="session started", timestamp=time.time())
        return None

    if event_type == "assistant":
        message = data.get("message", {})
        content_blocks = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content_blocks, list):
            return None
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                return StreamEvent(
                    type="assistant",
                    content=block.get("text", ""),
                    timestamp=time.time(),
                )
            if block_type == "tool_use":
                return StreamEvent(
                    type="tool_use",
                    tool_name=block.get("name", ""),
                    content=json.dumps(block.get("input", {}))[:200],
                    timestamp=time.time(),
                )
            if block_type == "thinking":
                return None
        return None

    if event_type == "user":
        message = data.get("message", {})
        content_blocks = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content_blocks, list):
            return None
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                raw = block.get("content", "")
                content_str = raw if isinstance(raw, str) else json.dumps(raw)
                return StreamEvent(
                    type="tool_result",
                    content=content_str[:500],
                    timestamp=time.time(),
                )
        return None

    if event_type == "result":
        return StreamEvent(type="result", content=data.get("result", ""), timestamp=time.time())

    return None


def extract_result_from_line(line: str) -> ClaudeOutput:
    data = json.loads(line)
    return ClaudeOutput(
        result=data.get("result", ""),
        is_error=data.get("is_error", False),
        cost_usd=data.get("total_cost_usd", 0.0),
        num_turns=data.get("num_turns", 0),
    )


class RunStream:
    def __init__(self, run_id: str, on_event: Callable) -> None:
        self.run_id = run_id
        self.on_event = on_event
        self.raw_lines: list[str] = []

    async def process_stream(self, proc: asyncio.subprocess.Process) -> ClaudeOutput:
        last_result: ClaudeOutput | None = None
        async for line in proc.stdout:
            text = line.decode().strip()
            if not text:
                continue
            self.raw_lines.append(text)
            event = parse_stream_line(text)
            if event:
                await self.on_event(self.run_id, event)
                if event.type == "result":
                    last_result = extract_result_from_line(text)
        await proc.wait()
        return last_result or ClaudeOutput(is_error=True, result="No result received")

    def get_raw_output(self) -> str:
        return "\n".join(self.raw_lines)
