"""The traveller's IRCTC account (user id + password).

Loaded from environment variables at login time, inside the provider. The values
are wrapped in pydantic ``SecretStr`` so they never show up in reprs, logs, tool
results or the LLM context. In production, populate the env vars from a secret
manager (Vault, AWS SSM, Doppler, 1Password CLI) rather than a file in the repo.

    export IRCTC_USERNAME="your-irctc-user-id"
    export IRCTC_PASSWORD="…set from your secret manager, never commit…"
"""

from __future__ import annotations

import os

from pydantic import BaseModel, SecretStr

from .errors import FatalError

USERNAME_ENV = "IRCTC_USERNAME"
PASSWORD_ENV = "IRCTC_PASSWORD"


class IrctcAccount(BaseModel):
    username: SecretStr
    password: SecretStr

    @property
    def masked_username(self) -> str:
        u = self.username.get_secret_value()
        return u[:2] + "*" * max(1, len(u) - 4) + u[-2:] if len(u) > 4 else "****"


def load_account() -> IrctcAccount:
    username = os.getenv(USERNAME_ENV, "").strip()
    password = os.getenv(PASSWORD_ENV, "")
    missing = [n for n, v in ((USERNAME_ENV, username), (PASSWORD_ENV, password)) if not v]
    if missing:
        raise FatalError(
            f"Missing {', '.join(missing)}. Set them in the environment (from your secret manager) "
            "before starting the server. Never paste them into the chat."
        )
    return IrctcAccount(username=SecretStr(username), password=SecretStr(password))
