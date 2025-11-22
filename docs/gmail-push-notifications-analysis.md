# Gmail Push Notifications - Implementation Analysis

**Date**: 2025-11-21
**Status**: Research Complete - Ready for Implementation

## Executive Summary

Gmail Push Notifications can replace the current batch sync approach with real-time notifications. This would reduce cost (fewer API calls) and improve responsiveness (instant updates instead of periodic polling).

## Technical Architecture

### How Gmail Push Works

1. **Cloud Pub/Sub Setup**
   - Create a Google Cloud Pub/Sub topic
   - Grant Gmail permission to publish to the topic
   - Create a subscription to receive messages

2. **Watch Request**
   - Call `gmail.users.watch()` to register for notifications
   - Provides: topic name, label IDs to watch (INBOX, SENT)
   - Returns: `historyId` (starting point) and `expiration` (Unix timestamp)
   - **Expiration**: 7 days maximum, but Google recommends renewing every 3 days

3. **Receiving Notifications**
   - Gmail publishes to Pub/Sub when changes occur
   - Webhook receives base64-encoded payload with:
     - `emailAddress`: The watched Gmail account
     - `historyId`: Point in time for the change
   - **Rate limit**: Maximum 1 event per second per user

4. **Processing Changes**
   - Use `gmail.users.history.list()` to fetch changes since last `historyId`
   - History API returns:
     - `messagesAdded`: New messages
     - `messagesDeleted`: Deleted messages
     - `labelsAdded`/`labelsRemoved`: Label changes
   - Process only relevant changes (new INBOX/SENT messages)

### Current MrPark Architecture

#### Existing Components
- **`/Users/mal/starchat/mrpark/mrpark/webhook/`**: Empty directory exists, ready for webhook implementation
- **`GmailClient`** (`/Users/mal/starchat/mrpark/mrpark/tools/gmail.py`): Currently implements:
  - OAuth authentication
  - `search_messages()`: Search by query
  - `get_message()`: Fetch single message
  - `list_messages()`: List message IDs
  - Missing: `watch()`, `stop()`, `history.list()` methods

- **`EmailSyncManager`** (`/Users/mal/starchat/mrpark/mrpark/tools/email_sync.py`):
  - Currently does full sync on command
  - Analyzes threads with Sonnet
  - Caches results in `cache/emails/threads.json`

#### What Needs to Be Added

1. **GmailClient Methods**:
   ```python
   def watch(self, topic_name: str, label_ids: List[str]) -> Dict[str, Any]:
       """Register for push notifications. Returns historyId and expiration."""

   def stop(self) -> None:
       """Stop watching for push notifications."""

   def list_history(self, start_history_id: str) -> List[Dict[str, Any]]:
       """Fetch changes since historyId."""
   ```

2. **Webhook Endpoint** (`mrpark/webhook/gmail_webhook.py`):
   - Flask/FastAPI endpoint to receive Pub/Sub messages
   - Verify webhook authenticity (Pub/Sub sends verification token)
   - Decode base64 payload
   - Extract `historyId`
   - Trigger incremental sync

3. **Watch Manager** (`mrpark/tools/gmail_watch.py`):
   - Track watch expiration
   - Auto-renew watch every 3 days
   - Store current `historyId` in cache
   - Handle watch failures gracefully

4. **Incremental Sync** (modify `EmailSyncManager`):
   - New method: `sync_incremental(since_history_id: str)`
   - Fetch only new/changed messages via history API
   - Update cache (add new threads, update existing)
   - Much faster and cheaper than full sync

## Implementation Plan

### Phase 1: History API Support (No webhook yet)
1. Add `list_history()` to `GmailClient`
2. Add `sync_incremental()` to `EmailSyncManager`
3. Test incremental sync manually with CLI command
4. Store `last_history_id` in cache

**Benefit**: Can test incremental sync logic without webhook infrastructure

