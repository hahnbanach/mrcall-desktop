"""Explicit profile-file configuration for the supervised M1 experiment."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator


class SmokeConfigurationError(ValueError):
    """A safe, non-secret configuration diagnostic."""


class SmokeConfig(BaseModel):
    """Validated snapshot; prices/reservations use integer USD microdollars."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    profile: Path
    owner_uid: str
    project_id: str
    test_number: str
    sip_to_uri: str
    public_endpoint: str
    engine_provider: str
    readiness_reference: str
    api_key: SecretStr
    webhook_secret: SecretStr
    duration_seconds: int = Field(default=180, ge=1, le=180)
    max_calls: int = Field(default=6, ge=1, le=6)
    reservation_microusd: int = Field(gt=0, le=5_000_000)
    voice_per_minute_microusd: int = Field(gt=0)
    carrier_per_minute_microusd: int = Field(ge=0)
    carrier_setup_microusd: int = Field(ge=0)
    result_delay_seconds: int = Field(default=5, ge=0, le=30)

    @model_validator(mode="after")
    def boundaries(self) -> "SmokeConfig":
        if self.profile.name != self.owner_uid or "@" in self.owner_uid:
            raise ValueError("profile must be keyed by its Firebase UID")
        if not re.fullmatch(r"proj_[A-Za-z0-9_-]+", self.project_id):
            raise ValueError("invalid project ID")
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", self.test_number):
            raise ValueError("test number must use E.164")
        if not re.fullmatch(r"sips?:[^\s<>]+@[^\s<>]+", self.sip_to_uri):
            raise ValueError("expected SIP To URI is required")
        if not self.public_endpoint.startswith("https://") or not self.public_endpoint.endswith(
            "/openai/live"
        ):
            raise ValueError("HTTPS webhook endpoint is required")
        if self.engine_provider not in {"anthropic", "openrouter", "mrcall"}:
            raise ValueError("explicit engine provider required")
        if not self.api_key.get_secret_value() or not self.webhook_secret.get_secret_value():
            raise ValueError("missing credentials")
        if not self.readiness_reference.strip():
            raise ValueError("supervised test preflight reference required")
        # Reserve rounded-up minutes including bounded control/finalization grace.
        # M1 makes no engine reasoning request; the fixed result costs no tokens.
        minutes = (self.duration_seconds + 20 + 59) // 60
        minimum = self.carrier_setup_microusd + minutes * (
            self.voice_per_minute_microusd + self.carrier_per_minute_microusd
        )
        if self.reservation_microusd < minimum:
            raise ValueError("reservation is below the configured conservative call estimate")
        return self

    @property
    def policy_id(self) -> str:
        """Pin the run to its public configuration, allowing secret rotation only."""
        public = self.model_dump(mode="json", exclude={"api_key", "webhook_secret"})
        return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()


def load_smoke_config(profile: Path) -> SmokeConfig:
    """Never inherit a test marker, identity, credentials or rates from the shell."""
    profile = profile.resolve(strict=True)
    values = dotenv_values(profile / ".env", interpolate=False)
    if values.get("VOICE_SMOKE_TEST_PROFILE") != profile.name:
        raise SmokeConfigurationError("selected profile file has no matching test marker")
    if values.get("VOICE_SMOKE_READY") != "1":
        raise SmokeConfigurationError("isolated routing/access/rates preflight is not confirmed")
    fields = {
        "owner_uid": "OWNER_ID",
        "project_id": "OPENAI_PROJECT_ID",
        "test_number": "VOICE_SMOKE_TEST_NUMBER",
        "sip_to_uri": "VOICE_SMOKE_SIP_TO_URI",
        "public_endpoint": "VOICE_SMOKE_PUBLIC_ENDPOINT",
        "engine_provider": "LLM_PROVIDER",
        "readiness_reference": "VOICE_SMOKE_PREFLIGHT_REFERENCE",
        "api_key": "OPENAI_API_KEY",
        "webhook_secret": "OPENAI_WEBHOOK_SECRET",
        "reservation_microusd": "VOICE_SMOKE_RESERVATION_MICROUSD",
        "voice_per_minute_microusd": "VOICE_SMOKE_VOICE_MICROUSD_PER_MINUTE",
        "carrier_per_minute_microusd": "VOICE_SMOKE_CARRIER_MICROUSD_PER_MINUTE",
        "carrier_setup_microusd": "VOICE_SMOKE_CARRIER_SETUP_MICROUSD",
    }
    optional = {
        "duration_seconds": "VOICE_SMOKE_DURATION_SECONDS",
        "max_calls": "VOICE_SMOKE_MAX_CALLS",
        "result_delay_seconds": "VOICE_SMOKE_RESULT_DELAY_SECONDS",
    }
    data = {field: values.get(key) for field, key in fields.items()}
    data.update({field: values[key] for field, key in optional.items() if key in values})
    try:
        return SmokeConfig(profile=profile, **data)
    except ValidationError as exc:
        # Pydantic errors may contain secret input values. Never render them.
        names = sorted({str(e["loc"][0]) if e["loc"] else "policy" for e in exc.errors()})
        raise SmokeConfigurationError("invalid smoke configuration: " + ", ".join(names)) from None
