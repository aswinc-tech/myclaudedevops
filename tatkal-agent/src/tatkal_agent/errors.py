"""Error taxonomy. The executor's retry decisions are driven entirely by type.

Getting this classification right is most of the reliability story: retrying a
non-retryable error wastes the few seconds Tatkal gives you, and blindly retrying
an *ambiguous* payment error is how people end up double-charged.
"""

from __future__ import annotations


class BookingError(Exception):
    """Base class."""


class TransientError(BookingError):
    """503 / gateway timeout / connection reset. Retry quickly with jitter."""


class RateLimitedError(TransientError):
    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SessionExpiredError(BookingError):
    """Login session is gone. Needs re-login (and a fresh OTP from the human)."""


class SoldOutError(BookingError):
    """This option cannot satisfy the policy any more. Move to the next option."""


class FareExceededError(BookingError):
    """Fare is above the human-approved cap. Never auto-retry: escalate."""

    def __init__(self, message: str, fare: int) -> None:
        super().__init__(message)
        self.fare = fare


class PaymentDeclinedError(BookingError):
    """Payment definitively failed (no debit). Safe to retry payment."""


class AmbiguousOutcomeError(BookingError):
    """Request timed out after payment was submitted. The money may have moved.

    The only safe next step is to reconcile using the idempotency key. Never
    resubmit a booking until reconciliation says no booking exists.
    """


class NotWindowOpenError(BookingError):
    """Tatkal window has not opened yet (clock skew). Retry after a short wait."""


class FatalError(BookingError):
    """Invalid input, account blocked, policy violation. Stop and ask a human."""
