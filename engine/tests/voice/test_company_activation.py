"""The new company path requires an explicit protected production switch."""

from pathlib import Path

import pytest

from zylch.services.voice.production_config import load_production_config


def test_production_company_knowledge_is_off_without_explicit_switch(tmp_path):
    profile = tmp_path / "firebase-uid"
    profile.mkdir()
    path = tmp_path / "voice.env"
    values = {
        "VOICE_PRODUCTION_ENABLED": "1",
        "VOICE_PRODUCTION_OWNER_UID": profile.name,
        "VOICE_PRODUCTION_BUSINESS_ID": "business-test",
        "VOICE_PRODUCTION_TEMPLATE": "starter",
        "VOICE_PRODUCTION_NUMBER": "+390250552776",
        "VOICE_PRODUCTION_PUBLIC_ENDPOINT": "https://voice.example.test/openai/live",
        "OPENAI_PROJECT_ID": "proj_test",
        "OPENAI_API_KEY": "test-openai-key",
        "OPENAI_WEBHOOK_SECRET": "test-webhook-key",
        "FIREBASE_WEB_API_KEY": "test-firebase-key",
        "VONAGE_APPLICATION_ID": "00000000-0000-0000-0000-000000000001",
        "VONAGE_API_KEY": "test-vonage-key",
        "VONAGE_SIGNATURE_SECRET": "test-signature-key",
    }

    def write(extra: dict[str, str] | None = None):
        path.write_text("\n".join(f"{k}={v}" for k, v in (values | (extra or {})).items()))

    write()
    assert load_production_config(path, Path(profile)).company_knowledge_enabled is False
    write({"VOICE_COMPANY_KNOWLEDGE_ENABLED": "1"})
    assert load_production_config(path, Path(profile)).company_knowledge_enabled is True
    write({"VOICE_COMPANY_KNOWLEDGE_ENABLED": "invalid"})
    with pytest.raises(ValueError, match="company-knowledge switch"):
        load_production_config(path, Path(profile))
