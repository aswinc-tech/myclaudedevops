"""Provider interface: the only layer that talks to a ticketing backend.

Swap implementations without touching the agent, MCP tools or executor:

* ``MockProvider``      - realistic simulator (overload, sell-out, payment
                          failures, ambiguous timeouts) for dev, tests and drills.
* ``PartnerApiProvider`` - skeleton for an *authorised* IRCTC partner / B2B
                          integration. This project intentionally ships no
                          screen-scraper and no CAPTCHA solver; see docs/COMPLIANCE.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from pydantic import BaseModel

from ..models import Availability, BookingOption, BookingPlan, BookingResult, Train


class LoginChallenge(BaseModel):
    otp_required: bool
    message: str


class BookingProvider(ABC):
    name: str = "base"

    # --- clock -----------------------------------------------------------
    @abstractmethod
    async def server_time(self) -> datetime: ...

    # --- session ---------------------------------------------------------
    @abstractmethod
    async def begin_login(self) -> LoginChallenge:
        """Start login with credentials resolved *inside* the provider
        (env vars / secret manager). Returns whether an OTP is needed."""

    @abstractmethod
    async def complete_login(self, otp: str | None) -> None: ...

    @abstractmethod
    def session_valid(self) -> bool: ...

    @abstractmethod
    async def keepalive(self) -> None:
        """Refresh the session so it does not expire while waiting for the window."""

    # --- read ------------------------------------------------------------
    @abstractmethod
    async def search_trains(self, source: str, destination: str, journey_date: date) -> list[Train]: ...

    @abstractmethod
    async def availability(
        self, train_number: str, travel_class: str, journey_date: date, quota: str = "TQ"
    ) -> Availability: ...

    # --- write -----------------------------------------------------------
    @abstractmethod
    async def book(self, plan: BookingPlan, option: BookingOption, idempotency_key: str) -> BookingResult:
        """Create booking + pay. Must be idempotent on `idempotency_key`.

        Raises the typed errors in ``tatkal_agent.errors``.
        """

    @abstractmethod
    async def find_booking(self, idempotency_key: str) -> BookingResult | None:
        """Reconciliation: did a booking with this key actually go through?"""

    @abstractmethod
    async def pnr_status(self, pnr: str) -> BookingResult: ...
