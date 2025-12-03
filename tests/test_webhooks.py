"""Tests for webhook endpoints and processor."""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


class TestWebhookEndpoints:
    """Tests for webhook HTTP endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from zylch.api.main import app
        return TestClient(app)

    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_starchat_webhook(self, client):
        """Test StarChat webhook endpoint."""
        payload = {
            "event_type": "call_ended",
            "business_id": "test_business",
            "call_id": "call_123",
            "caller_number": "+393331234567",
            "caller_name": "Mario Rossi",
            "direction": "inbound",
            "duration_seconds": 120,
            "transcript": "Ciao, volevo informazioni sul prodotto..."
        }

        response = client.post("/webhooks/starchat", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
        assert response.json()["event_id"] == "call_123"

    def test_sendgrid_webhook(self, client):
        """Test SendGrid webhook endpoint with multiple events."""
        events = [
            {
                "event": "delivered",
                "email": "test@example.com",
                "timestamp": 1701388800,
                "sg_message_id": "msg_123"
            },
            {
                "event": "open",
                "email": "test@example.com",
                "timestamp": 1701389000,
                "sg_event_id": "evt_456"
            }
        ]

        response = client.post("/webhooks/sendgrid", json=events)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
        assert response.json()["events_count"] == 2

    def test_gmail_push_webhook(self, client):
        """Test Gmail push notification endpoint."""
        payload = {
            "message": {
                "data": "eyJ0ZXN0IjogdHJ1ZX0=",  # base64 of {"test": true}
                "messageId": "msg_789"
            },
            "subscription": "projects/test/subscriptions/gmail-push"
        }

        response = client.post("/webhooks/gmail/push", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_vonage_status_webhook(self, client):
        """Test Vonage SMS status webhook."""
        payload = {
            "message_uuid": "sms_123",
            "to": "+393331234567",
            "status": "delivered"
        }

        response = client.post("/webhooks/vonage/status", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    def test_vonage_inbound_webhook(self, client):
        """Test Vonage inbound SMS webhook."""
        payload = {
            "messageId": "in_456",
            "msisdn": "+393331234567",
            "to": "+393009876543",
            "text": "Ciao, conferma appuntamento"
        }

        response = client.post("/webhooks/vonage/inbound", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    def test_test_webhook(self, client):
        """Test the test/debug webhook endpoint."""
        payload = {"test_key": "test_value"}

        response = client.post("/webhooks/test", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "received"
        assert response.json()["payload"] == payload

    def test_webhook_status(self, client):
        """Test webhook status endpoint."""
        response = client.get("/webhooks/status")
        assert response.status_code == 200
        assert response.json()["status"] == "operational"
        assert "stats" in response.json()

    def test_webhook_events_list(self, client):
        """Test listing webhook events."""
        response = client.get("/webhooks/events")
        assert response.status_code == 200
        assert "events" in response.json()
        assert "count" in response.json()

    def test_webhook_events_filter_by_source(self, client):
        """Test filtering webhook events by source."""
        response = client.get("/webhooks/events?source=starchat")
        assert response.status_code == 200

    def test_invalid_json_payload(self, client):
        """Test handling of invalid JSON."""
        response = client.post(
            "/webhooks/starchat",
            content="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400


class TestWebhookEventStore:
    """Tests for webhook event storage."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create store with temp database."""
        from zylch.services.webhook_processor import WebhookEventStore
        return WebhookEventStore(db_path=tmp_path / "test_webhooks.db")

    def test_store_event(self, store):
        """Test storing webhook event."""
        row_id = store.store_event(
            event_id="test_123",
            source="starchat",
            event_type="call_ended",
            payload={"test": True},
            owner_id="owner_1"
        )
        assert row_id > 0

    def test_duplicate_event_ignored(self, store):
        """Test that duplicate events are ignored."""
        store.store_event(
            event_id="dup_123",
            source="starchat",
            event_type="call_ended",
            payload={"test": True}
        )

        # Try to store same event again
        row_id = store.store_event(
            event_id="dup_123",
            source="starchat",
            event_type="call_ended",
            payload={"test": True}
        )
        assert row_id == 0  # Duplicate ignored

    def test_mark_processed(self, store):
        """Test marking event as processed."""
        store.store_event(
            event_id="proc_123",
            source="sendgrid",
            event_type="open",
            payload={}
        )

        store.mark_processed("proc_123")

        # Verify processed
        events = store.list_events()
        event = next((e for e in events if e["event_id"] == "proc_123"), None)
        assert event is not None
        assert event["processed"] == 1

    def test_mark_processed_with_error(self, store):
        """Test marking event as processed with error."""
        store.store_event(
            event_id="err_123",
            source="gmail",
            event_type="push",
            payload={}
        )

        store.mark_processed("err_123", error="Test error")

        events = store.list_events()
        event = next((e for e in events if e["event_id"] == "err_123"), None)
        assert event is not None
        assert event["error"] == "Test error"

    def test_record_engagement(self, store):
        """Test recording contact engagement."""
        store.record_engagement(
            engagement_type="email_open",
            contact_email="test@example.com",
            data={"ip": "1.2.3.4"},
            owner_id="owner_1"
        )
        # No error = success

    def test_get_stats(self, store):
        """Test getting statistics."""
        # Store some events
        store.store_event("s1", "starchat", "call_ended", {})
        store.store_event("s2", "starchat", "call_missed", {})
        store.store_event("s3", "sendgrid", "open", {})

        stats = store.get_stats()

        assert stats["total"] == 3
        assert stats["by_source"]["starchat"] == 2
        assert stats["by_source"]["sendgrid"] == 1

    def test_list_events(self, store):
        """Test listing events."""
        store.store_event("l1", "starchat", "call", {})
        store.store_event("l2", "sendgrid", "open", {})
        store.store_event("l3", "gmail", "push", {})

        # All events
        all_events = store.list_events()
        assert len(all_events) == 3

        # Filter by source
        starchat_events = store.list_events(source="starchat")
        assert len(starchat_events) == 1

        # Pagination
        paginated = store.list_events(limit=2)
        assert len(paginated) == 2


