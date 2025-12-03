"""CLI Authentication Manager for Firebase authentication.

Handles browser-based OAuth flow for CLI login:
1. Start local HTTP server
2. Open browser to login page
3. User authenticates via Firebase
4. Receive token via callback
5. Save credentials to ~/.zylch/credentials.json
"""

import json
import logging
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


class CLIAuthManager:
    """Manages CLI authentication with Firebase."""

    CREDENTIALS_DIR = Path.home() / ".zylch" / "credentials"
    DEFAULT_PORT = 9876
    TOKEN_EXPIRY_BUFFER_MINUTES = 5  # Refresh if expiring within 5 minutes

    def __init__(self):
        """Initialize auth manager."""
        self._ensure_credentials_dir()

    def _ensure_credentials_dir(self):
        """Create credentials directory if it doesn't exist."""
        self.CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    def _get_credentials_path(self, provider: str = None) -> Path:
        """Get credentials file path for a specific provider.

        Args:
            provider: Provider name (google.com or microsoft.com). If None, tries to detect.

        Returns:
            Path to credentials file
        """
        if provider == "google.com":
            provider_dir = self.CREDENTIALS_DIR / "google"
        elif provider == "microsoft.com":
            provider_dir = self.CREDENTIALS_DIR / "microsoft"
        else:
            # Try to detect from existing credentials
            google_creds = self.CREDENTIALS_DIR / "google" / "credentials.json"
            microsoft_creds = self.CREDENTIALS_DIR / "microsoft" / "credentials.json"

            if google_creds.exists():
                return google_creds
            elif microsoft_creds.exists():
                return microsoft_creds
            else:
                # Default to google for backwards compatibility
                provider_dir = self.CREDENTIALS_DIR / "google"

        provider_dir.mkdir(parents=True, exist_ok=True)
        return provider_dir / "credentials.json"

    @property
    def CREDENTIALS_PATH(self) -> Path:
        """Get current credentials path (tries to detect provider)."""
        return self._get_credentials_path()

    def login(self, port: int = None) -> bool:
        """Start OAuth flow: open browser, wait for callback, save credentials.

        Args:
            port: Local server port (default: 9876)

        Returns:
            True if login successful, False otherwise
        """
        port = port or self.DEFAULT_PORT

        # Import here to avoid circular imports
        from .auth_server import AuthCallbackServer

        print(f"🔐 Opening browser for authentication...")
        print(f"   If browser doesn't open, visit: http://localhost:{port}/auth")
        print()

        # Start local server and wait for callback
        server = AuthCallbackServer(port=port)

        try:
            # Open browser
            auth_url = f"http://localhost:{port}/auth"
            webbrowser.open(auth_url)

            # Wait for callback (blocks until user completes login or timeout)
            credentials = server.start_and_wait(timeout=300)

            if credentials:
                # Save credentials
                self._save_credentials(credentials)

                print()
                print(f"✅ Logged in as {credentials.get('display_name', 'User')} ({credentials.get('email', 'unknown')})")
                print(f"   Token saved to {self.CREDENTIALS_PATH}")

                # Calculate expiry
                expires_at = credentials.get("expires_at")
                if expires_at:
                    try:
                        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                        # Convert to local time for display
                        exp_local = exp_dt.astimezone()
                        print(f"   Expires: {exp_local.strftime('%Y-%m-%d %H:%M')} (local time)")
                    except Exception:
                        pass

                return True
            else:
                print()
                print("❌ Login failed or timed out")
                return False

        except KeyboardInterrupt:
            print()
            print("❌ Login cancelled")
            return False
        except Exception as e:
            logger.exception(f"Login error: {e}")
            print()
            print(f"❌ Login error: {e}")
            return False

    def logout(self) -> bool:
        """Delete stored credentials (all providers).

        Returns:
            True if logout successful
        """
        try:
            deleted = False

            # Delete Google credentials
            google_creds = self._get_credentials_path("google.com")
            if google_creds.exists():
                google_creds.unlink()
                print(f"✅ Deleted Google credentials: {google_creds}")
                deleted = True

            # Delete Microsoft credentials
            microsoft_creds = self._get_credentials_path("microsoft.com")
            if microsoft_creds.exists():
                microsoft_creds.unlink()
                print(f"✅ Deleted Microsoft credentials: {microsoft_creds}")
                deleted = True

            if deleted:
                print("✅ Logged out successfully")
            else:
                print("ℹ️  No active session")

            return True
        except Exception as e:
            logger.exception(f"Logout error: {e}")
            print(f"❌ Logout error: {e}")
            return False

    def is_authenticated(self) -> bool:
        """Check if valid credentials exist.

        Returns:
            True if valid, non-expired credentials exist
        """
        creds = self.get_credentials()
        if not creds:
            return False

        # Check expiry
        expires_at = creds.get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)

                if exp_dt <= now:
                    logger.info("Credentials expired")
                    return False
            except Exception as e:
                logger.warning(f"Error checking expiry: {e}")

        return True

    def get_credentials(self) -> Optional[dict]:
        """Load credentials from file.

        Returns:
            Credentials dict or None if not found/invalid
        """
        if not self.CREDENTIALS_PATH.exists():
            return None

        try:
            with open(self.CREDENTIALS_PATH, "r") as f:
                creds = json.load(f)

            # Validate required fields
            required = ["token", "owner_id", "email"]
            if not all(k in creds for k in required):
                logger.warning("Invalid credentials file - missing required fields")
                return None

            return creds

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid credentials JSON: {e}")
            return None
        except Exception as e:
            logger.exception(f"Error reading credentials: {e}")
            return None

    def get_owner_id(self) -> Optional[str]:
        """Get Firebase UID from credentials.

        Returns:
            Owner ID or None if not authenticated
        """
        creds = self.get_credentials()
        return creds.get("owner_id") if creds else None

    def get_token(self) -> Optional[str]:
        """Get Firebase ID token.

        Returns:
            Token or None if not authenticated
        """
        creds = self.get_credentials()
        return creds.get("token") if creds else None

    def get_user_info(self) -> dict:
        """Get user info from credentials.

        Returns:
            Dict with email, display_name, owner_id
        """
        creds = self.get_credentials()
        if not creds:
            return {}

        return {
            "email": creds.get("email", ""),
            "display_name": creds.get("display_name", ""),
            "owner_id": creds.get("owner_id", "")
        }

    def needs_refresh(self) -> bool:
        """Check if token needs refresh (expiring soon).

        Returns:
            True if token expires within buffer time
        """
        creds = self.get_credentials()
        if not creds:
            return True

        expires_at = creds.get("expires_at")
        if not expires_at:
            return False  # No expiry info, assume valid

        try:
            exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)

            from datetime import timedelta
            buffer = timedelta(minutes=self.TOKEN_EXPIRY_BUFFER_MINUTES)

            return (exp_dt - now) <= buffer
        except Exception as e:
            logger.warning(f"Error checking token refresh: {e}")
            return False

    def _save_credentials(self, credentials: dict):
        """Save credentials to provider-specific file.

        Args:
            credentials: Dict with token, owner_id, email, provider, etc.
        """
        # Add created_at timestamp
        credentials["created_at"] = datetime.now(timezone.utc).isoformat()

        # Get provider-specific path
        provider = credentials.get("provider", "google.com")
        creds_path = self._get_credentials_path(provider)

        with open(creds_path, "w") as f:
            json.dump(credentials, f, indent=2)

        # Set file permissions to user-only (600)
        creds_path.chmod(0o600)

        logger.info(f"Credentials saved to {creds_path}")


def main():
    """CLI entry point for auth commands."""
    auth = CLIAuthManager()

    if len(sys.argv) < 2:
        print("Usage: python -m zylch.cli.auth [login|logout|status]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "login":
        success = auth.login()
        sys.exit(0 if success else 1)

    elif command == "logout":
        success = auth.logout()
        sys.exit(0 if success else 1)

    elif command == "status":
        if auth.is_authenticated():
            info = auth.get_user_info()
            print(f"✅ Logged in as {info.get('display_name', 'User')} ({info.get('email', 'unknown')})")
            print(f"   Owner ID: {info.get('owner_id', 'unknown')}")
        else:
            print("❌ Not logged in")
            print("   Run: zylch-cli --login")
        sys.exit(0)

    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m zylch.cli.auth [login|logout|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