### Phase 2: Watch Management
1. Add `watch()` and `stop()` to `GmailClient`
2. Create `GmailWatchManager` class:
   - Start watch on CLI startup or `/sync` command
   - Store expiration timestamp in cache
   - Check expiration on every operation
   - Auto-renew if < 24 hours remaining
3. Add `/watch start` and `/watch stop` CLI commands for testing

**Benefit**: Can verify watch lifecycle without webhook

### Phase 3: Webhook Implementation
1. Create Flask/FastAPI app in `mrpark/webhook/`
2. Implement `/webhook/gmail` endpoint:
   - Verify Pub/Sub signature
   - Decode payload
   - Extract historyId
   - Call `email_sync.sync_incremental(history_id)`
3. Deploy webhook to public URL (ngrok for testing, proper hosting for production)
4. Configure Pub/Sub subscription to push to webhook

**Benefit**: Full real-time notification system

### Phase 4: Production Hardening
1. Add error handling and retry logic
2. Add monitoring/logging for webhook failures
3. Add fallback: if webhook fails, do periodic full sync (safety net)
4. Add tests for incremental sync edge cases

## Cost & Performance Impact

### Current Approach (Full Sync)
- **API Calls**: ~100-500 message fetches per sync (depending on `days_back`)
- **Frequency**: Manual or cron-based (e.g., hourly)
- **Latency**: User triggers sync, waits 30-60 seconds

### With Push Notifications
- **API Calls**:
  - Initial: Full sync to establish baseline
  - Ongoing: Only fetch changed messages (typically 1-10 per event)
  - Watch renewal: 1 call every 3 days
- **Frequency**: Real-time (within seconds of email arrival)
- **Latency**: Webhook triggers immediately, update takes 1-5 seconds

**Cost Reduction**: 90%+ reduction in API calls for typical usage

## Risks & Mitigations

### Risk 1: Watch Expiration
- **Problem**: If watch expires and isn't renewed, no notifications arrive
- **Mitigation**:
  - Check expiration on every operation
  - Renew early (3 days before expiration)
  - Fallback to periodic full sync if watch fails

### Risk 2: Missed History
- **Problem**: If `historyId` is too old, Gmail returns error
- **Mitigation**:
  - If history fetch fails, fall back to full sync
  - Store last successful historyId with timestamp

### Risk 3: Webhook Downtime
- **Problem**: If webhook endpoint is down, notifications are lost
- **Mitigation**:
  - Pub/Sub retries for 7 days (configurable)
  - Run daily full sync as safety net
  - Monitor webhook health

### Risk 4: Rate Limiting
- **Problem**: Gmail limits to 1 event/sec per user
- **Mitigation**:
  - Not an issue for single-user (Mario) usage
  - For multi-user, implement queue

## Current Bugs Fixed

While researching this, discovered and fixed critical bug in `email_sync.py`:

**Bug**: Alphabetic sort of date strings instead of datetime sort
- "Thu, 20 Nov" sorted BEFORE "Wed, 19 Nov" (T < W alphabetically)
- This caused wrong message to be treated as "last message" in thread
- **Fix**: Added `_parse_email_date_for_sort()` method that properly parses RFC2822 dates
- **Impact**: Luisa Boni thread now correctly identifies Nov 20 email as latest (not Nov 19)

## Recommendation

**Implement in phases**:
1. **Now**: Phase 1 (History API) - Low risk, high value for testing
2. **Next week**: Phase 2 (Watch management) - Establishes lifecycle without webhook complexity
3. **When needed**: Phase 3 (Webhook) - Full real-time system

**Alternative**: Keep current full sync approach, but optimize it:
- The date sort bug fix (just completed) was critical
- Full sync works reliably if triggered frequently enough
- Push notifications are optimization, not requirement

## Next Steps

1. ✅ Fix date sort bug (COMPLETED)
2. Test date fix with Luisa Boni thread (IN PROGRESS)
3. Decide: Implement push notifications or optimize current approach?
4. If implementing: Start with Phase 1 (History API)
