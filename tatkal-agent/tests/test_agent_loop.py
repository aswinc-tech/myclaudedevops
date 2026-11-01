"""Exercise the agent loop wiring with a scripted stand-in for the Claude API.

This checks plumbing (tool_use -> MCP call -> tool_result -> next turn, human
gates reached through elicitation), not model judgement; that needs a live key.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace as NS

import tatkal_agent.agent as agent_mod
from tests.test_mcp_server import PLAN_ARGS, ScriptedHuman, server


def tool(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def text(t):
    return NS(type="text", text=t)


class FakeClaude:
    def __init__(self):
        self.calls = []
        self.beta = NS(messages=NS(create=self.create))

    async def create(self, **kw):
        self.calls.append(kw)
        turn = len(self.calls)
        if turn == 1:
            return NS(stop_reason="tool_use", content=[tool("t1", "propose_booking_plan", PLAN_ARGS)])
        if turn == 2:
            plan = json.loads(kw["messages"][-1]["content"][0]["content"])
            self.plan_id = plan["plan_id"]
            return NS(stop_reason="tool_use", content=[tool("t2", "login", {})])
        if turn == 3:
            return NS(stop_reason="tool_use",
                      content=[tool("t3", "execute_booking_plan", {"plan_id": self.plan_id})])
        result = json.loads(kw["messages"][-1]["content"][0]["content"])
        return NS(stop_reason="end_turn", content=[text(f"Confirmed: PNR {result['final']['pnr']}")])


async def test_agent_loop_books_through_mcp(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(agent_mod.anthropic, "AsyncAnthropic", lambda: fake)
    human = ScriptedHuman()
    out = await agent_mod.run_agent("book it", server(), human, printer=lambda s: None)

    assert out.startswith("Confirmed: PNR ")
    assert len(human.seen) == 2  # plan approval + OTP
    first = fake.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert {t["name"] for t in first["tools"]} >= {"propose_booking_plan", "execute_booking_plan"}
    # append-only history: user + 3x(assistant tool_use, user tool_result) + final assistant
    assert len(fake.calls[-1]["messages"]) == 1 + 2 * 3 + 1
