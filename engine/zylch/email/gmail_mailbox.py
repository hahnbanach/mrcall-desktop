from __future__ import annotations

import base64
import binascii
import email
import re
from email.policy import default
from typing import Any
from urllib.parse import quote

import httpx

from .gmail_auth import API_ROOT, GmailAuth, GmailError


class GmailMailbox:
    def __init__(self, owner: str, *, auth=None, http_client=None):
        self.owner = owner.strip().lower()
        self.auth = auth if auth is not None else GmailAuth(self.owner)
        self.client = http_client if http_client is not None else httpx.Client(timeout=30, follow_redirects=False)
        self._owns_client = http_client is None
        self._owns_auth = auth is None
        try:
            identity = self.auth.verify()
            if not isinstance(identity, dict) or identity.get("email", "").strip().lower() != self.owner:
                raise GmailError("gmail_mailbox_mismatch")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
        if self._owns_auth:
            self.auth.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _request(self, method: str, path: str, *, allow_missing=False, **kwargs):
        try:
            token = self.auth.access_token()
        except GmailError as error:
            # No mailbox request has started when authorization fails here.
            error.non_dispatch = method in {"POST", "PUT", "PATCH", "DELETE"}
            raise
        try:
            response = self.client.request(
                method, API_ROOT + path, headers={"Authorization": "Bearer " + token},
                follow_redirects=False, **kwargs,
            )
        except httpx.HTTPError:
            raise GmailError("gmail_provider_unavailable") from None
        if allow_missing and response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            reason = "gmail_authorization_required" if response.status_code in {401, 403} else "gmail_provider_error"
            if response.status_code == 404:
                reason = "gmail_item_not_found"
            error = GmailError(reason, response.status_code)
            error.non_dispatch = method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code in {
                400, 401, 403, 404, 405, 413, 415, 422, 429,
            }
            raise error
        try:
            result = response.json()
        except (ValueError, UnicodeError):
            raise GmailError("gmail_provider_response_invalid") from None
        if not isinstance(result, dict):
            raise GmailError("gmail_provider_response_invalid")
        return result

    @staticmethod
    def _id(value: Any) -> str:
        if not isinstance(value, str) or not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise GmailError("gmail_identity_invalid")
        return quote(value, safe="")

    @staticmethod
    def _rfc_id(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", value):
            raise GmailError("gmail_message_id_invalid")
        return value

    @staticmethod
    def _raw(value: Any) -> str:
        if not isinstance(value, bytes) or not value:
            raise GmailError("gmail_message_invalid")
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _message(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise GmailError("gmail_provider_response_invalid")
        message_id = value.get("id")
        thread_id = value.get("threadId")
        labels = value.get("labelIds")
        encoded = value.get("raw")
        if (not isinstance(message_id, str) or not message_id or not isinstance(thread_id, str)
                or not thread_id or not isinstance(labels, list) or any(not isinstance(x, str) for x in labels)
                or not isinstance(encoded, str) or not encoded):
            raise GmailError("gmail_provider_response_invalid")
        try:
            raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        except (binascii.Error, ValueError):
            raise GmailError("gmail_provider_response_invalid") from None
        if not raw:
            raise GmailError("gmail_provider_response_invalid")
        return {"id": message_id, "message_id": message_id, "thread_id": thread_id, "labels": labels, "raw": raw}

    def _draft(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]:
            raise GmailError("gmail_provider_response_invalid")
        result = self._message(value.get("message"))
        return dict(result, id=value["id"])

    def _listing(self, path: str, key: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        tokens: set[str] = set()
        identities: set[str] = set()
        query = dict(params or {}, maxResults=500)
        while True:
            result = self._request("GET", path, params=query)
            batch = result.get(key, [])
            if not isinstance(batch, list):
                raise GmailError("gmail_inventory_incomplete")
            for row in batch:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in identities:
                    raise GmailError("gmail_inventory_incomplete")
                identities.add(row["id"])
                rows.append(row)
            page = result.get("nextPageToken")
            if page is None:
                return rows
            if not isinstance(page, str) or not page or page in tokens:
                raise GmailError("gmail_inventory_incomplete")
            tokens.add(page)
            query["pageToken"] = page

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        result = self._request("GET", "/drafts/" + self._id(draft_id), params={"format": "raw"}, allow_missing=True)
        if result is None:
            return None
        draft = self._draft(result)
        if draft["id"] != draft_id:
            raise GmailError("gmail_identity_mismatch")
        if "TRASH" in draft["labels"] or "SENT" in draft["labels"]:
            return None
        if "DRAFT" not in draft["labels"]:
            raise GmailError("gmail_item_not_draft")
        return draft

    def list_drafts(self) -> list[dict[str, Any]]:
        results = []
        for row in self._listing("/drafts", "drafts"):
            draft = self.get_draft(row["id"])
            if draft is None:
                raise GmailError("gmail_inventory_changed")
            results.append(draft)
        return results

    def create_draft(self, raw: bytes, thread_id: str | None = None) -> dict[str, Any]:
        message = {"raw": self._raw(raw)}
        if thread_id is not None:
            message["threadId"] = self._id(thread_id)
        result = self._request("POST", "/drafts", json={"message": message})
        draft_id = result.get("id")
        self._id(draft_id)
        draft = self.get_draft(draft_id)
        if draft is None:
            raise GmailError("gmail_draft_creation_unconfirmed")
        return draft

    def update_draft(self, draft_id: str, raw: bytes, thread_id: str | None = None) -> dict[str, Any]:
        message = {"raw": self._raw(raw)}
        if thread_id is not None:
            message["threadId"] = self._id(thread_id)
        result = self._request("PUT", "/drafts/" + self._id(draft_id), json={"message": message})
        if result.get("id") != draft_id:
            raise GmailError("gmail_identity_mismatch")
        draft = self.get_draft(draft_id)
        if draft is None:
            raise GmailError("gmail_draft_update_unconfirmed")
        return draft

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        result = self._request("GET", "/messages/" + self._id(message_id), params={"format": "raw"}, allow_missing=True)
        if result is None:
            return None
        message = self._message(result)
        if message["id"] != message_id:
            raise GmailError("gmail_identity_mismatch")
        return message

    def trash_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise GmailError("gmail_draft_not_found", 404)
        result = self._request("POST", "/messages/" + self._id(draft["message_id"]) + "/trash", json={})
        if result.get("id") != draft["message_id"]:
            raise GmailError("gmail_identity_mismatch")
        observed = self.get_message(draft["message_id"])
        if observed is None or "TRASH" not in observed["labels"] or self.get_draft(draft_id) is not None:
            raise GmailError("gmail_trash_unconfirmed")
        return {"id": draft_id, "message_id": draft["message_id"], "status": "trashed", "verified": True}

    def _sent_submission(self, result: dict[str, Any]) -> dict[str, Any]:
        message_id = result.get("id")
        self._id(message_id)
        return {"id": message_id, "message_id": message_id, "thread_id": result.get("threadId"), "acknowledged": True}

    def send_draft(self, draft_id: str, raw: bytes) -> dict[str, Any]:
        result = self._request("POST", "/drafts/send", json={"id": self._id(draft_id), "message": {"raw": self._raw(raw)}})
        return self._sent_submission(result)

    def send_message(self, raw: bytes) -> dict[str, Any]:
        return self._sent_submission(self._request("POST", "/messages/send", json={"raw": self._raw(raw)}))

    @staticmethod
    def _has_rfc_id(raw: bytes, rfc_id: str) -> bool:
        message = email.message_from_bytes(raw, policy=default)
        values = message.get_all("Message-ID", [])
        return len(values) == 1 and str(values[0]).strip() == rfc_id

    def sent(self, message_id: str) -> list[dict[str, Any]]:
        wanted = self._rfc_id(message_id)
        results = []
        for item in self._listing("/messages", "messages", {"labelIds": "SENT", "q": "rfc822msgid:" + wanted}):
            message = self.get_message(item["id"])
            if message is None:
                raise GmailError("gmail_sent_inventory_changed")
            if "SENT" in message["labels"] and self._has_rfc_id(message["raw"], wanted):
                results.append(message)
        return results

    def find_drafts(self, message_id: str) -> list[dict[str, Any]]:
        wanted = self._rfc_id(message_id)
        results = []
        for item in self._listing("/drafts", "drafts", {"q": "rfc822msgid:" + wanted}):
            draft = self.get_draft(item["id"])
            if draft is None:
                raise GmailError("gmail_inventory_changed")
            if self._has_rfc_id(draft["raw"], wanted):
                results.append(draft)
        return results

    def thread_for_message(self, message_id: str) -> str:
        wanted = self._rfc_id(message_id)
        matches = []
        for item in self._listing("/messages", "messages", {"q": "rfc822msgid:" + wanted}):
            message = self.get_message(item["id"])
            if message is None:
                raise GmailError("gmail_inventory_changed")
            if self._has_rfc_id(message["raw"], wanted) and not {"TRASH", "SPAM"}.intersection(message["labels"]):
                matches.append(message)
        if not matches:
            raise GmailError("gmail_source_not_found", 404)
        if len(matches) != 1:
            raise GmailError("gmail_source_ambiguous")
        return matches[0]["thread_id"]

    def conversation(self, message_id: str) -> list[dict[str, Any]]:
        thread_id = self.thread_for_message(message_id)
        result = self._request("GET", "/threads/" + self._id(thread_id), params={"format": "minimal"})
        if result.get("id") != thread_id or not isinstance(result.get("messages"), list):
            raise GmailError("gmail_thread_incomplete")
        messages = []
        seen = set()
        for item in result["messages"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in seen:
                raise GmailError("gmail_thread_incomplete")
            seen.add(item["id"])
            observed = self.get_message(item["id"])
            if observed is None or observed["thread_id"] != thread_id:
                raise GmailError("gmail_thread_incomplete")
            messages.append(observed)
        if not messages or not any(self._has_rfc_id(m["raw"], message_id) for m in messages):
            raise GmailError("gmail_thread_incomplete")
        final = self._request("GET", "/threads/" + self._id(thread_id), params={"format": "minimal"})
        if final != result:
            raise GmailError("gmail_thread_changed")
        return messages
