"""Auth API routes for session management with Firebase authentication.

These endpoints provide session token management on top of Firebase authentication:
- Login: Exchange Firebase ID token for session info
- Refresh: Validate and extend session
- Logout: Invalidate session

For Phase 1, these endpoints provide the structure for future thin client migration.
Currently they work alongside Firebase auth (validate Firebase token + return session info).
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token
from zylch.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# Request/Response Models

class LoginRequest(BaseModel):
    """Request to create session from Firebase token."""

    firebase_token: str = Field(
        ...,
        description="Firebase ID token from client authentication"
    )
    graph_token: Optional[str] = Field(
        None,
        description="Microsoft Graph API access token (for microsoft.com provider)"
    )


class LoginResponse(BaseModel):
    """Response with session information."""

    success: bool = Field(description="Whether login succeeded")
    token: str = Field(description="Session token (currently same as Firebase token)")
    owner_id: str = Field(description="Firebase UID / owner_id")
    email: Optional[str] = Field(None, description="User email from Firebase")
    display_name: Optional[str] = Field(None, description="User display name from Firebase")
    provider: Optional[str] = Field(None, description="Auth provider (google.com, microsoft.com)")
    expires_at: str = Field(description="ISO 8601 timestamp when token expires")


class RefreshResponse(BaseModel):
    """Response with refreshed session information."""

    success: bool = Field(description="Whether refresh succeeded")
    token: str = Field(description="Refreshed session token")
    expires_at: str = Field(description="ISO 8601 timestamp when token expires")


class LogoutResponse(BaseModel):
    """Response confirming logout."""

    success: bool = Field(description="Whether logout succeeded")
    message: str = Field(description="Confirmation message")


# Auth Endpoints

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Create session from Firebase ID token.

    This endpoint validates a Firebase ID token and returns session information.
    For Phase 1, this is primarily informational - the Firebase token itself
    is used for authentication in subsequent requests.

    In future phases (thin client), this will:
    - Create server-side session
    - Return short-lived session token
    - Enable stateful session management

    **Request Body:**
    - firebase_token: Firebase ID token from client authentication

    **Response:**
    - token: Session token (currently same as Firebase token)
    - owner_id: Firebase UID for multi-tenant isolation
    - email: User email from Firebase auth
    - display_name: User display name
    - provider: Auth provider (google.com, microsoft.com)
    - expires_at: Token expiration timestamp

    **No authentication required** - this endpoint creates the session
    """
    try:
        # Validate Firebase token by using it with get_current_user
        # This is a bit hacky but works for Phase 1
        from firebase_admin import auth as firebase_auth

        try:
            # Verify Firebase token
            decoded_token = firebase_auth.verify_id_token(request.firebase_token)

            owner_id = decoded_token.get('uid')
            email = decoded_token.get('email')
            display_name = decoded_token.get('name')

            # Extract provider from firebase data
            provider_data = decoded_token.get('firebase', {}).get('sign_in_provider', 'google.com')

            # Calculate expiration (Firebase tokens expire in 1 hour)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

            logger.info(f"User logged in: {owner_id} ({email})")
            logger.info(f"Provider: {provider_data}, graph_token present: {request.graph_token is not None}")

            # Save user tokens to file storage
            from zylch.api.token_storage import save_provider, save_email, save_graph_token

            save_provider(owner_id, provider_data)
            save_email(owner_id, email)

            # Save Microsoft Graph token if provided
            if request.graph_token and provider_data == "microsoft.com":
                save_graph_token(owner_id, request.graph_token, expires_at.isoformat())
                logger.info(f"Saved Microsoft Graph token for owner {owner_id}")
            else:
                logger.warning(f"Graph token NOT saved - graph_token: {request.graph_token is not None}, provider: {provider_data}")

            return LoginResponse(
                success=True,
                token=request.firebase_token,  # Phase 1: return same token
                owner_id=owner_id,
                email=email,
                display_name=display_name,
                provider=provider_data,
                expires_at=expires_at.isoformat()
            )

        except firebase_auth.InvalidIdTokenError:
            raise HTTPException(
                status_code=401,
                detail="Invalid Firebase token"
            )
        except firebase_auth.ExpiredIdTokenError:
            raise HTTPException(
                status_code=401,
                detail="Firebase token expired"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Login failed: {str(e)}"
        )


