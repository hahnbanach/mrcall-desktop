#!/usr/bin/env python3
"""Test script for Google OAuth flow.

Usage:
    1. Run this script: python scripts/test_oauth_flow.py
    2. It will open a browser for Firebase login
    3. After login, it will show your Firebase token
    4. Then it will test the Google OAuth endpoints
"""

import http.server
import json
import socketserver
import threading
import webbrowser
import urllib.parse
import requests
import time

API_BASE = "http://localhost:9000"
CALLBACK_PORT = 8765

# Global to store the token
firebase_token = None


class CallbackHandler(http.server.SimpleHTTPRequestHandler):
    """Handle the OAuth callback."""

    def do_GET(self):
        global firebase_token

        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if 'token' in params:
            firebase_token = params['token'][0]

            # Send success response
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                    <h1>Login Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                    <p style="color: green;">Firebase token received.</p>
                </body>
                </html>
            """)
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"No token received")

    def log_message(self, format, *args):
        pass  # Suppress logging


def start_callback_server():
    """Start a temporary server to receive the callback."""
    with socketserver.TCPServer(("", CALLBACK_PORT), CallbackHandler) as httpd:
        httpd.handle_request()  # Handle single request


def main():
    global firebase_token

    print("=" * 60)
    print("Google OAuth Flow Test")
    print("=" * 60)

    # Check if API is running
    try:
        resp = requests.get(f"{API_BASE}/health")
        if resp.status_code != 200:
            print(f"ERROR: API not healthy: {resp.text}")
            return
        print("✓ API server is running")
    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to API at", API_BASE)
        print("Please start the API server first:")
        print("  cd /Users/mal/hb/zylch")
        print("  venv/bin/python -m uvicorn zylch.api.main:app --host 0.0.0.0 --port 9000")
        return

    print()
    print("Step 1: Firebase Login")
    print("-" * 40)

    # Start callback server in background
    server_thread = threading.Thread(target=start_callback_server)
    server_thread.start()

    # Open browser for Firebase login
    callback_url = f"http://localhost:{CALLBACK_PORT}/callback"
    login_url = f"{API_BASE}/api/auth/oauth/initiate?callback_url={urllib.parse.quote(callback_url)}"

    print(f"Opening browser for Firebase login...")
    print(f"URL: {login_url}")
    webbrowser.open(login_url)

    # Wait for callback
    print("Waiting for login callback...")
    server_thread.join(timeout=120)

    if not firebase_token:
        print("ERROR: Did not receive Firebase token. Did you complete the login?")
        return

    print(f"✓ Got Firebase token: {firebase_token[:50]}...")

    print()
    print("Step 2: Check Google OAuth Status")
    print("-" * 40)

    headers = {"Authorization": f"Bearer {firebase_token}"}

    resp = requests.get(f"{API_BASE}/api/auth/google/status", headers=headers)
    print(f"Status response: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))

    if resp.json().get("has_credentials"):
        print("✓ Google credentials already exist!")
        print()
        print("Do you want to test the OAuth flow anyway? This will re-authenticate.")
        choice = input("Enter 'yes' to continue, anything else to skip: ").strip().lower()
        if choice != 'yes':
            print("Skipping OAuth flow test.")
            return

    print()
    print("Step 3: Initiate Google OAuth")
    print("-" * 40)

    resp = requests.get(f"{API_BASE}/api/auth/google/authorize", headers=headers)
    print(f"Authorize response: {resp.status_code}")

    if resp.status_code != 200:
        print(f"ERROR: {resp.text}")
        return

    auth_data = resp.json()
    auth_url = auth_data.get("auth_url")

    if not auth_url:
        print(f"ERROR: No auth_url in response: {auth_data}")
        return

    print(f"✓ Got OAuth URL")
    print()
    print("Step 4: Complete Google OAuth")
    print("-" * 40)
    print("Opening browser for Google consent...")
    print()
    print("IMPORTANT: After granting permissions, you should see a success page.")
    print()

    webbrowser.open(auth_url)

    # Wait for user to complete OAuth
    input("Press Enter after you've completed the Google OAuth flow...")

    print()
    print("Step 5: Verify Credentials")
    print("-" * 40)

    resp = requests.get(f"{API_BASE}/api/auth/google/status", headers=headers)
    print(f"Final status: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))

    if resp.json().get("has_credentials"):
        print()
        print("=" * 60)
        print("SUCCESS! Google OAuth flow completed.")
        print("Credentials are now stored in Supabase.")
        print("=" * 60)
    else:
        print()
        print("WARNING: Credentials not found. Something may have gone wrong.")


if __name__ == "__main__":
    main()
