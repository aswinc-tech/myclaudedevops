from __future__ import annotations

import os

from .base import BookingProvider, LoginChallenge
from .mock import MockProvider, MockScenario

__all__ = ["BookingProvider", "LoginChallenge", "MockProvider", "MockScenario", "make_provider"]


def make_provider() -> BookingProvider:
    """Pick the backend from TATKAL_PROVIDER (default: mock)."""
    kind = os.getenv("TATKAL_PROVIDER", "mock").lower()
    if kind == "mock":
        opens_in = os.getenv("MOCK_WINDOW_OPENS_IN_SECONDS", "20")
        return MockProvider(
            MockScenario(
                window_opens_in_seconds=None if opens_in.lower() == "real" else float(opens_in),
                seed=int(os.getenv("MOCK_SEED", "7")),
            )
        )
    if kind == "partner":
        from .partner import PartnerApiProvider

        return PartnerApiProvider()
    raise ValueError(f"Unknown TATKAL_PROVIDER={kind!r}")
