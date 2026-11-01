"""MCP server exposing the Tatkal booking tools.

Usable by the bundled agent (tatkal_agent.agent) or by any MCP host such as
Claude Code or Claude Desktop.

Human-in-the-loop is enforced *here*, in code, not by asking the model nicely:

* propose_booking_plan  -> MCP elicitation: the human sees the full plan
                           (passengers, trains, fare cap) and approves/declines.
* login / re-login      -> MCP elicitation for the OTP. The OTP goes from the
                           human straight to this server; it never enters the
                           LLM context.
* execute_booking_plan  -> refuses unless the plan was approved by a human.
* ask_human             -> the agent can escalate any decision.

If the MCP client does not support elicitation, every gate fails closed.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mcp.server.mcpserver import Context, MCPServer

from .clock import IST
from .errors import BookingError
from .executor import BookingExecutor, ExecutorConfig
from .models import ALL_CLASSES, BookingOption, BookingPlan, BookingPolicy
from .profile import TravellerProfile, load_profile
from .providers import BookingProvider, make_provider
from .providers.mock import MockProvider

log = logging.getLogger(__name__)

INSTRUCTIONS = """Tools for planning and executing an IRCTC Tatkal booking through an authorised
backend. Typical flow: get_tatkal_window -> search_trains -> check_availability ->
propose_booking_plan (human approves) -> login (human enters OTP) -> execute_booking_plan.
Passenger details and credentials are held server-side; never ask the user for passwords."""


# ---------------------------------------------------------------- elicitation
class PlanApproval(BaseModel):
    approve: bool = Field(description="Approve this plan and authorise payment up to the fare cap?")
    comment: str = Field(default="", description="Optional instructions for the agent")


class OtpEntry(BaseModel):
    otp: str = Field(description="One-time password sent to your registered mobile")


class HumanAnswer(BaseModel):
    answer: str = Field(description="Your answer")


class AuditLog:
    """Append-only JSONL trail of every decision. Never contains secrets."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **data: Any) -> None:
        line = {"at": datetime.now(IST).isoformat(), "event": event, **data}
        print(f"[audit] {event} {json.dumps(data, default=str)[:300]}", file=sys.stderr)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(line, default=str) + "\n")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def build_server(
    provider: BookingProvider | None = None,
    profile: TravellerProfile | None = None,
    executor_config: ExecutorConfig | None = None,
    audit_path: Path | None = Path("runs/audit.jsonl"),
) -> MCPServer:
    provider = provider or make_provider()
    profile = profile or load_profile()
    audit = AuditLog(audit_path)
    plans: dict[str, BookingPlan] = {}

    server = MCPServer("tatkal-booking", instructions=INSTRUCTIONS)

    def window_for(journey_date: date, travel_class: str) -> datetime:
        if isinstance(provider, MockProvider):
            return provider.window_open(journey_date, travel_class)
        from .clock import tatkal_window_open

        return tatkal_window_open(journey_date, travel_class)

    async def elicit_otp(ctx: Context, message: str) -> str | None:
        hint = f" ({profile.mobile_hint})" if profile.mobile_hint else ""
        res = await ctx.elicit(f"{message}{hint}. Enter the OTP:", OtpEntry)
        audit.write("otp_prompt", action=res.action)  # never log the OTP itself
        return res.data.otp.strip() if res.action == "accept" else None

    # ------------------------------------------------------------------ tools
    @server.tool()
    async def get_tatkal_window(journey_date: str, travel_class: str) -> dict:
        """When the Tatkal window opens for a journey date and class (AC opens 10:00 IST,
        non-AC 11:00 IST, one day before the journey), plus seconds remaining by the
        booking server's clock. journey_date is YYYY-MM-DD."""
        jd = _parse_date(journey_date)
        opens = window_for(jd, travel_class.upper())
        now = await provider.server_time()
        return {
            "opens_at": opens.isoformat(),
            "server_now": now.isoformat(),
            "seconds_until_open": round((opens - now).total_seconds(), 1),
            "is_open": now >= opens,
        }

    @server.tool()
    async def search_trains(source: str, destination: str, journey_date: str) -> dict:
        """Trains between two station codes (e.g. NDLS, MMCT) on a date (YYYY-MM-DD)."""
        trains = await provider.search_trains(source, destination, _parse_date(journey_date))
        return {"trains": [t.model_dump() for t in trains]}

    @server.tool()
    async def check_availability(train_number: str, travel_class: str, journey_date: str) -> dict:
        """Tatkal-quota availability and per-passenger fare (INR) for one train/class.
        Status is AVAILABLE, RAC, WAITLIST, REGRET or NOT_OPEN (window not open yet)."""
        av = await provider.availability(train_number, travel_class.upper(), _parse_date(journey_date))
        return av.model_dump(mode="json") | {"passengers": len(profile.passengers)}

    @server.tool()
    async def propose_booking_plan(
        journey_date: str,
        source: str,
        destination: str,
        options: list[BookingOption],
        max_total_fare: int,
        rationale: str,
        confirmed_berths_only: bool = True,
        accept_rac: bool = False,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict:
        """Propose a ranked list (best first, max 6) of train/class options plus a total fare cap
        for all passengers. A human reviews the plan and approves or declines it. Nothing can
        be booked until a plan is approved. Returns plan_id, approved flag and any human comment."""
        for o in options:
            if o.travel_class.upper() not in ALL_CLASSES:
                return {"error": f"Unknown class {o.travel_class}"}
            o.travel_class = o.travel_class.upper()
        plan = BookingPlan(
            journey_date=_parse_date(journey_date),
            source=source.upper(),
            destination=destination.upper(),
            passengers=profile.passengers,
            options=options,
            policy=BookingPolicy(
                max_total_fare=max_total_fare,
                confirmed_berths_only=confirmed_berths_only,
                accept_rac=accept_rac,
                payment_method=profile.payment_method,
            ),
            rationale=rationale,
        )
        pax = ", ".join(f"{p.name} ({p.age}{p.gender.value})" for p in plan.passengers)
        ranked = "\n".join(
            f"  {i + 1}. {o.train_number} / {o.travel_class}" for i, o in enumerate(plan.options)
        )
        message = (
            f"Tatkal booking plan {plan.plan_id}\n"
            f"Journey: {plan.source} -> {plan.destination} on {plan.journey_date}\n"
            f"Passengers: {pax}\n"
            f"Options, tried in order:\n{ranked}\n"
            f"Fare cap (all passengers): INR {max_total_fare}, paid via {plan.policy.payment_method}\n"
            f"Confirmed berths only: {confirmed_berths_only}; accept RAC: {accept_rac}\n"
            f"Agent's rationale: {rationale}"
        )
        res = await ctx.elicit(message, PlanApproval)
        if res.action == "accept" and res.data.approve:
            plan.approved = True
            plan.approved_at = datetime.now(IST)
            plan.approver_comment = res.data.comment
        elif res.action == "accept":
            plan.approver_comment = res.data.comment
        plans[plan.plan_id] = plan
        audit.write("plan_reviewed", plan_id=plan.plan_id, approved=plan.approved,
                    options=[o.model_dump() for o in options], cap=max_total_fare, action=res.action)
        return {
            "plan_id": plan.plan_id,
            "approved": plan.approved,
            "human_comment": plan.approver_comment,
            "human_action": res.action,
        }

    @server.tool()
    async def login(ctx: Context = None) -> dict:  # type: ignore[assignment]
        """Log in to the booking backend with the user's stored credentials. The human is asked
        for the OTP directly; you never see it. Do this a few minutes before the window opens."""
        if provider.session_valid():
            return {"logged_in": True, "note": "session already active"}
        try:
            challenge = await provider.begin_login()
            otp = await elicit_otp(ctx, challenge.message) if challenge.otp_required else None
            if challenge.otp_required and not otp:
                return {"logged_in": False, "error": "Human did not provide an OTP"}
            await provider.complete_login(otp)
        except BookingError as exc:
            audit.write("login_failed", error=str(exc))
            return {"logged_in": False, "error": str(exc)}
        audit.write("login_ok")
        return {"logged_in": True}

    @server.tool()
    async def execute_booking_plan(plan_id: str, max_wait_seconds: int = 1800, ctx: Context = None) -> dict:  # type: ignore[assignment]
        """Run an APPROVED plan: sync to the server clock, wait for the window, fire on time and
        retry automatically (overload, session expiry, declined payment, lost responses),
        falling through options in order. Returns the booking result, every attempt, and
        `needs_human` when a decision outside the approved bounds is required."""
        plan = plans.get(plan_id)
        if plan is None:
            return {"error": f"Unknown plan_id {plan_id}"}
        if not plan.approved:
            return {"error": "Plan is not approved by a human. Propose a plan and get approval first."}

        executor = BookingExecutor(
            provider,
            executor_config,
            request_otp=lambda msg: elicit_otp(ctx, msg),
            on_event=lambda m: print(f"[executor] {m}", file=sys.stderr),
        )
        try:
            await executor.ensure_session()
            await executor.sync_clock()
            opens = min(window_for(plan.journey_date, o.travel_class) for o in plan.options)
            wait = (opens - await provider.server_time()).total_seconds()
            if wait > max_wait_seconds:
                return {"error": "too_early", "seconds_until_open": round(wait),
                        "hint": "Call again closer to the window."}
            if wait > 0:
                await executor.wait_for_window(opens)
            report = await executor.run(plan)
        except BookingError as exc:
            audit.write("execute_failed", plan_id=plan_id, error=str(exc))
            return {"error": str(exc), "needs_human": str(exc)}

        audit.write("executed", plan_id=plan_id, confirmed=report.confirmed,
                    final=report.final.model_dump() if report.final else None,
                    needs_human=report.needs_human, attempts=len(report.attempts))
        out = report.model_dump(mode="json")
        out["confirmed"] = report.confirmed
        return out

    @server.tool()
    async def get_booking_status(pnr: str) -> dict:
        """Current status of a booked PNR."""
        try:
            return (await provider.pnr_status(pnr)).model_dump(mode="json")
        except BookingError as exc:
            return {"error": str(exc)}

    @server.tool()
    async def ask_human(question: str, ctx: Context = None) -> dict:  # type: ignore[assignment]
        """Ask the traveller a question when a decision is theirs to make (e.g. raise the fare
        cap, accept RAC/waitlist, try a different date). Returns their answer."""
        res = await ctx.elicit(question, HumanAnswer)
        audit.write("asked_human", question=question, action=res.action)
        if res.action != "accept":
            return {"answered": False, "action": res.action}
        return {"answered": True, "answer": res.data.answer}

    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    build_server().run("stdio")


if __name__ == "__main__":
    main()