class TestWebhookProcessor:
    """Tests for webhook processor logic."""

    @pytest.fixture
    def processor(self, tmp_path):
        """Create processor with temp storage."""
        from zylch.services.webhook_processor import WebhookProcessor, WebhookEventStore

        processor = WebhookProcessor()
        processor.store = WebhookEventStore(db_path=tmp_path / "test_proc.db")
        return processor

    @pytest.mark.asyncio
    async def test_process_starchat_event(self, processor):
        """Test processing StarChat call event."""
        payload = {
            "event_type": "call_ended",
            "call_id": "test_call_1",
            "business_id": "biz_1",
            "caller_number": "+393331234567",
            "caller_name": "Mario Rossi",
            "duration_seconds": 120,
            "transcript": "Test transcript"
        }

        await processor.process_starchat_event(payload)

        # Verify event stored
        events = processor.store.list_events(source="starchat")
        assert len(events) == 1
        assert events[0]["event_type"] == "call_ended"

    @pytest.mark.asyncio
    async def test_process_sendgrid_event(self, processor):
        """Test processing SendGrid email event."""
        payload = {
            "event": "open",
            "email": "test@example.com",
            "timestamp": 1701388800,
            "sg_event_id": "sg_123"
        }

        await processor.process_sendgrid_event(payload)

        events = processor.store.list_events(source="sendgrid")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_process_gmail_push(self, processor):
        """Test processing Gmail push notification."""
        import base64

        data = base64.b64encode(json.dumps({"emailAddress": "test@gmail.com"}).encode()).decode()

        payload = {
            "data": data,
            "message_id": "gmail_123"
        }

        await processor.process_gmail_push(payload)

        events = processor.store.list_events(source="gmail")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_process_vonage_event(self, processor):
        """Test processing Vonage SMS event."""
        payload = {
            "message_uuid": "vonage_123",
            "to": "+393331234567",
            "status": "delivered"
        }

        await processor.process_vonage_event(payload)

        events = processor.store.list_events(source="vonage")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_process_vonage_inbound(self, processor):
        """Test processing inbound SMS."""
        payload = {
            "messageId": "in_123",
            "msisdn": "+393331234567",
            "text": "Test reply"
        }

        await processor.process_vonage_inbound(payload)

        events = processor.store.list_events(source="vonage")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_get_stats(self, processor):
        """Test getting processor stats."""
        stats = await processor.get_stats()

        assert "total" in stats
        assert "by_source" in stats

    @pytest.mark.asyncio
    async def test_list_events(self, processor):
        """Test listing events via processor."""
        events = await processor.list_events()
        assert isinstance(events, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
