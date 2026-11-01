"""Traveller profile: passengers and preferences, loaded server-side.

Passenger details stay inside the MCP server. The agent works with a passenger
*count*; names and ages are shown only to the human in approval prompts. No
passwords live here: IRCTC credentials come from environment variables /
a secret manager inside the provider.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from .models import Passenger

EXAMPLE = Path(__file__).resolve().parents[2] / "profile.example.json"


class TravellerProfile(BaseModel):
    passengers: list[Passenger] = Field(min_length=1, max_length=4)  # Tatkal allows max 4 per PNR
    payment_method: str = "UPI"
    mobile_hint: str = Field(default="", description="Last digits only, for OTP prompts")


def load_profile(path: str | None = None) -> TravellerProfile:
    p = Path(path or os.getenv("TATKAL_PROFILE", "profile.json"))
    if not p.exists():
        p = EXAMPLE
    return TravellerProfile.model_validate(json.loads(p.read_text()))
