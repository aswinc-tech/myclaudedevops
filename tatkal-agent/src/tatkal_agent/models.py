"""Domain models shared by the executor, providers, MCP server and agent.

Nothing in here ever holds a password, OTP or payment secret. Credentials are
resolved inside a provider from environment variables / a secret manager and are
never serialised into tool results, logs or the LLM context.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

AC_CLASSES = {"1A", "2A", "3A", "3E", "CC", "EC"}
NON_AC_CLASSES = {"SL", "2S"}
ALL_CLASSES = AC_CLASSES | NON_AC_CLASSES


class Gender(StrEnum):
    MALE = "M"
    FEMALE = "F"
    TRANSGENDER = "T"


class Passenger(BaseModel):
    name: str = Field(min_length=1, max_length=16)  # IRCTC limits passenger name length
    age: int = Field(ge=1, le=125)
    gender: Gender
    berth_preference: str | None = Field(default=None, description="LB/MB/UB/SL/SU or None")


class Train(BaseModel):
    number: str
    name: str
    source: str
    destination: str
    departure: str
    arrival: str
    classes: list[str]


class SeatStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    RAC = "RAC"
    WAITLIST = "WAITLIST"
    REGRET = "REGRET"  # sold out, no waitlist either
    NOT_OPEN = "NOT_OPEN"  # Tatkal window not open yet


class Availability(BaseModel):
    train_number: str
    travel_class: str
    journey_date: date
    quota: str = "TQ"
    status: SeatStatus
    count: int = Field(description="Seats available, or RAC/WL position")
    fare_per_passenger: int = Field(description="INR, including Tatkal charge")


class BookingOption(BaseModel):
    """One ranked alternative the agent proposes and the human approves."""

    train_number: str
    travel_class: str
    boarding_station: str | None = None


class BookingPolicy(BaseModel):
    """Bounds the human approves. The executor never acts outside them."""

    max_total_fare: int = Field(gt=0, description="Hard cap in INR for all passengers")
    confirmed_berths_only: bool = Field(
        default=True,
        description="Maps to IRCTC's 'book only if confirmed berths are allotted' option",
    )
    accept_rac: bool = False
    max_waitlist: int = Field(default=0, ge=0, description="Only used when confirmed_berths_only is false")
    payment_method: str = Field(default="UPI", description="Pre-selected so no time is lost at checkout")


class BookingPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:10]}")
    journey_date: date
    source: str
    destination: str
    passengers: list[Passenger]
    options: list[BookingOption] = Field(min_length=1, max_length=6)
    policy: BookingPolicy
    rationale: str = ""
    approved: bool = False
    approved_at: datetime | None = None
    approver_comment: str = ""


class BookingStatus(StrEnum):
    CONFIRMED = "CNF"
    RAC = "RAC"
    WAITLIST = "WL"
    FAILED = "FAILED"
    PENDING = "PENDING"  # money may be debited, outcome unknown -> must reconcile


class BookingResult(BaseModel):
    idempotency_key: str
    status: BookingStatus
    pnr: str | None = None
    train_number: str | None = None
    travel_class: str | None = None
    total_fare: int | None = None
    berths: list[str] = Field(default_factory=list)
    message: str = ""


class AttemptLog(BaseModel):
    at: datetime
    option_index: int
    train_number: str
    travel_class: str
    outcome: str
    detail: str = ""
    elapsed_ms: int = 0


class ExecutionReport(BaseModel):
    plan_id: str
    final: BookingResult | None = None
    attempts: list[AttemptLog] = Field(default_factory=list)
    needs_human: str | None = Field(
        default=None, description="Set when the executor stopped because a human decision is required"
    )

    @property
    def confirmed(self) -> bool:
        return self.final is not None and self.final.status == BookingStatus.CONFIRMED
