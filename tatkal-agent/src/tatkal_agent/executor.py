"""Deterministic booking executor: the hot path.

Why not let the LLM drive the hot path? Tatkal confirmed berths on popular
trains can be gone in a minute. An LLM round-trip takes seconds. So the agent
does the *thinking* before the window opens (rank options, set bounds, get
human approval), and this executor does the *doing* at 10:00:00 in
milliseconds: fire on the server's clock, retry transient errors with jitter,
fall through to the next approved option on sell-out, and reconcile ambiguous
payments instead of double-booking. Anything outside the approved bounds is
handed back to the agent and the human.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from .clock import IST, estimate_offset, sleep_until
from .errors import (
    AmbiguousOutcomeError,
    FareExceededError,
    FatalError,
    PaymentDeclinedError,
    SessionExpiredError,
    SoldOutError,
    TransientError,
)
from .models import AttemptLog, BookingPlan, BookingResult, ExecutionReport
from .providers.base import BookingProvider
from .retry import RetryPolicy, retry_async

log = logging.getLogger(__name__)

OtpRequester = Callable[[str], Awaitable[str | None]]


@dataclass
class ExecutorConfig:
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    max_payment_attempts: int = 3
    reconcile_attempts: int = 5
    reconcile_delay: float = 1.0
    keepalive_every_seconds: float = 60.0


class BookingExecutor:
    def __init__(
        self,
        provider: BookingProvider,
        config: ExecutorConfig | None = None,
        request_otp: OtpRequester | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.provider = provider
        self.cfg = config or ExecutorConfig()
        self.request_otp = request_otp
        self.on_event = on_event or (lambda msg: log.info(msg))
        self.clock_offset = 0.0
        self.one_way_latency = 0.0

    # ----------------------------------------------------------- preparation
    async def sync_clock(self) -> tuple[float, float]:
        offset, rtt = await estimate_offset(self.provider.server_time)
        self.clock_offset, self.one_way_latency = offset, rtt / 2
        self.on_event(f"clock offset {offset * 1000:+.0f} ms, rtt {rtt * 1000:.0f} ms")
        return offset, rtt

    async def ensure_session(self) -> None:
        if self.provider.session_valid():
            return
        challenge = await self.provider.begin_login()
        otp = None
        if challenge.otp_required:
            if self.request_otp is None:
                raise SessionExpiredError("Login needs an OTP but no human channel is available")
            otp = await self.request_otp(challenge.message)
            if not otp:
                raise FatalError("Human did not provide an OTP")
        await self.provider.complete_login(otp)
        self.on_event("logged in")

    async def wait_for_window(self, opens_at: datetime) -> None:
        """Sleep until the window opens, keeping the session alive."""
        while True:
            remaining = opens_at.timestamp() - self.clock_offset - time.time()
            if remaining <= self.cfg.keepalive_every_seconds:
                break
            await asyncio.sleep(self.cfg.keepalive_every_seconds)
            try:
                await self.provider.keepalive()
            except SessionExpiredError:
                await self.ensure_session()
        await self.sync_clock()  # re-sync right before firing
        self.on_event(f"firing at {opens_at.isoformat()} (server clock)")
        await sleep_until(opens_at, self.clock_offset, self.one_way_latency)

    # -------------------------------------------------------------- hot path
    async def run(self, plan: BookingPlan) -> ExecutionReport:
        if not plan.approved:
            raise FatalError("Refusing to execute a plan that a human has not approved")

        report = ExecutionReport(plan_id=plan.plan_id)
        started = time.monotonic()

        def record(idx: int, outcome: str, detail: str = "") -> None:
            opt = plan.options[idx]
            report.attempts.append(
                AttemptLog(
                    at=datetime.now(IST), option_index=idx, train_number=opt.train_number,
                    travel_class=opt.travel_class, outcome=outcome, detail=detail,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            )
            self.on_event(f"[{idx}] {opt.train_number}/{opt.travel_class}: {outcome} {detail}".rstrip())

        for idx, option in enumerate(plan.options):
            payment_attempts = 0
            attempt_no = 0
            while True:
                key = f"{plan.plan_id}-o{idx}-a{attempt_no}"

                def on_retry(n: int, exc: BaseException, delay: float, _idx: int = idx) -> None:
                    record(_idx, "retry", f"#{n} {exc} (sleep {delay * 1000:.0f} ms)")

                try:
                    result = await retry_async(
                        lambda: self.provider.book(plan, option, key), self.cfg.retry, on_retry=on_retry
                    )
                    report.final = result
                    record(idx, "booked", f"PNR {result.pnr} {result.status}")
                    return report

                except SoldOutError as exc:
                    record(idx, "sold_out", str(exc))
                    break  # next option

                except SessionExpiredError as exc:
                    record(idx, "session_expired", str(exc))
                    try:
                        await self.ensure_session()
                    except (FatalError, SessionExpiredError) as e:
                        report.needs_human = f"Could not re-login: {e}"
                        return report
                    continue

                except PaymentDeclinedError as exc:
                    payment_attempts += 1
                    record(idx, "payment_declined", str(exc))
                    if payment_attempts >= self.cfg.max_payment_attempts:
                        report.needs_human = (
                            f"Payment declined {payment_attempts} times. Check the UPI app/bank, "
                            "or approve a different payment method."
                        )
                        return report
                    attempt_no += 1  # definitive decline: new key is safe
                    continue

                except AmbiguousOutcomeError as exc:
                    record(idx, "ambiguous", f"{exc}; reconciling")
                    found = await self._reconcile(key)
                    if found is not None:
                        report.final = found
                        record(idx, "reconciled", f"PNR {found.pnr} {found.status}")
                        return report
                    record(idx, "reconciled", "no booking found; safe to retry")
                    attempt_no += 1
                    continue

                except FareExceededError as exc:
                    record(idx, "fare_exceeded", str(exc))
                    report.needs_human = (
                        f"{option.train_number}/{option.travel_class} costs {exc.fare}, above the approved "
                        f"cap {plan.policy.max_total_fare}. Approve a higher cap or skip this option."
                    )
                    return report

                except TransientError as exc:
                    record(idx, "gave_up", f"retries exhausted: {exc}")
                    break

                except FatalError as exc:
                    record(idx, "fatal", str(exc))
                    report.needs_human = str(exc)
                    return report

        report.needs_human = "All approved options were sold out or unavailable."
        return report

    async def _reconcile(self, key: str) -> BookingResult | None:
        """Ask the backend whether the ambiguous booking went through.

        Payment confirmations can lag, so poll a few times before concluding
        'not booked'. Only after that is a new attempt safe.
        """
        for i in range(self.cfg.reconcile_attempts):
            try:
                found = await self.provider.find_booking(key)
            except TransientError:
                found = None
            if found is not None:
                return found
            if i < self.cfg.reconcile_attempts - 1:
                await asyncio.sleep(self.cfg.reconcile_delay)
        return None
