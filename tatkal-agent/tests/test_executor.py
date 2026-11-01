from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from tatkal_agent.clock import tatkal_window_open
from tatkal_agent.errors import FatalError, TransientError
from tatkal_agent.executor import BookingExecutor, ExecutorConfig
from tatkal_agent.models import BookingOption, BookingPlan, BookingPolicy, BookingStatus, Gender, Passenger
from tatkal_agent.providers.mock import MOCK_OTP, MockProvider, MockScenario
from tatkal_agent.retry import RetryPolicy, retry_async

JD = date.today() + timedelta(days=1)
PAX = [Passenger(name="A", age=30, gender=Gender.FEMALE), Passenger(name="B", age=32, gender=Gender.MALE)]


def plan(*opts: tuple[str, str], cap: int = 10_000, approved: bool = True) -> BookingPlan:
    return BookingPlan(
        journey_date=JD, source="NDLS", destination="MMCT", passengers=PAX,
        options=[BookingOption(train_number=t, travel_class=c) for t, c in opts],
        policy=BookingPolicy(max_total_fare=cap), approved=approved,
    )


def calm(**kw) -> MockScenario:
    """Window already open, no overload, no payment trouble unless overridden."""
    base = dict(window_opens_in_seconds=-1, overload_seconds=0, payment_decline_rate=0, ambiguous_rate=0)
    return MockScenario(**(base | kw))


async def otp(_: str) -> str:
    return MOCK_OTP


def executor(provider: MockProvider) -> BookingExecutor:
    cfg = ExecutorConfig(retry=RetryPolicy(base_delay=0.001, max_delay=0.005, deadline_seconds=5,
                                           rng=random.Random(1)), reconcile_delay=0)
    return BookingExecutor(provider, cfg, request_otp=otp, on_event=lambda m: None)


async def test_unapproved_plan_is_refused():
    p = MockProvider(calm())
    with pytest.raises(FatalError):
        await executor(p).run(plan(("12951", "3A"), approved=False))


async def test_happy_path_confirms():
    p = MockProvider(calm())
    ex = executor(p)
    await ex.ensure_session()
    report = await ex.run(plan(("12951", "3A")))
    assert report.confirmed and report.final.pnr


async def test_sold_out_falls_through_to_next_option():
    p = MockProvider(calm(sold_out_trains={"11111"}))
    ex = executor(p)
    await ex.ensure_session()
    report = await ex.run(plan(("11111", "3A"), ("22222", "SL")))
    assert report.confirmed
    assert report.final.train_number == "22222"
    assert [a.outcome for a in report.attempts][0] == "sold_out"


async def test_overload_is_retried():
    p = MockProvider(calm(overload_seconds=60, overload_failure_rate=0.8, seed=3))
    ex = executor(p)
    await ex.ensure_session()
    report = await ex.run(plan(("12951", "3A")))
    assert report.confirmed
    assert any(a.outcome == "retry" for a in report.attempts)


async def test_ambiguous_payment_is_reconciled_not_double_booked():
    p = MockProvider(calm(ambiguous_rate=1.0))  # every booking "times out" after the money moves
    ex = executor(p)
    await ex.ensure_session()
    report = await ex.run(plan(("12951", "3A")))
    assert report.confirmed
    assert len(p._bookings) == 1, "must not create a second booking after a lost response"
    assert [a.outcome for a in report.attempts][-1] == "reconciled"


async def test_fare_above_cap_escalates_to_human():
    p = MockProvider(calm())
    ex = executor(p)
    await ex.ensure_session()
    report = await ex.run(plan(("12951", "1A"), cap=1000))
    assert not report.confirmed
    assert "cap" in report.needs_human
    assert p._bookings == {}


async def test_repeated_payment_decline_escalates():
    p = MockProvider(calm(payment_decline_rate=1.0))
    ex = executor(p)
    await ex.ensure_session()
    report = await ex.run(plan(("12951", "3A")))
    assert not report.confirmed and "Payment declined" in report.needs_human


async def test_session_expiry_triggers_relogin_with_human_otp():
    p = MockProvider(calm())
    ex = executor(p)
    await ex.ensure_session()
    p._session_expires = None  # simulate expiry right before firing
    report = await ex.run(plan(("12951", "3A")))
    assert report.confirmed
    assert any(a.outcome == "session_expired" for a in report.attempts)


async def test_all_options_exhausted_needs_human():
    p = MockProvider(calm(sold_out_trains={"1", "2"}))
    ex = executor(p)
    await ex.ensure_session()
    report = await ex.run(plan(("1", "3A"), ("2", "SL")))
    assert not report.confirmed and report.needs_human


async def test_retry_respects_max_attempts():
    calls = 0

    async def boom():
        nonlocal calls
        calls += 1
        raise TransientError("503")

    async def nosleep(_: float) -> None:
        return None

    with pytest.raises(TransientError):
        await retry_async(boom, RetryPolicy(max_attempts=4), sleep=nosleep)
    assert calls == 4


def test_window_times():
    jd = date(2026, 11, 20)
    assert tatkal_window_open(jd, "3A").isoformat() == "2026-11-19T10:00:00+05:30"
    assert tatkal_window_open(jd, "SL").isoformat() == "2026-11-19T11:00:00+05:30"