class MicrosoftLoginRequest(BaseModel):
    """Request model for Microsoft login."""
    graph_token: str = Field(..., description="Microsoft Graph access token from MSAL")


@router.post("/microsoft-login")
async def microsoft_login(request: MicrosoftLoginRequest):
    """Exchange Microsoft Graph token for Firebase custom token.

    This endpoint:
    1. Verifies the Microsoft Graph token by calling Microsoft Graph API
    2. Extracts user email and name
    3. Creates or gets Firebase user
    4. Generates Firebase custom token
    5. Saves the Microsoft Graph token for later use

    Args:
        graph_token: Microsoft Graph access token from MSAL

    Returns:
        {
            "firebase_token": "custom_token_here",
            "owner_id": "firebase_uid",
            "email": "user@example.com"
        }
    """
    import httpx
    from zylch.api.firebase_auth import get_or_create_user, create_custom_token
    from zylch.api.token_storage import save_provider, save_email, save_graph_token

    try:
        # Verify Microsoft Graph token by calling /me endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {request.graph_token}"}
            )

            if response.status_code != 200:
                logger.error(f"Microsoft Graph API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=401,
                    detail="Invalid Microsoft Graph token"
                )

            user_info = response.json()
            email = user_info.get("mail") or user_info.get("userPrincipalName")
            display_name = user_info.get("displayName")

            if not email:
                raise HTTPException(
                    status_code=400,
                    detail="Could not extract email from Microsoft account"
                )

        logger.info(f"Microsoft user authenticated: {email}")

        # Get or create Firebase user
        uid = get_or_create_user(email, display_name)

        # Create Firebase custom token
        firebase_token = create_custom_token(uid, {"provider": "microsoft.com"})

        # Save Microsoft Graph token for future API calls
        save_provider(uid, "microsoft.com")
        save_email(uid, email)
        save_graph_token(uid, request.graph_token)

        logger.info(f"Created Firebase custom token for Microsoft user: {uid}")

        return {
            "firebase_token": firebase_token,
            "owner_id": uid,
            "email": email,
            "display_name": display_name
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during Microsoft login: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Microsoft login failed: {str(e)}"
        )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(user: dict = Depends(get_current_user)):
    """Refresh session token.

    This endpoint validates the current session and returns refreshed token info.
    For Phase 1, this validates the Firebase token and returns expiration info.

    In future phases (thin client), this will:
    - Validate current session token
    - Issue new short-lived session token
    - Enable seamless token rotation

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Response:**
    - token: Refreshed session token
    - expires_at: Token expiration timestamp
    """
    try:
        # Extract owner_id (this validates the token)
        owner_id = get_user_id_from_token(user)

        # Calculate new expiration
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        logger.info(f"Token refreshed for user {owner_id}")

        return RefreshResponse(
            success=True,
            token=user.get('token', ''),  # Return same token for Phase 1
            expires_at=expires_at.isoformat()
        )

    except Exception as e:
        logger.error(f"Error refreshing token: {e}", exc_info=True)
        raise HTTPException(
            status_code=401,
            detail="Token refresh failed"
        )


@router.post("/logout", response_model=LogoutResponse)
async def logout(user: dict = Depends(get_current_user)):
    """Logout and invalidate session.

    This endpoint logs out the user and invalidates their session.
    For Phase 1, this is informational - the client should discard the token.

    In future phases (thin client), this will:
    - Invalidate server-side session
    - Revoke session token
    - Clear any cached data

    **Authentication:**
    - Requires Firebase ID token in 'auth' header

    **Response:**
    - success: Whether logout succeeded
    - message: Confirmation message
    """
    try:
        # Extract owner_id (this validates the token)
        owner_id = get_user_id_from_token(user)

        logger.info(f"User logged out: {owner_id}")

        # Phase 1: No server-side session to invalidate
        # Client should discard token
        # Future: Invalidate session in session store

        return LogoutResponse(
            success=True,
            message="Logout successful - client should discard token"
        )

    except Exception as e:
        logger.error(f"Error during logout: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Logout failed: {str(e)}"
        )


