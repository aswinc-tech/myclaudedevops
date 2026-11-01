"""Skeleton for an *authorised* booking integration.

IRCTC exposes booking to approved partners (principal service providers / B2B
integrations) under a contract. That is the only kind of backend this project
should be wired to. Do NOT implement this class by scraping irctc.co.in,
automating its web UI, solving its CAPTCHA or rotating accounts. That breaks
IRCTC's terms of use, gets user IDs blocked, and is the exact behaviour behind
the bot-driven unfairness Tatkal users complain about (see docs/COMPLIANCE.md).

Credentials: read from environment variables (or a secret manager) at call
time. Never accept them as tool arguments and never return them.
"""

from __future__ import annotations

import os
from datetime import date, datetime

from ..errors import FatalError
from ..models import Availability, BookingOption, BookingPlan, BookingResult, Train
from .base import BookingProvider, LoginChallenge

_NOT_CONFIGURED = (
    "PartnerApiProvider is a skeleton. Wire it to an authorised partner API "
    "(set PARTNER_API_BASE_URL and PARTNER_API_KEY_ENV) before use."
)


class PartnerApiProvider(BookingProvider):
    name = "partner"

    def __init__(self) -> None:
        self.base_url = os.getenv("PARTNER_API_BASE_URL")
        # Name of the env var that holds the key, so the key itself never sits in config files.
        self._key_env = os.getenv("PARTNER_API_KEY_ENV", "PARTNER_API_KEY")
        if not self.base_url or not os.getenv(self._key_env):
            raise FatalError(_NOT_CONFIGURED)

    async def server_time(self) -> datetime:
        raise NotImplementedError(_NOT_CONFIGURED)

    async def begin_login(self) -> LoginChallenge:
        # e.g. POST {base_url}/session with IRCTC user id from os.environ["IRCTC_USERNAME"];
        # the partner flow triggers the Aadhaar-linked OTP to the user's phone.
        raise NotImplementedError(_NOT_CONFIGURED)

    async def complete_login(self, otp: str | None) -> None:
        raise NotImplementedError(_NOT_CONFIGURED)

    def session_valid(self) -> bool:
        return False

    async def keepalive(self) -> None:
        raise NotImplementedError(_NOT_CONFIGURED)

    async def search_trains(self, source: str, destination: str, journey_date: date) -> list[Train]:
        raise NotImplementedError(_NOT_CONFIGURED)

    async def availability(
        self, train_number: str, travel_class: str, journey_date: date, quota: str = "TQ"
    ) -> Availability:
        raise NotImplementedError(_NOT_CONFIGURED)

    async def book(self, plan: BookingPlan, option: BookingOption, idempotency_key: str) -> BookingResult:
        raise NotImplementedError(_NOT_CONFIGURED)

    async def find_booking(self, idempotency_key: str) -> BookingResult | None:
        raise NotImplementedError(_NOT_CONFIGURED)

    async def pnr_status(self, pnr: str) -> BookingResult:
        raise NotImplementedError(_NOT_CONFIGURED)
