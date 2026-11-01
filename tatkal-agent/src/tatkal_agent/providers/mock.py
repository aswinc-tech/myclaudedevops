"""A deliberately hostile simulator of Tatkal opening time.

It reproduces the failure modes users actually complain about so the agent and
executor can be exercised end-to-end without touching a real system:

* site overloaded / 503s for the first seconds after the window opens
* inventory selling out within a minute or two
* sessions expiring while you wait
* payment declined
* payment timeout where the money moved but the client never heard back
  ("amount debited, no ticket")
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..account import load_account
from ..clock import IST, tatkal_window_open
from ..errors import (
    AmbiguousOutcomeError,
    FareExceededError,
    FatalError,
    NotWindowOpenError,
    PaymentDeclinedError,
    SessionExpiredError,
    SoldOutError,
    TransientError,
)
from ..models import (
    ALL_CLASSES,
    Availability,
    BookingOption,
    BookingPlan,
    BookingResult,
    BookingStatus,
    SeatStatus,
    Train,
)
from .base import BookingProvider, LoginChallenge

BASE_FARE = {"1A": 4200, "2A": 2500, "3A": 1800, "3E": 1650, "CC": 1100, "EC": 2100, "SL": 650, "2S": 250}
TATKAL_CHARGE = {"1A": 0, "2A": 500, "3A": 400, "3E": 400, "CC": 225, "EC": 500, "SL": 200, "2S": 15}
MOCK_OTP = "123456"


@dataclass
class MockScenario:
    seed: int = 7
    window_opens_in_seconds: float | None = 3.0
    """Open the window N seconds after the provider is created (for demos).
    None -> use the real Tatkal schedule."""
    initial_seats: int = 40
    sellout_seconds: float = 90.0
    overload_seconds: float = 4.0
    overload_failure_rate: float = 0.7
    payment_decline_rate: float = 0.15
    ambiguous_rate: float = 0.15
    session_ttl_seconds: float = 900.0
    server_clock_skew_seconds: float = 0.0
    sold_out_trains: set[str] = field(default_factory=set)
    require_account: bool = True
    """Require IRCTC_USERNAME / IRCTC_PASSWORD in the environment, like a real login."""
    reject_password: bool = False
    """Simulate a wrong password."""


class MockProvider(BookingProvider):
    name = "mock"

    def __init__(self, scenario: MockScenario | None = None) -> None:
        self.s = scenario or MockScenario()
        self.rng = random.Random(self.s.seed)
        self._created = self._now()
        self._session_expires: datetime | None = None
        self._pending_login = False
        self._bookings: dict[str, BookingResult] = {}
        self._own_booked: dict[tuple[str, str, date], int] = {}

    # ------------------------------------------------------------------ util
    def _now(self) -> datetime:
        return datetime.now(IST) + timedelta(seconds=self.s.server_clock_skew_seconds)

    def window_open(self, journey_date: date, travel_class: str) -> datetime:
        if self.s.window_opens_in_seconds is not None:
            return self._created + timedelta(seconds=self.s.window_opens_in_seconds)
        return tatkal_window_open(journey_date, travel_class)

    def _seats_left(self, train: str, cls: str, jd: date) -> int:
        if train in self.s.sold_out_trains:
            return 0
        opened = self.window_open(jd, cls)
        elapsed = (self._now() - opened).total_seconds()
        if elapsed < 0:
            return self.s.initial_seats
        sold_by_others = int(self.s.initial_seats * min(1.0, elapsed / self.s.sellout_seconds))
        return max(0, self.s.initial_seats - sold_by_others - self._own_booked.get((train, cls, jd), 0))

    @staticmethod
    def _fare(cls: str) -> int:
        return BASE_FARE[cls] + TATKAL_CHARGE[cls]

    # ----------------------------------------------------------------- clock
    async def server_time(self) -> datetime:
        return self._now()

    # --------------------------------------------------------------- session
    async def begin_login(self) -> LoginChallenge:
        who = "demo user"
        if self.s.require_account:
            account = load_account()  # raises FatalError if the env vars are missing
            if self.s.reject_password:
                raise FatalError("Invalid user id or password")
            who = account.masked_username
        self._pending_login = True
        return LoginChallenge(
            otp_required=True,
            message=f"Signed in as {who}; OTP sent to the registered mobile (mock OTP is 123456)",
        )

    async def complete_login(self, otp: str | None) -> None:
        if not self._pending_login:
            raise FatalError("begin_login must be called first")
        if otp != MOCK_OTP:
            raise FatalError("Invalid OTP")
        self._pending_login = False
        self._session_expires = self._now() + timedelta(seconds=self.s.session_ttl_seconds)

    def session_valid(self) -> bool:
        return self._session_expires is not None and self._now() < self._session_expires

    async def keepalive(self) -> None:
        if not self.session_valid():
            raise SessionExpiredError("Session expired")
        self._session_expires = self._now() + timedelta(seconds=self.s.session_ttl_seconds)

    # ------------------------------------------------------------------ read
    async def search_trains(self, source: str, destination: str, journey_date: date) -> list[Train]:
        src, dst = source.upper(), destination.upper()
        digest = int(hashlib.sha256(f"{src}-{dst}".encode()).hexdigest(), 16)
        trains = []
        for i in range(4):
            num = str(12000 + (digest >> (i * 8)) % 9000 + i)
            dep_h = (6 + i * 5 + digest % 3) % 24
            trains.append(
                Train(
                    number=num,
                    name=f"{src}-{dst} {['Rajdhani', 'Superfast', 'Express', 'Mail'][i]}",
                    source=src,
                    destination=dst,
                    departure=f"{dep_h:02d}:{(i * 15) % 60:02d}",
                    arrival=f"{(dep_h + 14) % 24:02d}:{(i * 20) % 60:02d}",
                    classes=[["1A", "2A", "3A"], ["2A", "3A", "SL"], ["3A", "3E", "SL"], ["SL", "2S"]][i],
                )
            )
        return trains

    async def availability(
        self, train_number: str, travel_class: str, journey_date: date, quota: str = "TQ"
    ) -> Availability:
        cls = travel_class.upper()
        if cls not in ALL_CLASSES:
            raise FatalError(f"Unknown class {cls}")
        fare = self._fare(cls)
        if self._now() < self.window_open(journey_date, cls):
            return Availability(
                train_number=train_number, travel_class=cls, journey_date=journey_date,
                quota=quota, status=SeatStatus.NOT_OPEN, count=self.s.initial_seats, fare_per_passenger=fare,
            )
        left = self._seats_left(train_number, cls, journey_date)
        if left > 0:
            status, count = SeatStatus.AVAILABLE, left
        else:
            opened = self.window_open(journey_date, cls)
            over = (self._now() - opened).total_seconds() - self.s.sellout_seconds
            wl = int(max(1, over * 2))
            status, count = (SeatStatus.WAITLIST, wl) if wl < 60 else (SeatStatus.REGRET, 0)
        return Availability(
            train_number=train_number, travel_class=cls, journey_date=journey_date,
            quota=quota, status=status, count=count, fare_per_passenger=fare,
        )

    # ----------------------------------------------------------------- write
    async def book(self, plan: BookingPlan, option: BookingOption, idempotency_key: str) -> BookingResult:
        if idempotency_key in self._bookings:
            return self._bookings[idempotency_key]
        if not self.session_valid():
            raise SessionExpiredError("Session expired; please log in again")
        cls = option.travel_class.upper()
        jd = plan.journey_date
        opened = self.window_open(jd, cls)
        now = self._now()
        if now < opened:
            raise NotWindowOpenError("Tatkal booking not yet open")
        if (now - opened).total_seconds() < self.s.overload_seconds and self.rng.random() < self.s.overload_failure_rate:
            raise TransientError("503 Service Unavailable")

        n = len(plan.passengers)
        left = self._seats_left(option.train_number, cls, jd)
        if left < n:
            # Mirrors IRCTC's "book only if confirmed berths are allotted" option.
            if plan.policy.confirmed_berths_only or not plan.policy.accept_rac:
                raise SoldOutError(f"{option.train_number}/{cls}: only {left} confirmed berths left")
            raise SoldOutError(f"{option.train_number}/{cls}: waitlist outside policy")

        total = self._fare(cls) * n
        if total > plan.policy.max_total_fare:
            raise FareExceededError(f"Fare {total} exceeds approved cap {plan.policy.max_total_fare}", total)

        roll = self.rng.random()
        if roll < self.s.payment_decline_rate:
            raise PaymentDeclinedError("Payment declined by bank/UPI app")

        result = BookingResult(
            idempotency_key=idempotency_key,
            status=BookingStatus.CONFIRMED,
            pnr=str(self.rng.randint(10**9, 10**10 - 1)),
            train_number=option.train_number,
            travel_class=cls,
            total_fare=total,
            berths=[f"B{self.rng.randint(1, 6)}/{self.rng.randint(1, 72)}" for _ in range(n)],
            message="Booked",
        )
        self._bookings[idempotency_key] = result
        key = (option.train_number, cls, jd)
        self._own_booked[key] = self._own_booked.get(key, 0) + n

        if roll < self.s.payment_decline_rate + self.s.ambiguous_rate:
            # The booking actually went through but the response was lost.
            raise AmbiguousOutcomeError("Gateway timeout after payment submission")
        return result

    async def find_booking(self, idempotency_key: str) -> BookingResult | None:
        return self._bookings.get(idempotency_key)

    async def pnr_status(self, pnr: str) -> BookingResult:
        for b in self._bookings.values():
            if b.pnr == pnr:
                return b
        raise FatalError(f"PNR {pnr} not found")