@router.get("/session")
async def get_session_info(user: dict = Depends(get_current_user)):
    """Get current session information.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Response:**
    - user: User object with uid, email, display_name, provider
    - authenticated: Whether user is authenticated
    """
    try:
        # Extract user info
        owner_id = get_user_id_from_token(user)
        email = user.get('email')
        provider = user.get('firebase', {}).get('sign_in_provider', 'unknown')

        return {
            "success": True,
            "authenticated": True,
            "user": {
                "uid": owner_id,
                "id": owner_id,
                "email": email,
                "display_name": user.get('name', email.split('@')[0] if email else 'User'),
                "name": user.get('name', email.split('@')[0] if email else 'User'),
                "provider": provider
            }
        }

    except Exception as e:
        logger.error(f"Error getting session info: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting session info: {str(e)}"
        )


@router.get("/check-allowlist")
async def check_allowlist(email: str):
    """Check if an email is in the alpha testers allowlist.

    **Query Parameters:**
    - email: Email address to check

    **Response:**
    - allowed: Boolean indicating if email is in allowlist
    - message: Human-readable status message
    """
    is_allowed = settings.is_alpha_tester(email)

    if is_allowed:
        return {
            "allowed": True,
            "message": "Email is in alpha testers list"
        }
    else:
        return {
            "allowed": False,
            "message": "Email is not in alpha testers list"
        }


