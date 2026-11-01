"""End-to-end through the real MCP protocol (in-process), including elicitation."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import mcp.types as types
from mcp.client.client import Client

from tatkal_agent.executor import ExecutorConfig
from tatkal_agent.mcp_server import build_server
from tatkal_agent.providers.mock import MOCK_OTP, MockProvider, MockScenario
from tatkal_agent.retry import RetryPolicy

JD = (date.today() + timedelta(days=1)).isoformat()


class ScriptedHuman:
    """Stands in for the terminal UI: answers elicitations from a script and records them."""

    def __init__(self, approve: bool = True, otp: str = MOCK_OTP) -> None:
        self.approve, self.otp = approve, otp
        self.seen: list[str] = []

    async def __call__(self, context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
        self.seen.append(params.message)
        props = params.requested_schema.get("properties", {})
        if "otp" in props:
            return types.ElicitResult(action="accept", content={"otp": self.otp})
        if "approve" in props:
            return types.ElicitResult(action="accept", content={"approve": self.approve, "comment": ""})
        return types.ElicitResult(action="accept", content={"answer": "yes"})


def server(**scenario: Any):
    base = dict(window_opens_in_seconds=0.5, overload_seconds=0, payment_decline_rate=0, ambiguous_rate=0)
    provider = MockProvider(MockScenario(**(base | scenario)))
    cfg = ExecutorConfig(retry=RetryPolicy(base_delay=0.001, max_delay=0.01, deadline_seconds=5), reconcile_delay=0)
    return build_server(provider, executor_config=cfg, audit_path=None)


def data(result: types.CallToolResult) -> dict:
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


PLAN_ARGS = {
    "journey_date": JD, "source": "NDLS", "destination": "MMCT",
    "options": [{"train_number": "12951", "travel_class": "3A"}, {"train_number": "12953", "travel_class": "SL"}],
    "max_total_fare": 6000, "rationale": "test",
}


async def test_tools_listed():
    async with Client(server(), mode="legacy", elicitation_callback=ScriptedHuman()) as c:
        names = {t.name for t in (await c.list_tools()).tools}
    assert {"get_tatkal_window", "search_trains", "check_availability", "propose_booking_plan",
            "login", "execute_booking_plan", "get_booking_status", "ask_human"} <= names


async def test_full_flow_with_human_approval_and_otp():
    human = ScriptedHuman(approve=True)
    async with Client(server(), mode="legacy", elicitation_callback=human) as c:
        plan = data(await c.call_tool("propose_booking_plan", PLAN_ARGS))
        assert plan["approved"] is True
        assert "Asha Kumar" in human.seen[0], "human must see passenger details in the approval prompt"

        login = await c.call_tool("login", {})
        assert data(login)["logged_in"] is True
        assert MOCK_OTP not in json.dumps(data(login)), "OTP must never be echoed to the agent"

        out = data(await c.call_tool("execute_booking_plan", {"plan_id": plan["plan_id"]}))
        assert out["confirmed"] is True and out["final"]["pnr"]


async def test_declined_plan_cannot_execute():
    async with Client(server(), mode="legacy", elicitation_callback=ScriptedHuman(approve=False)) as c:
        plan = data(await c.call_tool("propose_booking_plan", PLAN_ARGS))
        assert plan["approved"] is False
        out = data(await c.call_tool("execute_booking_plan", {"plan_id": plan["plan_id"]}))
        assert "not approved" in out["error"]


async def test_wrong_otp_fails_closed():
    async with Client(server(), mode="legacy", elicitation_callback=ScriptedHuman(otp="000000")) as c:
        assert data(await c.call_tool("login", {}))["logged_in"] is False


async def test_passenger_pii_not_exposed_to_agent_reads():
    async with Client(server(), mode="legacy", elicitation_callback=ScriptedHuman()) as c:
        av = data(await c.call_tool("check_availability",
                                    {"train_number": "12951", "travel_class": "3A", "journey_date": JD}))
        assert av["passengers"] == 2 and "Asha" not in json.dumps(av)


async def test_login_uses_env_account_and_never_leaks_password(capsys):
    async with Client(server(), mode="legacy", elicitation_callback=(human := ScriptedHuman())) as c:
        out = json.dumps(data(await c.call_tool("login", {})))
    assert '"logged_in": true' in out
    assert "placeholder-not-a-real-password" not in out + capsys.readouterr().err + " ".join(human.seen)
    assert "demo_user01" not in " ".join(human.seen), "username is masked in prompts"


async def test_missing_account_fails_closed(monkeypatch):
    monkeypatch.delenv("IRCTC_PASSWORD")
    async with Client(server(), mode="legacy", elicitation_callback=ScriptedHuman()) as c:
        out = data(await c.call_tool("login", {}))
    assert out["logged_in"] is False and "IRCTC_PASSWORD" in out["error"]


async def test_wrong_password_fails_without_otp_prompt():
    human = ScriptedHuman()
    async with Client(server(reject_password=True), mode="legacy", elicitation_callback=human) as c:
        out = data(await c.call_tool("login", {}))
    assert out["logged_in"] is False and human.seen == []
