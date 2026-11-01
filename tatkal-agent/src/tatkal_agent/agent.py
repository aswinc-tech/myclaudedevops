"""The planning agent: Claude + the Tatkal MCP tools.

Claude decides *what* to do (which trains/classes to rank, what fare cap to
propose, when to log in, how to react when the executor reports a sell-out or
a fare above the cap). The MCP server enforces *what is allowed* (human
approval, OTP from the human, approved bounds). The executor does the
time-critical work without an LLM in the loop.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any

import anthropic
from mcp.client.client import Client

MODEL = os.getenv("TATKAL_AGENT_MODEL", "claude-opus-5-5")
MAX_TURNS = 40

SYSTEM_PROMPT = """You are a Tatkal train-booking agent working for one traveller. Your goal is a
CONFIRMED ticket for their journey, booked through the tools provided.

How Tatkal works: the quota opens one day before the journey date, at 10:00 IST for AC classes
(1A, 2A, 3A, 3E, CC, EC) and 11:00 IST for non-AC (SL, 2S). Popular trains sell out of
confirmed berths within a minute or two, so the plan must be decided BEFORE the window opens.

Your job:
1. Understand the request. Check the window time, search trains, check availability and fares.
2. Build a ranked plan of 2-6 options (best first). Prefer options likely to give confirmed
   berths: the traveller's preferred train/class first, then alternatives on the same route and
   date (other trains, adjacent classes). Remember AC and non-AC windows open an hour apart:
   a non-AC fallback after an AC sell-out is a real second chance.
3. Pick a fare cap for ALL passengers that covers the options you ranked, with a small margin.
4. Call propose_booking_plan. The traveller reviews it. If they decline or comment, adapt and
   propose again; never try to book without an approved plan.
5. Call login shortly before execution (the traveller enters the OTP; you never see it).
6. Call execute_booking_plan. It handles timing and retries on its own.
7. If the result has `needs_human`, decide the next step: ask_human for a decision outside the
   approved bounds (higher fare cap, RAC/waitlist, another date) and propose a new plan if needed.
   If it is confirmed, report the PNR, train, class, berths and fare.

Rules: never ask for passwords, OTPs or payment details in chat. Keep messages short and
concrete. Do not claim a ticket is confirmed unless a tool result says so."""


def _mcp_tools_to_anthropic(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
        for t in tools
    ]


def _result_text(result: Any) -> str:
    if result.structured_content is not None:
        return json.dumps(result.structured_content, default=str)
    parts = [getattr(c, "text", "") for c in result.content]
    return "\n".join(p for p in parts if p) or "(no content)"


async def run_agent(
    request: str,
    server: Any,
    elicitation_callback: Any,
    printer: Callable[[str], None] = lambda s: print(s, flush=True),
    model: str = MODEL,
) -> str:
    """Run the agent until it finishes. `server` is an MCPServer instance (in-process)
    or StdioServerParameters (subprocess)."""
    claude = anthropic.AsyncAnthropic()  # credentials from env / `ant auth login`; never hardcoded

    # legacy handshake: supports server-initiated elicitation (our human-in-the-loop channel)
    async with Client(server, mode="legacy", elicitation_callback=elicitation_callback) as mcp:
        tools = _mcp_tools_to_anthropic((await mcp.list_tools()).tools)
        messages: list[dict[str, Any]] = [{"role": "user", "content": request}]

        for _ in range(MAX_TURNS):
            response = await claude.beta.messages.create(
                model=model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": "high"},
                # Server-side refusal fallback: if the model declines, the API re-runs the
                # request on a fallback model chosen by refusal category.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            # Append the full content (incl. thinking blocks) unchanged; never edit history.
            messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "thinking" and getattr(block, "thinking", ""):
                    printer(f"  (thinking) {block.thinking.strip()[:400]}")
                elif block.type == "text" and block.text.strip():
                    printer(f"\nAgent: {block.text.strip()}")

            if response.stop_reason == "refusal":
                return "The model declined this request."
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason == "max_tokens":
                messages.append({"role": "user", "content": "Continue."})
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return next((b.text for b in response.content if b.type == "text"), "")

            results = []
            for tu in tool_uses:
                printer(f"  -> {tu.name}({json.dumps(tu.input)[:200]})")
                try:
                    r = await mcp.call_tool(tu.name, tu.input)
                    text, is_error = _result_text(r), bool(r.is_error)
                except Exception as exc:  # surface tool crashes to the model as errors
                    text, is_error = f"Tool error: {exc}", True
                printer(f"  <- {text[:300]}")
                results.append(
                    {"type": "tool_result", "tool_use_id": tu.id, "content": text, "is_error": is_error}
                )
            messages.append({"role": "user", "content": results})

    print("Agent hit the turn limit.", file=sys.stderr)
    return "Stopped: turn limit reached."
