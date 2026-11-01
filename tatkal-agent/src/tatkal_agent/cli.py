"""Command line entry points.

  tatkal-agent run "Book 3A NDLS to MMCT on 2026-11-20, prefer Rajdhani"   # agent + human-in-the-loop
  tatkal-agent drill                                                       # executor vs. hostile mock, no LLM
  tatkal-agent serve                                                       # MCP server on stdio for any MCP host
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from datetime import date, timedelta
from typing import Any

import mcp.types as types


async def terminal_elicitation(context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
    """Human-in-the-loop UI: render an MCP elicitation request in the terminal."""
    schema = getattr(params, "requested_schema", None) or {}
    props: dict[str, Any] = schema.get("properties", {})
    print("\n" + "=" * 70 + "\nHUMAN INPUT NEEDED\n" + "=" * 70)
    print(params.message)
    print("-" * 70)
    content: dict[str, Any] = {}
    for name, spec in props.items():
        desc = spec.get("description", name)
        if spec.get("type") == "boolean":
            ans = (await asyncio.to_thread(input, f"{desc} [y/N]: ")).strip().lower()
            content[name] = ans in {"y", "yes"}
        elif name == "otp":
            content[name] = await asyncio.to_thread(getpass.getpass, f"{desc} (hidden): ")
        else:
            content[name] = await asyncio.to_thread(input, f"{desc}: ")
    print("=" * 70 + "\n")
    return types.ElicitResult(action="accept", content=content)


def _cmd_run(args: argparse.Namespace) -> None:
    from .agent import run_agent
    from .mcp_server import build_server

    final = asyncio.run(run_agent(args.request, build_server(), terminal_elicitation))
    print("\n" + final)


def _cmd_serve(_: argparse.Namespace) -> None:
    from .mcp_server import main

    main()


def _cmd_drill(args: argparse.Namespace) -> None:
    """Run the deterministic executor against the hostile simulator. No LLM, no network."""
    from .executor import BookingExecutor, ExecutorConfig
    from .models import BookingOption, BookingPlan, BookingPolicy
    from .profile import load_profile
    from .providers.mock import MOCK_OTP, MockProvider, MockScenario
    from .retry import RetryPolicy

    async def go() -> None:
        provider = MockProvider(MockScenario(seed=args.seed, window_opens_in_seconds=3, require_account=False,
                                             sold_out_trains={"SOLD1"}))
        jd = date.today() + timedelta(days=1)
        trains = await provider.search_trains("NDLS", "MMCT", jd)
        plan = BookingPlan(
            journey_date=jd, source="NDLS", destination="MMCT",
            passengers=load_profile().passengers,
            options=[BookingOption(train_number="SOLD1", travel_class="3A"),
                     BookingOption(train_number=trains[0].number, travel_class="3A"),
                     BookingOption(train_number=trains[1].number, travel_class="SL")],
            policy=BookingPolicy(max_total_fare=6000),
            approved=True,  # drill only: auto-approved
        )

        async def otp(_: str) -> str:
            return MOCK_OTP

        ex = BookingExecutor(provider, ExecutorConfig(retry=RetryPolicy(deadline_seconds=30), reconcile_delay=0.1),
                             request_otp=otp, on_event=lambda m: print(f"[executor] {m}"))
        await ex.ensure_session()
        await ex.sync_clock()
        await ex.wait_for_window(provider.window_open(jd, "3A"))
        report = await ex.run(plan)
        print("\nRESULT:", report.final.model_dump_json(indent=2) if report.final else report.needs_human)

    asyncio.run(go())


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    p = argparse.ArgumentParser(prog="tatkal-agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Plan and book with the AI agent (human approves)")
    r.add_argument("request")
    r.set_defaults(fn=_cmd_run)
    s = sub.add_parser("serve", help="Run the MCP server on stdio")
    s.set_defaults(fn=_cmd_serve)
    d = sub.add_parser("drill", help="Executor fire-drill against the simulator (no LLM)")
    d.add_argument("--seed", type=int, default=7)
    d.set_defaults(fn=_cmd_drill)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
