"""Explicit, protected configuration for one production voice daemon."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, model_validator

from .business_binding import ExpectedBusiness


class ProductionVoiceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: Path
    owner_uid: str
    business_id: str
    template: str
    test_number: str  # shared listener interface; this is the production called number
    project_id: str
    public_endpoint: str
    vonage_application_id: str
    vonage_api_key: SecretStr
    vonage_signature_secret: SecretStr
    api_key: SecretStr
    webhook_secret: SecretStr
    firebase_web_api_key: SecretStr
    company_knowledge_enabled: bool = False
    voice_per_minute_microusd: int = 50_000
    carrier_per_minute_microusd: int = 20_000
    carrier_setup_microusd: int = 0
    reservation_microusd: int = 10_000_000

    @model_validator(mode="after")
    def validate_binding(self):
        if self.profile.name != self.owner_uid or "@" in self.owner_uid:
            raise ValueError("voice profile must be the Firebase UID")
        if not self.business_id or self.template != "starter":
            raise ValueError("invalid production business")
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", self.test_number):
            raise ValueError("invalid production number")
        if not re.fullmatch(r"proj_[A-Za-z0-9_-]+", self.project_id):
            raise ValueError("invalid OpenAI project")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", self.vonage_application_id):
            raise ValueError("invalid Vonage application")
        if not self.public_endpoint.startswith("https://") or not self.public_endpoint.endswith(
            "/openai/live"
        ):
            raise ValueError("invalid production webhook")
        for secret in (
            self.vonage_api_key, self.vonage_signature_secret, self.api_key,
            self.webhook_secret, self.firebase_web_api_key,
        ):
            if not secret.get_secret_value():
                raise ValueError("missing production credential")
        # Vonage's external default/maximum connect limit is 7200 seconds.
        # USD0.05/min Live and a padded USD0.02/min for both carrier legs plus
        # ringing/cleanup fit below this held estimate without a local cutoff.
        if self.reservation_microusd < 10_000_000:
            raise ValueError("production exposure reserve is insufficient")
        return self

    @property
    def expected_business(self) -> ExpectedBusiness:
        return ExpectedBusiness(self.business_id, self.owner_uid, self.test_number, self.template)

    @property
    def policy_id(self) -> str:
        public = (self.owner_uid, self.business_id, self.test_number, self.template,
                  self.project_id, self.vonage_application_id)
        return hashlib.sha256(json.dumps(public).encode()).hexdigest()

    @property
    def sip_to_uri(self) -> str:
        return f"sip:{self.project_id}@sip.api.openai.com"

    @property
    def duration_seconds(self) -> int:
        return 7200  # external provider maximum; not sent as a local limit

    @property
    def max_calls(self) -> int:
        return 1  # simultaneous active-call capacity, not a lifetime ceiling

    @property
    def unlimited(self) -> bool:
        return True

    @property
    def result_delay_seconds(self) -> int:
        return 0


def load_production_config(path: Path, profile: Path) -> ProductionVoiceConfig:
    """Read only the explicitly selected service file, never ambient test flags."""
    path = path.resolve(strict=True)
    profile = profile.resolve(strict=True)
    values = dotenv_values(path, interpolate=False)
    if values.get("VOICE_PRODUCTION_ENABLED") != "1":
        raise ValueError("Production voice is disabled")
    fields = {
        "owner_uid": "VOICE_PRODUCTION_OWNER_UID",
        "business_id": "VOICE_PRODUCTION_BUSINESS_ID",
        "template": "VOICE_PRODUCTION_TEMPLATE",
        "test_number": "VOICE_PRODUCTION_NUMBER",
        "public_endpoint": "VOICE_PRODUCTION_PUBLIC_ENDPOINT",
        "project_id": "OPENAI_PROJECT_ID",
        "api_key": "OPENAI_API_KEY",
        "webhook_secret": "OPENAI_WEBHOOK_SECRET",
        "firebase_web_api_key": "FIREBASE_WEB_API_KEY",
        "vonage_application_id": "VONAGE_APPLICATION_ID",
        "vonage_api_key": "VONAGE_API_KEY",
        "vonage_signature_secret": "VONAGE_SIGNATURE_SECRET",
    }
    try:
        flag = values.get("VOICE_COMPANY_KNOWLEDGE_ENABLED", "0")
        if flag not in ("0", "1"):
            raise ValueError("Invalid protected company-knowledge switch")
        return ProductionVoiceConfig(
            profile=profile,
            company_knowledge_enabled=flag == "1",
            **{k: values.get(v) for k, v in fields.items()},
        )
    except ValidationError:
        # Pydantic validation errors may include credential input values.
        raise ValueError("Invalid protected production voice configuration") from None