@router.get("/oauth/initiate", response_class=HTMLResponse)
async def oauth_initiate(callback_url: str, request: Request):
    """Initiate browser-based OAuth flow.

    This endpoint returns an HTML page with Firebase authentication.
    After successful sign-in, the page redirects to the callback_url with the token.

    **Query Parameters:**
    - callback_url: URL to redirect to after authentication (e.g., http://localhost:8765/callback)

    **Response:**
    - HTML page with Firebase sign-in UI

    **Flow:**
    1. User opens this endpoint in browser
    2. User signs in with Firebase (Google, Microsoft, etc.)
    3. JavaScript captures Firebase ID token
    4. Page redirects to callback_url?token=...&owner_id=...&email=...
    5. CLI captures token from callback

    **No authentication required** - this initiates the authentication flow
    """
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Zylch - Sign In</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}

            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #ffffff;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}

            .logo {{
                margin-bottom: 32px;
            }}

            .logo img {{
                height: 48px;
            }}

            .tagline {{
                color: #6b7280;
                font-size: 18px;
                margin-bottom: 32px;
            }}

            .container {{
                background: white;
                border-radius: 12px;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                max-width: 448px;
                width: 100%;
                padding: 32px;
            }}

            h1 {{
                font-size: 24px;
                font-weight: 600;
                color: #111827;
                text-align: center;
                margin-bottom: 24px;
            }}

            .button-group {{
                display: flex;
                flex-direction: column;
                gap: 16px;
            }}

            button {{
                width: 100%;
                padding: 12px 16px;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                background: white;
                font-size: 16px;
                font-weight: 500;
                color: #374151;
                cursor: pointer;
                transition: background-color 0.15s, border-color 0.15s;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 12px;
            }}

            button:hover {{
                background: #f9fafb;
                border-color: #d1d5db;
            }}

            button:disabled {{
                opacity: 0.5;
                cursor: not-allowed;
            }}

            .privacy-note {{
                margin-top: 24px;
                text-align: center;
                font-size: 14px;
                color: #6b7280;
            }}

            .privacy-note a {{
                color: #2563eb;
                text-decoration: none;
            }}

            .privacy-note a:hover {{
                text-decoration: underline;
            }}

            .status {{
                margin-top: 16px;
                padding: 12px;
                border-radius: 8px;
                font-size: 14px;
                display: none;
                text-align: center;
            }}

            .status.loading {{
                display: block;
                background: #eff6ff;
                color: #1d4ed8;
                border: 1px solid #bfdbfe;
            }}

            .status.success {{
                display: block;
                background: #f0fdf4;
                color: #166534;
                border: 1px solid #bbf7d0;
            }}

            .status.error {{
                display: block;
                background: #fef2f2;
                color: #991b1b;
                border: 1px solid #fecaca;
            }}

            .footer {{
                margin-top: 32px;
                font-size: 14px;
                color: #6b7280;
            }}

            .footer a {{
                color: #6b7280;
                text-decoration: none;
            }}

            .footer a:hover {{
                color: #111827;
            }}

            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
        </style>

        <!-- Firebase SDK -->
        <script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-auth-compat.js"></script>

        <!-- MSAL.js for Microsoft Graph token acquisition -->
        <script src="https://alcdn.msauth.net/browser/2.38.1/js/msal-browser.min.js"></script>
    </head>
    <body>
        <!-- Logo -->
        <div class="logo">
            <svg viewBox="0 0 350 100" width="175" height="50" xmlns="http://www.w3.org/2000/svg">
                <!-- Z Mark -->
                <path
                    d="M 15 25
                       C 35 24, 65 23, 85 22
                       C 65 40, 35 60, 15 78
                       C 35 77, 65 76, 85 75"
                    stroke="#1a1a1a"
                    stroke-width="7"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    fill="none"
                />
                <!-- "ylch" text -->
                <text x="95" y="72" font-family="Inter, Arial, sans-serif" font-size="64" font-weight="400" fill="#1a1a1a">ylch</text>
            </svg>
        </div>

        <!-- Tagline -->
        <p class="tagline">Your AI assistant for business communication</p>

        <!-- Login Card -->
        <div class="container">
            <h1>Sign in to Zylch</h1>

            <div class="button-group">
                <button id="google-signin">
                    <svg width="20" height="20" viewBox="0 0 24 24">
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                    </svg>
                    Continue with Google
                </button>

                <button id="microsoft-signin">
                    <svg width="20" height="20" viewBox="0 0 24 24">
                        <path fill="#F25022" d="M1 1h10v10H1z"/>
                        <path fill="#00A4EF" d="M1 13h10v10H1z"/>
                        <path fill="#7FBA00" d="M13 1h10v10H13z"/>
                        <path fill="#FFB900" d="M13 13h10v10H13z"/>
                    </svg>
                    Continue with Microsoft
                </button>
            </div>

            <p class="privacy-note">
                By signing in, you agree to our
                <a href="/privacy">Privacy Policy</a>
                and
                <a href="/terms">Terms of Service</a>
            </p>

            <div id="status" class="status"></div>
        </div>

        <!-- Footer -->
        <footer class="footer">
            <a href="https://zylch.ai">Learn more about Zylch</a>
        </footer>

        <script>
            // Firebase configuration
            const firebaseConfig = {{
                apiKey: "{settings.firebase_api_key}",
                authDomain: "{settings.firebase_auth_domain}",
                projectId: "{settings.firebase_project_id}"
            }};

            // Initialize Firebase
            firebase.initializeApp(firebaseConfig);
            const auth = firebase.auth();

            // MSAL configuration for Microsoft Graph token acquisition
            const msalConfig = {{
                auth: {{
                    clientId: "6e5e2530-f3f6-4b10-b26a-eb6c4028c4ee",
                    authority: "https://login.microsoftonline.com/common",
                    redirectUri: window.location.origin + "/api/auth/oauth/initiate"
                }},
                cache: {{
                    cacheLocation: "localStorage",
                    storeAuthStateInCookie: false
                }}
            }};

            const msalInstance = new msal.PublicClientApplication(msalConfig);

            // Callback URL from query parameter
            const callbackUrl = "{callback_url}";

            // Status message helper
            function showStatus(message, type) {{
                const status = document.getElementById('status');
                status.textContent = message;
                status.className = 'status ' + type;
            }}

            // Handle authentication result
            async function handleAuthResult(user, credential) {{
                showStatus('✓ Signed in successfully! Getting Microsoft Graph token...', 'success');

                try {{
                    // Get Firebase ID token
                    const token = await user.getIdToken();
                    const email = user.email;
                    const uid = user.uid;

                    // Try to get Microsoft Graph token using MSAL (silent acquisition)
                    let graphToken = null;

                    // First, check if Firebase gave us the token (unlikely for Microsoft)
                    if (credential && credential.accessToken) {{
                        graphToken = credential.accessToken;
                        console.log('Got Graph token from Firebase credential');
                    }} else {{
                        // Use MSAL to silently acquire Microsoft Graph token
                        console.log('Firebase did not provide token, using MSAL...');
                        try {{
                            const silentRequest = {{
                                scopes: [
                                    "https://graph.microsoft.com/Mail.Read",
                                    "https://graph.microsoft.com/Mail.Send",
                                    "https://graph.microsoft.com/Mail.ReadWrite",
                                    "https://graph.microsoft.com/Calendars.Read",
                                    "https://graph.microsoft.com/Calendars.ReadWrite",
                                    "https://graph.microsoft.com/User.Read"
                                ],
                                loginHint: email  // Use email as login hint for silent auth
                            }};

                            const msalResponse = await msalInstance.acquireTokenSilent(silentRequest);
                            graphToken = msalResponse.accessToken;
                            console.log('Got Graph token from MSAL silent acquisition');
                        }} catch (msalError) {{
                            console.error('MSAL silent acquisition failed:', msalError);
                            // Fallback: try interactive acquisition
                            try {{
                                const interactiveRequest = {{
                                    scopes: silentRequest.scopes,
                                    loginHint: email
                                }};
                                const msalResponse = await msalInstance.acquireTokenPopup(interactiveRequest);
                                graphToken = msalResponse.accessToken;
                                console.log('Got Graph token from MSAL interactive acquisition');
                            }} catch (interactiveError) {{
                                console.error('MSAL interactive acquisition failed:', interactiveError);
                            }}
                        }}
                    }}

                    console.log('Graph token to send:', graphToken ? 'PRESENT' : 'NULL');

                    // Call /api/auth/login to save tokens server-side
                    const loginResponse = await fetch('/api/auth/login', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            firebase_token: token,
                            graph_token: graphToken
                        }})
                    }});

                    if (!loginResponse.ok) {{
                        throw new Error('Login failed: ' + loginResponse.statusText);
                    }}

                    // Get callback URL (from sessionStorage if redirect, or from query param if popup)
                    const savedCallbackUrl = sessionStorage.getItem('zylch_callback_url') || callbackUrl;
                    sessionStorage.removeItem('zylch_callback_url');  // Clean up

                    // Check alpha tester allowlist
                    const checkResponse = await fetch('/api/auth/check-allowlist?email=' + encodeURIComponent(email));
                    const allowlistData = await checkResponse.json();
                    const isAllowed = allowlistData.allowed;

                    // Build callback URL with token
                    const params = new URLSearchParams({{
                        token: token,
                        owner_id: uid,
                        email: email,
                        allowed: isAllowed ? 'true' : 'false'
                    }});

                    const redirectUrl = savedCallbackUrl + '?' + params.toString();

                    // Redirect to CLI callback
                    setTimeout(() => {{
                        window.location.href = redirectUrl;
                    }}, 1000);

                }} catch (error) {{
                    showStatus('Error: ' + error.message, 'error');
                }}
            }}

            // Google Sign-In
            document.getElementById('google-signin').addEventListener('click', async () => {{
                showStatus('Signing in with Google...', 'loading');

                const provider = new firebase.auth.GoogleAuthProvider();
                provider.addScope('email');
                provider.addScope('profile');

                try {{
                    const result = await auth.signInWithPopup(provider);
                    // Extract credential from result
                    const credential = firebase.auth.GoogleAuthProvider.credentialFromResult(result);
                    await handleAuthResult(result.user, credential);
                }} catch (error) {{
                    console.error('Google sign-in error:', error);
                    showStatus('Error: ' + error.message, 'error');
                }}
            }});

            // Microsoft Sign-In (MSAL direct + Firebase custom token)
            document.getElementById('microsoft-signin').addEventListener('click', async () => {{
                showStatus('Signing in with Microsoft...', 'loading');

                try {{
                    // Use MSAL to get Microsoft Graph token
                    const loginRequest = {{
                        scopes: [
                            "https://graph.microsoft.com/Mail.Read",
                            "https://graph.microsoft.com/Mail.Send",
                            "https://graph.microsoft.com/Mail.ReadWrite",
                            "https://graph.microsoft.com/Calendars.Read",
                            "https://graph.microsoft.com/Calendars.ReadWrite",
                            "https://graph.microsoft.com/User.Read"
                        ],
                        prompt: 'select_account'
                    }};

                    showStatus('Authenticating with Microsoft...', 'loading');
                    const msalResponse = await msalInstance.loginPopup(loginRequest);
                    const graphToken = msalResponse.accessToken;

                    console.log('Got Microsoft Graph token from MSAL');

                    // Exchange Microsoft Graph token for Firebase custom token
                    showStatus('Creating session...', 'loading');
                    const response = await fetch('/api/auth/microsoft-login', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ graph_token: graphToken }})
                    }});

                    if (!response.ok) {{
                        throw new Error('Failed to create Firebase session: ' + response.statusText);
                    }}

                    const data = await response.json();
                    console.log('Got Firebase custom token');

                    // Sign in to Firebase with custom token
                    showStatus('Signing in to Firebase...', 'loading');
                    const userCredential = await auth.signInWithCustomToken(data.firebase_token);
                    const firebaseToken = await userCredential.user.getIdToken();

                    console.log('Signed in to Firebase successfully');

                    // Check alpha tester allowlist
                    const checkResponse = await fetch('/api/auth/check-allowlist?email=' + encodeURIComponent(data.email));
                    const allowlistData = await checkResponse.json();
                    const isAllowed = allowlistData.allowed;

                    // Redirect to CLI callback
                    const params = new URLSearchParams({{
                        token: firebaseToken,
                        owner_id: data.owner_id,
                        email: data.email,
                        allowed: isAllowed ? 'true' : 'false'
                    }});

                    const redirectUrl = callbackUrl + '?' + params.toString();

                    showStatus('✓ Success! Redirecting...', 'success');
                    setTimeout(() => {{
                        window.location.href = redirectUrl;
                    }}, 1000);

                }} catch (error) {{
                    console.error('Microsoft sign-in error:', error);
                    showStatus('Error: ' + error.message, 'error');
                }}
            }});

            // Check for redirect result on page load
            console.log('Checking for redirect result...');
            auth.getRedirectResult().then(async (result) => {{
                console.log('getRedirectResult returned:', result);
                if (result.user) {{
                    console.log('Redirect result received:', result.user.email);
                    showStatus('Processing sign-in...', 'loading');
                    // Extract credential from redirect result
                    const credential = firebase.auth.OAuthProvider.credentialFromResult(result);
                    console.log('Credential from redirect:', credential);
                    console.log('Access token:', credential ? credential.accessToken : 'NO CREDENTIAL');
                    await handleAuthResult(result.user, credential);
                }} else {{
                    console.log('No redirect result (normal page load)');
                }}
            }}).catch((error) => {{
                console.error('Redirect result error:', error);
                showStatus('Error: ' + error.message, 'error');
            }});

            // Check if already signed in
            auth.onAuthStateChanged(async (user) => {{
                if (user) {{
                    console.log('Already signed in:', user.email);
                    // Don't auto-redirect - wait for redirect result to handle credential
                }}
            }});
        </script>
    </body>
    </html>
    """

    return HTMLResponse(content=html_content)


# =============================================================================
# Google OAuth Server-Side Flow (for Gmail/Calendar API access)
# =============================================================================

# Google OAuth scopes for Gmail + Calendar
GOOGLE_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
]

# In-memory state storage (use Redis in production for multi-instance)
_oauth_states: dict = {}


@router.get("/google/authorize")
async def google_oauth_authorize(user: dict = Depends(get_current_user)):
    """Initiate Google OAuth flow for Gmail/Calendar API access.

    This endpoint generates a Google OAuth authorization URL with the necessary
    scopes for Gmail and Calendar API access. The user must be authenticated
    with Firebase first.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Response:**
    - auth_url: URL to redirect user to for Google OAuth consent

    **Flow:**
    1. Frontend calls this endpoint with Firebase token
    2. Backend generates OAuth URL with state parameter
    3. Frontend redirects user to auth_url
    4. User grants permissions on Google consent screen
    5. Google redirects to /api/auth/google/callback with code
    6. Backend exchanges code for tokens and stores in Supabase
    """
    import secrets
    from urllib.parse import urlencode

    owner_id = get_user_id_from_token(user)
    user_email = user.get('email', '')

    # Check if Google OAuth is configured
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )

    # Generate state parameter for CSRF protection
    state = secrets.token_urlsafe(32)

    # Store state with user info (expires in 10 minutes)
    _oauth_states[state] = {
        'owner_id': owner_id,
        'email': user_email,
        'created_at': datetime.now(timezone.utc).isoformat()
    }

    # Build authorization URL
    redirect_uri = settings.google_oauth_redirect_uri
    if not redirect_uri:
        # Default to API server URL + callback path
        redirect_uri = f"{settings.api_server_url}/api/auth/google/callback"

    params = {
        'client_id': settings.google_client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(GOOGLE_SCOPES),
        'access_type': 'offline',  # Get refresh token
        'prompt': 'consent',  # Force consent to get refresh token
        'state': state,
        'login_hint': user_email,  # Pre-fill email
    }

    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    logger.info(f"Generated Google OAuth URL for user {owner_id}")

    return {
        "auth_url": auth_url,
        "state": state
    }


@router.get("/google/callback")
async def google_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None
):
    """Handle Google OAuth callback.

    This endpoint receives the authorization code from Google after user
    grants permissions. It exchanges the code for tokens and stores them
    in Supabase.

    **Query Parameters:**
    - code: Authorization code from Google
    - state: State parameter for CSRF validation
    - error: Error message if authorization failed

    **Response:**
    - HTML page that closes the popup and notifies parent window
    """
    import httpx

    # Handle errors
    if error:
        logger.error(f"Google OAuth error: {error}")
        return HTMLResponse(content=_oauth_error_page(f"Google OAuth failed: {error}"))

    if not code or not state:
        return HTMLResponse(content=_oauth_error_page("Missing code or state parameter"))

    # Validate state
    if state not in _oauth_states:
        logger.error(f"Invalid OAuth state: {state}")
        return HTMLResponse(content=_oauth_error_page("Invalid or expired state. Please try again."))

    state_data = _oauth_states.pop(state)
    owner_id = state_data['owner_id']
    user_email = state_data['email']

    # Check if state is expired (10 minutes)
    created_at = datetime.fromisoformat(state_data['created_at'])
    if datetime.now(timezone.utc) - created_at > timedelta(minutes=10):
        logger.error(f"Expired OAuth state for user {owner_id}")
        return HTMLResponse(content=_oauth_error_page("OAuth session expired. Please try again."))

    # Exchange code for tokens
    redirect_uri = settings.google_oauth_redirect_uri
    if not redirect_uri:
        redirect_uri = f"{settings.api_server_url}/api/auth/google/callback"

    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        'client_id': settings.google_client_id,
        'client_secret': settings.google_client_secret,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': redirect_uri,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=token_data)

            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                return HTMLResponse(content=_oauth_error_page(f"Failed to exchange code for tokens: {response.text}"))

            tokens = response.json()

        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        expires_in = tokens.get('expires_in', 3600)

        if not access_token:
            return HTMLResponse(content=_oauth_error_page("No access token received from Google"))

        # Create Google Credentials object
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=GOOGLE_SCOPES
        )

        # Save credentials using token_storage (saves to Supabase if configured)
        from zylch.api.token_storage import save_google_credentials, save_provider, save_email

        save_provider(owner_id, "google.com", user_email)
        save_email(owner_id, user_email)
        save_google_credentials(owner_id, creds, user_email)

        logger.info(f"Saved Google OAuth credentials for user {owner_id}")

        # Return success page that closes popup
        return HTMLResponse(content=_oauth_success_page())

    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}", exc_info=True)
        return HTMLResponse(content=_oauth_error_page(f"Error processing OAuth callback: {str(e)}"))


@router.get("/google/status")
async def google_oauth_status(user: dict = Depends(get_current_user)):
    """Check if user has valid Google OAuth credentials.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Response:**
    - has_credentials: Whether user has Google credentials
    - email: User's email
    - scopes: List of authorized scopes (if credentials exist)
    """
    from zylch.api.token_storage import has_google_credentials, get_google_credentials, get_email

    owner_id = get_user_id_from_token(user)

    has_creds = has_google_credentials(owner_id)
    email = get_email(owner_id)

    response = {
        "has_credentials": has_creds,
        "email": email,
        "owner_id": owner_id
    }

    if has_creds:
        creds = get_google_credentials(owner_id)
        if creds:
            response["scopes"] = list(creds.scopes) if creds.scopes else GOOGLE_SCOPES
            response["valid"] = creds.valid
            response["expired"] = creds.expired

    return response


@router.post("/google/revoke")
async def google_oauth_revoke(user: dict = Depends(get_current_user)):
    """Revoke Google OAuth credentials.

    **Authentication:**
    - Requires Firebase ID token in Authorization header

    **Response:**
    - success: Whether revocation succeeded
    """
    import httpx
    from zylch.api.token_storage import get_google_credentials, delete_user_credentials

    owner_id = get_user_id_from_token(user)

    creds = get_google_credentials(owner_id)
    if creds and creds.token:
        # Revoke token with Google
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://oauth2.googleapis.com/revoke?token={creds.token}"
                )
        except Exception as e:
            logger.warning(f"Failed to revoke Google token: {e}")

    # Delete local credentials
    delete_user_credentials(owner_id)

    logger.info(f"Revoked Google credentials for user {owner_id}")

    return {"success": True, "message": "Google credentials revoked"}


def _oauth_success_page() -> str:
    """Generate HTML page for successful OAuth completion."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authorization Successful</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background: #f9fafb;
            }
            .container {
                text-align: center;
                padding: 40px;
                background: white;
                border-radius: 12px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }
            .success-icon {
                font-size: 64px;
                margin-bottom: 20px;
            }
            h1 {
                color: #166534;
                margin-bottom: 10px;
            }
            p {
                color: #6b7280;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success-icon">✓</div>
            <h1>Authorization Successful!</h1>
            <p>Your Google account has been connected.</p>
            <p>You can close this window and return to Zylch.</p>
        </div>
        <script>
            // Notify parent window if in popup
            if (window.opener) {
                window.opener.postMessage({ type: 'google-oauth-success' }, '*');
                setTimeout(() => window.close(), 2000);
            }
        </script>
    </body>
    </html>
    """


def _oauth_error_page(error_message: str) -> str:
    """Generate HTML page for OAuth error."""
    import html
    safe_message = html.escape(error_message)
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authorization Failed</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background: #f9fafb;
            }}
            .container {{
                text-align: center;
                padding: 40px;
                background: white;
                border-radius: 12px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                max-width: 500px;
            }}
            .error-icon {{
                font-size: 64px;
                margin-bottom: 20px;
            }}
            h1 {{
                color: #991b1b;
                margin-bottom: 10px;
            }}
            p {{
                color: #6b7280;
            }}
            .error-detail {{
                background: #fef2f2;
                color: #991b1b;
                padding: 12px;
                border-radius: 8px;
                margin-top: 16px;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error-icon">✗</div>
            <h1>Authorization Failed</h1>
            <p>We couldn't connect your Google account.</p>
            <div class="error-detail">{safe_message}</div>
            <p style="margin-top: 20px;">Please close this window and try again.</p>
        </div>
        <script>
            // Notify parent window if in popup
            if (window.opener) {{
                window.opener.postMessage({{ type: 'google-oauth-error', error: '{safe_message}' }}, '*');
            }}
        </script>
    </body>
    </html>
    """
