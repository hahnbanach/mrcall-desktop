"""OAuth handlers for CLI with local HTTP server pattern.

Handles OAuth flows for providers that require browser-based consent,
using a local HTTP server on port 8765 to receive callbacks.
"""

import http.server
import json
import logging
import socketserver
import threading
import time
import webbrowser
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)

CALLBACK_PORT = 8765


class MrCallOAuthHandler(http.server.SimpleHTTPRequestHandler):
    """Handle MrCall OAuth callback with local HTTP server."""

    authorization_code: Optional[str] = None
    oauth_state: Optional[str] = None
    oauth_error: Optional[str] = None

    def do_GET(self):
        """Handle GET request from OAuth callback."""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if 'code' in params and 'state' in params:
            # Success - got authorization code
            MrCallOAuthHandler.authorization_code = params['code'][0]
            MrCallOAuthHandler.oauth_state = params['state'][0]

            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                    <h1>MrCall Connected!</h1>
                    <p>Authorization successful. You can close this window.</p>
                    <p style="color: green;">Return to your terminal to continue.</p>
                </body>
                </html>
            """)
        elif 'error' in params:
            # Error from OAuth provider
            MrCallOAuthHandler.oauth_error = params['error'][0]
            error_description = params.get('error_description', ['Unknown error'])[0]

            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(f"""
                <html>
                <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                    <h1>Authorization Failed</h1>
                    <p style="color: red;">Error: {params['error'][0]}</p>
                    <p>{error_description}</p>
                    <p>Please try again or contact support.</p>
                </body>
                </html>
            """.encode())
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Invalid callback - missing code or error parameter")

    def log_message(self, format, *args):
        """Suppress HTTP server logging."""
        pass


async def handle_mrcall_oauth_flow(api_base_url: str, owner_id: str) -> bool:
    """
    Handle complete MrCall OAuth flow with local server.

    This function:
    1. Calls backend to get OAuth authorization URL
    2. Starts local HTTP server on port 8765
    3. Opens browser for user to authorize
    4. Waits for callback with authorization code
    5. Calls backend callback endpoint to exchange code for tokens

    Args:
        api_base_url: Zylch API base URL (e.g., http://localhost:8000)
        owner_id: Firebase UID of the user

    Returns:
        True if successful, False otherwise
    """
    import requests

    # Reset class variables
    MrCallOAuthHandler.authorization_code = None
    MrCallOAuthHandler.oauth_state = None
    MrCallOAuthHandler.oauth_error = None

    try:
        # Step 1: Get OAuth URL from backend
        print("Initiating MrCall OAuth flow...")
        response = requests.get(
            f"{api_base_url}/api/auth/mrcall/authorize",
            params={"owner_id": owner_id},
            timeout=10
        )

        if response.status_code != 200:
            print(f"Error: Failed to initiate OAuth - {response.text}")
            return False

        data = response.json()
        auth_url = data.get('auth_url')
        state = data.get('state')

        if not auth_url:
            print(f"Error: No auth_url in response: {data}")
            return False

        # Step 2: Start local callback server
        print(f"Starting local callback server on port {CALLBACK_PORT}...")
        server = socketserver.TCPServer(("", CALLBACK_PORT), MrCallOAuthHandler)
        server_thread = threading.Thread(target=lambda: server.handle_request())
        server_thread.daemon = True
        server_thread.start()

        # Step 3: Open browser for OAuth flow
        print()
        print("=" * 60)
        print("Opening browser for MrCall authorization...")
        print("=" * 60)
        print()
        print(f"Authorization URL: {auth_url}")
        print()
        print("Please log into MrCall and approve the connection.")
        print("After approval, you will be redirected back.")
        print()
        print("Waiting for callback...")
        print()

        webbrowser.open(auth_url)

        # Wait for callback (5 minute timeout)
        timeout = 300  # 5 minutes
        start_time = time.time()
        while time.time() - start_time < timeout:
            if MrCallOAuthHandler.authorization_code or MrCallOAuthHandler.oauth_error:
                break
            time.sleep(0.5)

        server.server_close()

        # Check result
        if MrCallOAuthHandler.oauth_error:
            print()
            print("=" * 60)
            print(f"Authorization failed: {MrCallOAuthHandler.oauth_error}")
            print("=" * 60)
            return False

        if not MrCallOAuthHandler.authorization_code:
            print()
            print("=" * 60)
            print("No authorization code received. Did you complete the flow?")
            print("=" * 60)
            return False

        print()
        print("Authorization code received")

        # Step 4: Exchange code for tokens via backend callback endpoint
        print("Exchanging code for access token...")

        callback_response = requests.get(
            f"{api_base_url}/api/auth/mrcall/callback",
            params={
                "code": MrCallOAuthHandler.authorization_code,
                "state": MrCallOAuthHandler.oauth_state or state
            },
            timeout=30
        )

        if callback_response.status_code == 200:
            print()
            print("=" * 60)
            print("MrCall connected successfully!")
            print("=" * 60)
            print()
            print("You can now use MrCall tools with /mrcall commands.")
            return True
        else:
            print()
            print("=" * 60)
            print(f"Token exchange failed: {callback_response.status_code}")
            print(f"Response: {callback_response.text}")
            print("=" * 60)
            return False

    except requests.exceptions.Timeout:
        print()
        print("=" * 60)
        print("Request timed out. Please check your internet connection.")
        print("=" * 60)
        return False
    except requests.exceptions.ConnectionError:
        print()
        print("=" * 60)
        print(f"Cannot connect to API at {api_base_url}")
        print("Please ensure the Zylch API server is running.")
        print("=" * 60)
        return False
    except Exception as e:
        logger.error(f"OAuth flow error: {e}", exc_info=True)
        print()
        print("=" * 60)
        print(f"Unexpected error: {e}")
        print("=" * 60)
        return False
