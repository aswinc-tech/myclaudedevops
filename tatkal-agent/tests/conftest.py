import pytest


@pytest.fixture(autouse=True)
def irctc_account(monkeypatch):
    """Placeholder account for the simulator. Real values come from a secret manager."""
    monkeypatch.setenv("IRCTC_USERNAME", "demo_user01")
    monkeypatch.setenv("IRCTC_PASSWORD", "placeholder-not-a-real-password")
