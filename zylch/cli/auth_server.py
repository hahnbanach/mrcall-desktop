"""Local HTTP server for Firebase OAuth callback.

Serves a login page with Firebase SDK, receives the token via callback,
and returns it to the CLI.
"""

import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import parse_qs, urlparse

from ..config import settings

logger = logging.getLogger(__name__)


class AuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""

    # Shared state between requests
    received_credentials: Optional[dict] = None
    server_should_stop = False

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/auth":
            self._serve_login_page()
        elif path == "/success":
            self._serve_success_page()
        elif path == "/config":
            self._serve_config()
        else:
            self._send_404()

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/callback":
            self._handle_callback()
        else:
            self._send_404()

    def _serve_login_page(self):
        """Serve the Firebase login page."""
        html = self._get_login_page_html()
        self._send_response(200, "text/html", html)

    def _serve_success_page(self):
        """Serve the success page after login."""
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Zylch - Login Successful!</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #1a1a1a;
            -webkit-font-smoothing: antialiased;
        }
        .container {
            text-align: center;
            padding: 60px 40px;
            background: white;
            border-radius: 24px;
            box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
            max-width: 420px;
        }
        .logo {
            margin-bottom: 30px;
        }
        .logo svg {
            height: 45px;
            width: auto;
        }
        .checkmark {
            width: 80px;
            height: 80px;
            background: linear-gradient(135deg, #27ca3f 0%, #20a835 100%);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 28px;
            color: white;
            font-size: 36px;
            box-shadow: 0 10px 30px rgba(39, 202, 63, 0.4);
            animation: pulse 2s ease-in-out infinite;
        }
        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.05); }
        }
        h1 {
            font-weight: 600;
            font-size: 1.5rem;
            margin-bottom: 12px;
            color: #1a1a1a;
        }
        .subtitle {
            color: #666;
            font-size: 1rem;
            margin-bottom: 24px;
            line-height: 1.5;
        }
        .terminal-hint {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #f5f5f5;
            padding: 12px 20px;
            border-radius: 12px;
            font-size: 0.9rem;
            color: #555;
        }
        .terminal-hint .icon {
            font-size: 1.2rem;
        }
        .countdown {
            margin-top: 20px;
            font-size: 0.85rem;
            color: #999;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <svg viewBox="0 0 350 100" xmlns="http://www.w3.org/2000/svg">
                <path d="M 15 25 C 35 24, 65 23, 85 22 C 65 40, 35 60, 15 78 C 35 77, 65 76, 85 75" stroke="#1a1a1a" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                <text x="95" y="72" font-family="Inter, Arial, sans-serif" font-size="64" font-weight="400" fill="#1a1a1a">ylch</text>
            </svg>
        </div>
        <div class="checkmark">&#10003;</div>
        <h1>You're all set!</h1>
        <p class="subtitle">Login successful. Your credentials have been saved.</p>
        <div class="terminal-hint">
            <span class="icon">&#9000;</span>
            <span>Return to your terminal to continue</span>
        </div>
        <p class="countdown" id="countdown">This tab will close in <span id="seconds">5</span> seconds...</p>
    </div>
    <script>
        // Try to close the tab after countdown
        let seconds = 5;
        const countdownEl = document.getElementById('seconds');
        const countdownContainer = document.getElementById('countdown');

        const timer = setInterval(() => {
            seconds--;
            countdownEl.textContent = seconds;

            if (seconds <= 0) {
                clearInterval(timer);
                // Try to close the tab (works if opened by script)
                window.close();
                // If we're still here after 500ms, update message
                setTimeout(() => {
                    countdownContainer.textContent = 'You can safely close this tab now.';
                }, 500);
            }
        }, 1000);
    </script>
</body>
</html>"""
        self._send_response(200, "text/html", html)

    def _serve_config(self):
        """Serve Firebase config as JSON."""
        config = {
            "apiKey": settings.firebase_api_key,
            "authDomain": settings.firebase_auth_domain,
            "projectId": settings.firebase_project_id,
        }
        self._send_response(200, "application/json", json.dumps(config))

    def _handle_callback(self):
        """Handle token callback from JavaScript."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)

            # Extract credentials
            token = data.get("token")
            uid = data.get("uid")
            email = data.get("email")
            display_name = data.get("displayName") or data.get("display_name") or email
            graph_token = data.get("graphToken")  # Microsoft Graph API token
            provider = data.get("provider", "google.com")  # Default to Google

            if not token or not uid:
                self._send_response(400, "application/json", json.dumps({"error": "Missing token or uid"}))
                return

            # Calculate token expiry (Firebase tokens expire in 1 hour)
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

            # Store credentials
            creds = {
                "token": token,
                "owner_id": uid,
                "email": email,
                "display_name": display_name,
                "expires_at": expires_at,
                "provider": provider,
            }

            # Add Microsoft Graph token if present
            if graph_token:
                creds["graph_token"] = graph_token
                # Graph tokens also expire in 1 hour
                creds["graph_expires_at"] = expires_at

            AuthCallbackHandler.received_credentials = creds

            # Signal server to stop
            AuthCallbackHandler.server_should_stop = True

            self._send_response(200, "application/json", json.dumps({"status": "ok"}))

            logger.info(f"Received credentials for {email}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in callback: {e}")
            self._send_response(400, "application/json", json.dumps({"error": "Invalid JSON"}))
        except Exception as e:
            logger.exception(f"Callback error: {e}")
            self._send_response(500, "application/json", json.dumps({"error": str(e)}))

    def _send_response(self, status: int, content_type: str, body: str):
        """Send HTTP response."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body.encode("utf-8")))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _send_404(self):
        """Send 404 response."""
        self._send_response(404, "text/plain", "Not Found")

    def _get_login_page_html(self) -> str:
        """Generate the login page HTML with Firebase SDK."""
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Zylch - Sign In</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #ffffff;
            --text-primary: #1a1a1a;
            --text-muted: #888888;
            --accent: #4a9eff;
            --radius: 12px;
            --shadow: 0 2px 8px rgba(0,0,0,0.08);
            --shadow-lg: 0 8px 32px rgba(0,0,0,0.12);
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background: var(--bg-primary);
            color: var(--text-primary);
            -webkit-font-smoothing: antialiased;
        }}
        .container {{
            text-align: center;
            max-width: 380px;
            width: 90%;
            padding: 40px 20px;
        }}
        .logo {{
            margin-bottom: 8px;
        }}
        .logo svg {{
            height: 50px;
            width: auto;
        }}
        .tagline {{
            color: var(--text-muted);
            font-size: 0.95rem;
            margin-bottom: 40px;
        }}
        .btn {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            width: 100%;
            padding: 14px 20px;
            margin-bottom: 12px;
            border: none;
            border-radius: var(--radius);
            font-size: 0.95rem;
            font-weight: 500;
            font-family: inherit;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .btn:hover {{
            transform: translateY(-1px);
            box-shadow: var(--shadow-lg);
        }}
        .btn:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }}
        .btn-google {{
            background: var(--bg-primary);
            color: var(--text-primary);
            border: 1px solid #e0e0e0;
        }}
        .btn-google:hover {{
            border-color: var(--accent);
            background: #fafafa;
        }}
        .btn-microsoft {{
            background: var(--bg-primary);
            color: var(--text-primary);
            border: 1px solid #e0e0e0;
        }}
        .btn-microsoft:hover {{
            border-color: #00a4ef;
            background: #fafafa;
        }}
        .btn-primary {{
            background: var(--text-primary);
            color: var(--bg-primary);
        }}
        .btn-primary:hover {{
            background: #333;
        }}
        .google-icon {{
            width: 18px;
            height: 18px;
        }}
        .divider {{
            display: flex;
            align-items: center;
            margin: 20px 0;
            color: var(--text-muted);
        }}
        .divider::before, .divider::after {{
            content: '';
            flex: 1;
            height: 1px;
            background: #e0e0e0;
        }}
        .divider span {{
            padding: 0 15px;
            font-size: 0.85rem;
        }}
        .email-form {{
            display: none;
        }}
        .email-form.active {{
            display: block;
        }}
        .input-group {{
            margin-bottom: 12px;
            text-align: left;
        }}
        .input-group label {{
            display: block;
            margin-bottom: 6px;
            color: var(--text-primary);
            font-weight: 500;
            font-size: 0.9rem;
        }}
        .input-group input {{
            width: 100%;
            padding: 12px 14px;
            border: 1px solid #e0e0e0;
            border-radius: var(--radius);
            font-size: 1rem;
            font-family: inherit;
            transition: border-color 0.2s ease;
        }}
        .input-group input:focus {{
            outline: none;
            border-color: var(--accent);
        }}
        .input-group input::placeholder {{
            color: var(--text-muted);
        }}
        .error {{
            color: #ff5f56;
            font-size: 0.9rem;
            margin-top: 12px;
            display: none;
        }}
        .error.active {{
            display: block;
        }}
        .back-link {{
            color: var(--text-muted);
            cursor: pointer;
            font-size: 0.9rem;
            margin-top: 16px;
            display: inline-block;
            transition: color 0.2s ease;
        }}
        .back-link:hover {{
            color: var(--text-primary);
        }}
        .loading {{
            display: none;
        }}
        .loading.active {{
            display: block;
        }}
        .spinner {{
            width: 32px;
            height: 32px;
            border: 3px solid #e0e0e0;
            border-top: 3px solid var(--text-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 20px auto;
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        .footer {{
            margin-top: 40px;
            font-size: 0.8rem;
            color: var(--text-muted);
        }}
        .footer a {{
            color: var(--text-muted);
            text-decoration: none;
        }}
        .footer a:hover {{
            color: var(--text-primary);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <svg viewBox="0 0 350 100" xmlns="http://www.w3.org/2000/svg">
                <path d="M 15 25 C 35 24, 65 23, 85 22 C 65 40, 35 60, 15 78 C 35 77, 65 76, 85 75" stroke="#1a1a1a" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                <text x="95" y="72" font-family="Inter, Arial, sans-serif" font-size="64" font-weight="400" fill="#1a1a1a">ylch</text>
            </svg>
        </div>
        <p class="tagline">Sign in to continue</p>

        <div id="main-buttons">
            <button class="btn btn-google" onclick="signInWithGoogle()">
                <svg class="google-icon" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                </svg>
                Continue with Google
            </button>

            <button class="btn btn-microsoft" onclick="signInWithMicrosoft()">
                <svg class="google-icon" viewBox="0 0 24 24">
                    <rect x="1" y="1" width="10" height="10" fill="#f25022"/>
                    <rect x="13" y="1" width="10" height="10" fill="#7fba00"/>
                    <rect x="1" y="13" width="10" height="10" fill="#00a4ef"/>
                    <rect x="13" y="13" width="10" height="10" fill="#ffb900"/>
                </svg>
                Continue with Microsoft
            </button>

            <div class="divider"><span>or</span></div>

            <button class="btn btn-primary" onclick="showEmailForm()">
                Continue with Email
            </button>
        </div>

        <div id="email-form" class="email-form">
            <div class="input-group">
                <label for="email">Email</label>
                <input type="email" id="email" placeholder="your@email.com">
            </div>
            <div class="input-group">
                <label for="password">Password</label>
                <input type="password" id="password" placeholder="Your password">
            </div>
            <button class="btn btn-primary" onclick="signInWithEmail()">
                Sign In
            </button>
            <div class="back-link" onclick="showMainButtons()">← Back</div>
        </div>

        <div id="loading" class="loading">
            <div class="spinner"></div>
            <p>Signing in...</p>
        </div>

        <div id="error" class="error"></div>

        <div class="footer">
            <a href="https://zylchai.com" target="_blank">zylchai.com</a>
        </div>
    </div>

    <!-- Firebase SDK -->
    <script src="https://www.gstatic.com/firebasejs/10.7.0/firebase-app-compat.js"></script>
    <script src="https://www.gstatic.com/firebasejs/10.7.0/firebase-auth-compat.js"></script>

    <script>
        // Firebase config
        const firebaseConfig = {{
            apiKey: "{settings.firebase_api_key}",
            authDomain: "{settings.firebase_auth_domain}",
            projectId: "{settings.firebase_project_id}"
        }};

        // Initialize Firebase
        firebase.initializeApp(firebaseConfig);
        const auth = firebase.auth();

        function showError(message) {{
            const errorEl = document.getElementById('error');
            errorEl.textContent = message;
            errorEl.classList.add('active');
        }}

        function hideError() {{
            document.getElementById('error').classList.remove('active');
        }}

        function showLoading() {{
            document.getElementById('main-buttons').style.display = 'none';
            document.getElementById('email-form').classList.remove('active');
            document.getElementById('loading').classList.add('active');
            hideError();
        }}

        function hideLoading() {{
            document.getElementById('loading').classList.remove('active');
            document.getElementById('main-buttons').style.display = 'block';
        }}

        function showEmailForm() {{
            document.getElementById('main-buttons').style.display = 'none';
            document.getElementById('email-form').classList.add('active');
            hideError();
        }}

        function showMainButtons() {{
            document.getElementById('email-form').classList.remove('active');
            document.getElementById('main-buttons').style.display = 'block';
            hideError();
        }}

        async function sendTokenToServer(user, graphToken = null, provider = null) {{
            try {{
                const token = await user.getIdToken();

                const payload = {{
                    token: token,
                    uid: user.uid,
                    email: user.email,
                    displayName: user.displayName || user.email
                }};

                // Add Graph API token if Microsoft login
                if (graphToken) {{
                    payload.graphToken = graphToken;
                }}
                if (provider) {{
                    payload.provider = provider;
                }}

                const response = await fetch('/callback', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});

                if (response.ok) {{
                    window.location.href = '/success';
                }} else {{
                    throw new Error('Failed to send token to CLI');
                }}
            }} catch (error) {{
                console.error('Error sending token:', error);
                hideLoading();
                showError('Failed to complete login. Please try again.');
            }}
        }}

        async function signInWithGoogle() {{
            showLoading();
            try {{
                const provider = new firebase.auth.GoogleAuthProvider();
                const result = await auth.signInWithPopup(provider);
                await sendTokenToServer(result.user, null, 'google.com');
            }} catch (error) {{
                console.error('Google sign-in error:', error);
                hideLoading();
                if (error.code === 'auth/popup-closed-by-user') {{
                    showError('Login cancelled');
                }} else if (error.code === 'auth/popup-blocked') {{
                    showError('Popup blocked. Please allow popups for this site.');
                }} else {{
                    showError(error.message || 'Login failed');
                }}
            }}
        }}

        async function signInWithMicrosoft() {{
            showLoading();
            try {{
                const provider = new firebase.auth.OAuthProvider('microsoft.com');
                provider.setCustomParameters({{
                    tenant: 'common'  // Allows both personal and work accounts
                }});

                // Request Microsoft Graph API scopes for email and calendar
                provider.addScope('https://graph.microsoft.com/Mail.Read');
                provider.addScope('https://graph.microsoft.com/Mail.Send');
                provider.addScope('https://graph.microsoft.com/Mail.ReadWrite');
                provider.addScope('https://graph.microsoft.com/User.Read');
                provider.addScope('https://graph.microsoft.com/Calendars.Read');
                provider.addScope('https://graph.microsoft.com/Calendars.ReadWrite');

                const result = await auth.signInWithPopup(provider);

                // Extract Microsoft Graph access token
                const credential = result.credential;
                const graphToken = credential ? credential.accessToken : null;

                await sendTokenToServer(result.user, graphToken, 'microsoft.com');
            }} catch (error) {{
                console.error('Microsoft sign-in error:', error);
                hideLoading();
                if (error.code === 'auth/popup-closed-by-user') {{
                    showError('Login cancelled');
                }} else if (error.code === 'auth/popup-blocked') {{
                    showError('Popup blocked. Please allow popups for this site.');
                }} else if (error.message && error.message.includes('consent_required')) {{
                    showError('Login cancelled - permissions not granted');
                }} else if (error.message && error.message.includes('User declined')) {{
                    showError('Login cancelled');
                }} else if (error.message && error.message.includes('access_denied')) {{
                    showError('Access denied');
                }} else if (error.code === 'auth/account-exists-with-different-credential') {{
                    showError('An account already exists with this email using a different sign-in method');
                }} else {{
                    showError('Microsoft login failed. Please try again.');
                }}
            }}
        }}

        async function signInWithEmail() {{
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;

            if (!email || !password) {{
                showError('Please enter email and password');
                return;
            }}

            showLoading();
            try {{
                const result = await auth.signInWithEmailAndPassword(email, password);
                await sendTokenToServer(result.user);
            }} catch (error) {{
                console.error('Email sign-in error:', error);
                hideLoading();
                if (error.code === 'auth/user-not-found') {{
                    showError('No account found with this email');
                }} else if (error.code === 'auth/wrong-password') {{
                    showError('Incorrect password');
                }} else if (error.code === 'auth/invalid-email') {{
                    showError('Invalid email address');
                }} else {{
                    showError(error.message || 'Login failed');
                }}
            }}
        }}

        // Allow Enter key to submit email form
        document.getElementById('password').addEventListener('keypress', function(e) {{
            if (e.key === 'Enter') signInWithEmail();
        }});
    </script>
</body>
</html>"""


class AuthCallbackServer:
    """Local HTTP server for OAuth callback."""

    def __init__(self, port: int = 9876):
        """Initialize server.

        Args:
            port: Port to listen on
        """
        self.port = port
        self.server = None

    def start_and_wait(self, timeout: int = 300) -> Optional[dict]:
        """Start server and wait for credentials.

        Args:
            timeout: Max seconds to wait for login

        Returns:
            Credentials dict or None if timeout/error
        """
        # Reset shared state
        AuthCallbackHandler.received_credentials = None
        AuthCallbackHandler.server_should_stop = False

        # Create server
        try:
            self.server = HTTPServer(("127.0.0.1", self.port), AuthCallbackHandler)
            self.server.timeout = 1  # Check stop flag every second
        except OSError as e:
            logger.error(f"Failed to start server on port {self.port}: {e}")
            return None

        logger.info(f"Auth server started on port {self.port}")

        # Wait for callback or timeout
        import time
        import select
        start_time = time.time()

        try:
            while not AuthCallbackHandler.server_should_stop:
                # Use select for non-blocking check
                ready, _, _ = select.select([self.server.socket], [], [], 0.5)
                if ready:
                    self.server.handle_request()

                # Check timeout
                if time.time() - start_time > timeout:
                    logger.warning("Auth timeout")
                    return None

            # Handle the /success page request before closing
            # Browser redirects to /success after callback POST
            ready, _, _ = select.select([self.server.socket], [], [], 2.0)
            if ready:
                self.server.handle_request()  # Serve /success page

            return AuthCallbackHandler.received_credentials

        except Exception as e:
            logger.exception(f"Server error: {e}")
            return None

        finally:
            self.server.server_close()
            logger.info("Auth server stopped")
