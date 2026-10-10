"""Keep engine Firebase defaults compatible with the shipped Desktop client."""

import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from zylch.config import Settings


class FirebaseDefaultsContractTests(unittest.TestCase):
    @staticmethod
    def desktop_value(field: str) -> str:
        root = Path(__file__).resolve().parents[3]
        source = (root / "app/src/renderer/src/firebase/config.ts").read_text()
        match = re.search(r"\b" + re.escape(field) + r"\s*:\s*'([^']+)'", source)
        if match is None:
            raise AssertionError(f"Desktop Firebase field missing: {field}")
        return match.group(1)

    def test_default_key_matches_desktop(self):
        self.assertEqual(
            Settings.model_fields["firebase_web_api_key"].default,
            self.desktop_value("apiKey"),
        )

    def test_default_project_matches_desktop(self):
        self.assertEqual(
            Settings.model_fields["firebase_project_id"].default,
            self.desktop_value("projectId"),
        )

    def test_explicit_environment_key_still_overrides_default(self):
        with patch.dict(
            os.environ, {"FIREBASE_WEB_API_KEY": "explicit-public-key-override"}, clear=True
        ):
            self.assertEqual(
                Settings(_env_file=None).firebase_web_api_key, "explicit-public-key-override"
            )


if __name__ == "__main__":
    unittest.main()
