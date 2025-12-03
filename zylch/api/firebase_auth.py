"""Firebase Authentication utilities for validating JWT tokens."""

import logging
from typing import Optional
from fastapi import HTTPException, Header
import firebase_admin
from firebase_admin import credentials, auth
from zylch.config import settings

logger = logging.getLogger(__name__)

# Global Firebase app instance
_firebase_app: Optional[firebase_admin.App] = None


def initialize_firebase():
    """Initialize Firebase Admin SDK.

    This should be called once at application startup.
    Uses service account credentials from environment config.
    """
    global _firebase_app

    if _firebase_app is not None:
        logger.info("Firebase already initialized")
        return _firebase_app

    try:
        # Check if service account path is configured
        if not settings.firebase_service_account_path:
            logger.warning("Firebase service account path not configured")
            return None

        # Initialize Firebase Admin SDK with service account
        cred = credentials.Certificate(settings.firebase_service_account_path)
        _firebase_app = firebase_admin.initialize_app(cred)

        logger.info("Firebase Admin SDK initialized successfully")
        return _firebase_app

    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        return None


def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token and return the decoded user data.

    Args:
        token: Firebase ID token from client

    Returns:
        dict: Decoded token with user information (uid, email, etc.)

    Raises:
        HTTPException: 401 if token is invalid or expired
    """
    if not _firebase_app:
        logger.error("Firebase not initialized - cannot verify token")
        raise HTTPException(
            status_code=500,
            detail="Firebase authentication not configured"
        )

    try:
        # Verify the ID token and decode it
        decoded_token = auth.verify_id_token(token)

        logger.info(f"Token verified for user: {decoded_token.get('uid')}")
        return decoded_token

    except auth.InvalidIdTokenError as e:
        logger.warning(f"Invalid Firebase token: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )
    except auth.ExpiredIdTokenError as e:
        logger.warning(f"Expired Firebase token: {e}")
        raise HTTPException(
            status_code=401,
            detail="Authentication token expired - please log in again"
        )
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        raise HTTPException(
            status_code=401,
            detail="Authentication failed"
        )


async def get_current_user(authorization: str = Header(...)) -> dict:
    """FastAPI dependency to get current authenticated user from Firebase token.

    Usage in route:
        @router.get("/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            user_id = user["uid"]
            user_email = user.get("email")
            ...

    Args:
        authorization: Authorization header with Bearer token (e.g., "Bearer <token>")

    Returns:
        dict: Decoded Firebase token with user data

    Raises:
        HTTPException: 401 if authentication fails
    """
    # Strip "Bearer " prefix if present
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    return verify_firebase_token(token)


def get_user_id_from_token(user_data: dict) -> str:
    """Extract user ID from decoded Firebase token.

    Args:
        user_data: Decoded Firebase token from verify_firebase_token()

    Returns:
        str: Firebase user ID (uid)
    """
    return user_data.get("uid", "unknown")


def get_user_email_from_token(user_data: dict) -> Optional[str]:
    """Extract user email from decoded Firebase token.

    Args:
        user_data: Decoded Firebase token from verify_firebase_token()

    Returns:
        str: User email or None if not available
    """
    return user_data.get("email")


def create_custom_token(uid: str, claims: Optional[dict] = None) -> str:
    """Create a Firebase custom token for a user.

    This allows server-side authentication without requiring the user
    to sign in through Firebase Auth providers.

    Args:
        uid: Firebase user ID (will be created if doesn't exist)
        claims: Optional additional claims to include in the token

    Returns:
        str: Custom token that can be used with signInWithCustomToken()

    Raises:
        HTTPException: 500 if Firebase not initialized or token creation fails
    """
    if not _firebase_app:
        logger.error("Firebase not initialized - cannot create custom token")
        raise HTTPException(
            status_code=500,
            detail="Firebase authentication not configured"
        )

    try:
        # Create custom token
        custom_token = auth.create_custom_token(uid, claims)
        logger.info(f"Created custom token for user: {uid}")
        return custom_token.decode('utf-8') if isinstance(custom_token, bytes) else custom_token

    except Exception as e:
        logger.error(f"Error creating custom token: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create authentication token: {str(e)}"
        )


def get_or_create_user(email: str, display_name: Optional[str] = None) -> str:
    """Get existing Firebase user by email or create new one.

    Args:
        email: User email address
        display_name: Optional display name for new users

    Returns:
        str: Firebase user ID (uid)

    Raises:
        HTTPException: 500 if Firebase not initialized or operation fails
    """
    if not _firebase_app:
        logger.error("Firebase not initialized - cannot get/create user")
        raise HTTPException(
            status_code=500,
            detail="Firebase authentication not configured"
        )

    try:
        # Try to get existing user by email
        try:
            user = auth.get_user_by_email(email)
            logger.info(f"Found existing Firebase user: {user.uid} ({email})")
            return user.uid
        except auth.UserNotFoundError:
            # User doesn't exist, create new one
            user = auth.create_user(
                email=email,
                display_name=display_name or email.split('@')[0],
                email_verified=True  # Trust Microsoft verification
            )
            logger.info(f"Created new Firebase user: {user.uid} ({email})")
            return user.uid

    except Exception as e:
        logger.error(f"Error getting/creating user: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get or create user: {str(e)}"
        )
