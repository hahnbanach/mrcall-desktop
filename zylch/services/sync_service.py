"""Email and calendar sync service - business logic layer.

Uses IMAPClient for email sync (replaces Gmail/Outlook OAuth).
"""

from typing import Dict, Any, Optional, TYPE_CHECKING
import logging
from datetime import datetime, timedelta, timezone

from zylch.email.imap_client import IMAPClient
from zylch.tools.email_archive import EmailArchiveManager
from zylch.tools.email_sync import EmailSyncManager
from zylch.tools.config import ToolConfig
from zylch.tools.factory import ToolFactory
from zylch.config import settings
from zylch.storage.database import get_session

# Avoid circular imports
if TYPE_CHECKING:
    from zylch.storage import Storage

logger = logging.getLogger(__name__)


class SyncService:
    """Service for syncing emails and calendar events.

    Uses IMAPClient for email access instead of OAuth APIs.
    """

    def __init__(
        self,
        email_client: Optional[IMAPClient] = None,
        email_archive: Optional[
            EmailArchiveManager
        ] = None,
        anthropic_api_key: Optional[str] = None,
        llm_provider: Optional[str] = None,
        owner_id: Optional[str] = None,
        supabase_storage: Optional['Storage'] = None,
    ):
        """Initialize sync service.

        Args:
            email_client: IMAPClient instance
            email_archive: Optional EmailArchiveManager
            anthropic_api_key: LLM API key (BYOK)
            llm_provider: LLM provider name
            owner_id: User ID for multi-tenant storage
            supabase_storage: Storage instance
        """
        self.email_client = email_client
        self.email_archive = email_archive
        self.anthropic_api_key = anthropic_api_key
        self.llm_provider = llm_provider

        self.owner_id = owner_id
        self.supabase = supabase_storage
        self._use_supabase = bool(
            self.supabase and self.owner_id
        )

        logger.debug(
            f"[SyncService] init owner_id={owner_id},"
            f" email_client="
            f"{'present' if email_client else 'absent'}"
        )

    async def _ensure_email_client(self) -> IMAPClient:
        """Ensure email client is initialized.

        Returns:
            Active IMAPClient

        Raises:
            ValueError: If no email client configured
        """
        if not self.email_client:
            raise ValueError(
                "Email client is required for sync."
                " SyncService must be initialized"
                " with email_client parameter."
            )
        return self.email_client

    async def _ensure_email_archive(
        self,
    ) -> EmailArchiveManager:
        """Ensure email archive is initialized.

        Returns:
            Active EmailArchiveManager
        """
        if not self.email_archive:
            email_client = (
                await self._ensure_email_client()
            )
            self.email_archive = EmailArchiveManager(
                gmail_client=email_client,
                owner_id=self.owner_id,
                supabase_storage=self.supabase,
            )
        return self.email_archive

    async def sync_emails(
        self,
        days_back: Optional[int] = None,
        force_full: bool = False,
        on_progress=None,
    ) -> Dict[str, Any]:
        """Sync emails via IMAP into archive.

        This method ONLY fetches emails into archive.
        AI analysis is done separately via /tasks.

        Args:
            days_back: Days to sync (default: 30)
            force_full: Force full sync

        Returns:
            Sync results with stats
        """
        logger.info(
            f"[email_sync] Starting archive sync"
            f" (days_back={days_back},"
            f" force_full={force_full})"
        )

        archive = await self._ensure_email_archive()
        archive_result = archive.incremental_sync(
            days_back=days_back, force_full=force_full,
            on_progress=on_progress,
        )

        if not archive_result["success"]:
            logger.error(
                f"Archive sync failed:"
                f" {archive_result.get('error')}"
            )
            return {
                "success": False,
                "error": (
                    f"Archive sync failed:"
                    f" {archive_result.get('error')}"
                ),
            }

        logger.info(
            f"[email_sync] Complete:"
            f" +{archive_result['messages_added']}"
            f" -{archive_result['messages_deleted']}"
            f" messages"
        )

        return {
            "success": True,
            "new_messages": archive_result[
                "messages_added"
            ],
            "deleted_messages": archive_result[
                "messages_deleted"
            ],
            "incremental": archive_result.get(
                "incremental", False
            ),
            "first_sync_date": archive_result.get(
                "first_sync_date"
            ),
        }

    async def sync_mrcall(
        self,
        days_back: int = 30,
        limit: int = 100,
        debug: bool = False,
        firebase_token: str = None,
        business_id: str = None,
        realm: str = None,
    ) -> Dict[str, Any]:
        """Sync MrCall phone call conversations to DB.

        Args:
            days_back: Days to sync (default: 30)
            limit: Max conversations per request
            debug: Print conversation data to stdout
            firebase_token: MrCall OAuth access token
            business_id: Optional business ID override
            realm: Optional realm override

        Returns:
            Result dict with sync statistics
        """
        import json
        import httpx

        logger.info(
            f"[mrcall_sync] Starting"
            f" (days_back={days_back}, limit={limit})"
        )

        if not self.supabase or not self.owner_id:
            logger.info(
                "[mrcall_sync] Skipping"
                " - no storage/owner_id"
            )
            return {
                "success": True,
                "skipped": True,
                "reason": "No storage configured",
                "synced": 0,
            }

        if not business_id:
            business_id = self.supabase.get_mrcall_link(
                self.owner_id
            )

        if not business_id:
            logger.info(
                "[mrcall_sync] Skipping"
                " - MrCall not linked"
            )
            return {
                "success": True,
                "skipped": True,
                "reason": (
                    "MrCall not linked."
                    " Use /mrcall link first."
                ),
                "synced": 0,
            }

        if not firebase_token:
            logger.error(
                "[mrcall_sync] No access token"
            )
            return {
                "success": False,
                "error": (
                    "MrCall access token required."
                    " Run /connect mrcall."
                ),
                "synced": 0,
            }

        try:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(
                days=days_back
            )

            target_realm = (
                realm
                if realm
                else settings.mrcall_realm
            )

            logger.info(
                f"[mrcall_sync] Using realm:"
                f" '{target_realm}'"
            )
            logger.info(
                f"[mrcall_sync] Auth token len:"
                f" {len(firebase_token)}"
            )

            url = (
                f"{settings.mrcall_base_url.rstrip('/')}"
                f"/mrcall/v1/delegated_{target_realm}"
                f"/customer/conversation/search"
            )
            headers = {
                "auth": firebase_token,
                "Content-Type": "application/json",
            }
            request_body = {
                "businessId": business_id,
                "from": 0,
                "size": limit,
                "lightweight": True,
                "asc": False,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
            }

            logger.info(
                f"[mrcall_sync] Calling API: {url}"
            )
            logger.debug(
                f"[mrcall_sync] Request body:"
                f" {json.dumps(request_body)}"
            )

            from zylch.api.token_storage import (
                refresh_mrcall_token,
            )

            async with httpx.AsyncClient(
                timeout=60.0,
                verify=settings.starchat_verify_ssl,
            ) as client:
                for attempt in range(2):
                    try:
                        response = await client.post(
                            url,
                            headers=headers,
                            json=request_body,
                        )
                        response.raise_for_status()
                        data = response.json()
                        break
                    except httpx.HTTPStatusError as e:
                        if (
                            e.response.status_code == 401
                            and attempt == 0
                        ):
                            logger.warning(
                                "[mrcall_sync] 401."
                                " Refreshing token..."
                            )
                            new_creds = (
                                await refresh_mrcall_token(
                                    self.owner_id
                                )
                            )
                            if new_creds and new_creds.get(
                                "access_token"
                            ):
                                logger.info(
                                    "[mrcall_sync]"
                                    " Token refreshed"
                                )
                                headers["auth"] = (
                                    new_creds[
                                        "access_token"
                                    ]
                                )
                                continue
                            else:
                                logger.error(
                                    "[mrcall_sync]"
                                    " Refresh failed"
                                )
                                raise e
                        else:
                            raise e

            conversations = (
                data.get("items", [])
                if isinstance(data, dict)
                else data
            )
            total = (
                data.get("total", len(conversations))
                if isinstance(data, dict)
                else len(conversations)
            )

            logger.info(
                f"[mrcall_sync] Fetched"
                f" {len(conversations)} conversation(s)"
                f" (total: {total})"
            )

            if debug and conversations:
                self._debug_print_conversations(
                    conversations, business_id
                )

            synced_count = 0
            skipped_count = 0

            for conv in conversations:
                try:
                    conv_id = conv.get("id")
                    if not conv_id:
                        skipped_count += 1
                        continue

                    body_data = conv.get("body")
                    if isinstance(body_data, str):
                        try:
                            body_data = json.loads(
                                body_data
                            )
                        except json.JSONDecodeError:
                            body_data = {
                                "raw": body_data
                            }

                    if isinstance(body_data, dict):
                        body_data = (
                            self._strip_audio_from_body(
                                body_data
                            )
                        )

                    raw_data = {
                        k: v
                        for k, v in conv.items()
                        if k != "body"
                    }
                    raw_data["body"] = body_data

                    self.supabase.store_mrcall_conversation(
                        owner_id=self.owner_id,
                        conversation_id=conv_id,
                        business_id=business_id,
                        contact_phone=conv.get(
                            "contactNumber"
                        ),
                        contact_name=conv.get(
                            "contactName"
                        ),
                        call_duration_ms=conv.get(
                            "duration"
                        ),
                        call_started_at=conv.get(
                            "startTimestamp"
                        ),
                        subject=conv.get("subject"),
                        body=body_data,
                        custom_values=conv.get(
                            "values"
                        ),
                        raw_data=raw_data,
                    )
                    synced_count += 1

                except Exception as e:
                    logger.warning(
                        f"[mrcall_sync] Failed to"
                        f" store conv"
                        f" {conv.get('id')}: {e}"
                    )
                    skipped_count += 1
                    continue

            logger.info(
                f"[mrcall_sync] Synced {synced_count},"
                f" skipped {skipped_count}"
            )

            return {
                "success": True,
                "synced": synced_count,
                "skipped": skipped_count,
                "total_available": total,
                "days_back": days_back,
                "business_id": business_id,
            }

        except httpx.HTTPStatusError as e:
            logger.error(
                f"[mrcall_sync] HTTP error:"
                f" {e.response.status_code}"
                f" - {e.response.text}"
            )
            return {
                "success": False,
                "error": (
                    f"MrCall API error:"
                    f" {e.response.status_code}"
                ),
                "synced": 0,
            }
        except Exception as e:
            logger.error(
                f"[mrcall_sync] Failed: {e}",
                exc_info=True,
            )
            return {
                "success": False,
                "error": str(e),
                "synced": 0,
            }

    def _debug_print_conversations(
        self,
        conversations: list,
        business_id: str,
    ) -> None:
        """Print conversation data for debugging.

        Args:
            conversations: List of conversation dicts
            business_id: Business ID for context
        """
        import json

        print(f"\n{'=' * 60}")
        print(
            f"MrCall DEBUG: Retrieved"
            f" {len(conversations)} conversation(s)"
        )
        print(f"Business ID: {business_id}")
        print(f"{'=' * 60}")
        for i, conv in enumerate(conversations):
            print(f"\n--- Conversation {i + 1} ---")
            print(f"ID: {conv.get('id')}")
            print(
                f"Timestamp:"
                f" {conv.get('startTimestamp')}"
            )
            print(
                f"Contact:"
                f" {conv.get('contactName', 'Unknown')}"
                f" ({conv.get('contactNumber', 'N/A')})"
            )
            dur = conv.get("duration", 0) / 1000
            print(f"Duration: {dur:.1f}s")
            print(
                f"Subject:"
                f" {conv.get('subject', 'N/A')}"
            )
            body_preview = str(
                conv.get("body", "N/A")
            )[:500]
            body_full = str(conv.get("body", ""))
            suffix = (
                "..."
                if len(body_full) > 500
                else ""
            )
            print(f"Body: {body_preview}{suffix}")
            if conv.get("values"):
                print(
                    f"Values:"
                    f" {json.dumps(conv.get('values'), indent=2, default=str)}"
                )
        print(f"\n{'=' * 60}\n")

    def _strip_audio_from_body(
        self, body: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Strip base64 audio data from body.

        Args:
            body: Conversation body dict

        Returns:
            Body dict with audio fields stripped
        """
        if not isinstance(body, dict):
            return body

        result = {}
        for key, value in body.items():
            if key in (
                "audio",
                "audioData",
                "audioBase64",
                "recording",
            ):
                result[key] = "[AUDIO_STRIPPED]"
            elif isinstance(value, dict):
                result[key] = (
                    self._strip_audio_from_body(value)
                )
            elif isinstance(value, list):
                result[key] = [
                    (
                        self._strip_audio_from_body(item)
                        if isinstance(item, dict)
                        else item
                    )
                    for item in value
                ]
            elif (
                isinstance(value, str)
                and len(value) > 10000
            ):
                if value.startswith(
                    (
                        "data:audio/",
                        "UklGR",
                        "SUQz",
                        "T2dnUw",
                    )
                ):
                    result[key] = "[AUDIO_STRIPPED]"
                else:
                    result[key] = value
            else:
                result[key] = value

        return result

    async def run_full_sync(
        self, days_back: Optional[int] = None,
        on_progress=None,
    ) -> Dict[str, Any]:
        """Run full sync: emails + Pipedrive + MrCall.

        Calendar sync removed (pending CalDAV impl).

        Args:
            days_back: Optional days to sync emails

        Returns:
            Combined sync results
        """
        logger.info(
            f"[full_sync] Starting"
            f" (days_back={days_back})"
        )

        results = {
            "email_sync": {
                "success": False,
                "error": "Not started",
            },
            "pipedrive_sync": {
                "success": True,
                "skipped": True,
            },
            "mrcall_sync": {
                "success": False,
                "error": "Not started",
            },
            "success": True,
            "errors": [],
        }

        # Sync emails via IMAP
        try:
            email_result = await self.sync_emails(
                days_back=days_back,
                on_progress=on_progress,
            )
            results["email_sync"] = {
                "success": True,
                **email_result,
            }
        except Exception as e:
            logger.error(f"Email sync failed: {e}")
            results["email_sync"] = {
                "success": False,
                "error": str(e),
            }
            results["errors"].append(
                f"Email sync: {str(e)}"
            )
            results["success"] = False

        # Pipedrive removed in standalone
        results["pipedrive_sync"] = {
            "success": True,
            "skipped": True,
        }

        # Sync MrCall (if connected)
        try:
            mrcall_result = (
                await self._sync_mrcall_if_connected(
                    days_back=(
                        days_back
                        if days_back is not None
                        else 30
                    )
                )
            )
            results["mrcall_sync"] = mrcall_result
            if not mrcall_result.get(
                "success"
            ) and not mrcall_result.get("skipped"):
                results["errors"].append(
                    f"MrCall sync:"
                    f" {mrcall_result.get('error', 'Unknown')}"
                )
        except Exception as e:
            logger.error(f"MrCall sync failed: {e}")
            results["mrcall_sync"] = {
                "success": False,
                "error": str(e),
            }
            results["errors"].append(
                f"MrCall sync: {str(e)}"
            )

        return results

    async def _sync_mrcall_if_connected(
        self, days_back: int = 30
    ) -> Dict[str, Any]:
        """Sync MrCall if credentials are available.

        Args:
            days_back: Days to sync

        Returns:
            Sync result dict
        """
        if not self.supabase or not self.owner_id:
            return {
                "success": True,
                "skipped": True,
                "reason": "No storage configured",
                "synced": 0,
            }

        mrcall_creds = (
            self.supabase.get_provider_credentials(
                self.owner_id, "mrcall"
            )
        )

        if mrcall_creds:
            logger.debug(
                f"[mrcall_sync] Loaded credentials."
                f" Keys: {list(mrcall_creds.keys())}"
            )
            logger.debug(
                f"[mrcall_sync] Realm:"
                f" '{mrcall_creds.get('realm')}'"
            )
            token = mrcall_creds.get("access_token")
            if token:
                logger.debug(
                    f"[mrcall_sync] Access token"
                    f" present (len={len(token)})"
                )
            else:
                logger.error(
                    "[mrcall_sync] Access token"
                    " MISSING in credentials"
                )
        else:
            logger.error(
                "[mrcall_sync] No credentials"
                " from get_provider_credentials"
            )

        if (
            not mrcall_creds
            or not mrcall_creds.get("access_token")
        ):
            return {
                "success": True,
                "skipped": True,
                "reason": "MrCall not connected",
                "synced": 0,
            }

        business_id = mrcall_creds.get("business_id")
        if not business_id:
            business_id = (
                self.supabase.get_mrcall_link(
                    self.owner_id
                )
            )

        if not business_id:
            return {
                "success": True,
                "skipped": True,
                "reason": (
                    "MrCall not linked to a business"
                ),
                "synced": 0,
            }

        return await self.sync_mrcall(
            days_back=days_back,
            firebase_token=mrcall_creds.get(
                "access_token"
            ),
            business_id=business_id,
            realm=mrcall_creds.get("realm"),
        )
