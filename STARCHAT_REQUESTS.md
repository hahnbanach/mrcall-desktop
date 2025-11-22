# StarChat API Enhancement Requests

This document tracks feature requests for the StarChat API to improve MrPark integration.

---

## Request 1: Support CrmContactSearch body in BasicAuth GET endpoint

**Date:** 2025-11-17
**Priority:** High
**Requested by:** MrPark integration team

### Current Behavior

The BasicAuth endpoint `GET /mrcall/v1/crm/contact/{businessId}` currently:
- Accepts `CrmContactSearch` in the request body (documented in OpenAPI)
- But only uses the `id` query parameter in the actual implementation
- Does not filter by `emails`, `phones`, or other fields from the body

**Code reference:** `CrmContactResource.scala:285-288`
```scala
psqlService.search(
  businessId = businessId,
  id = contactId  // Only uses ID, ignores body
)
```

### Desired Behavior

Please implement full `CrmContactSearch` body support, similar to the Firebase JWT endpoint:
- Search by `emails: [{"address": "user@example.com"}]`
- Search by `phones: [{"number": "+391234567890"}]`
- Search by `displayName`, `name`, etc.

This would enable proper contact lookup without requiring JWT authentication.

### Use Case

MrPark needs to check if a contact already exists before creating/updating:
```python
# Current workaround: GET all contacts and filter in Python (slow)
all_contacts = await get_all_contacts(business_id)
matching = [c for c in all_contacts
            if any(e.get("address") == email for e in c.get("emails", []))]

# Desired: Direct API search
contacts = await search_contacts(
    business_id=business_id,
    emails=[{"address": email}]
)
```

### Benefits

1. **Performance**: Avoid fetching all contacts and filtering client-side
2. **Consistency**: BasicAuth and JWT endpoints have same capabilities
3. **Proper upsert**: Enable "check before create" pattern to prevent duplicates

### Implementation Notes

The Firebase endpoint already does this correctly. Please extend the same functionality to the BasicAuth endpoint by:
1. Parsing the `CrmContactSearch` from request body in `contactGetApiKeyRoute`
2. Passing search criteria to `psqlService.search()`
3. The backend service already supports these parameters (used by Firebase endpoint)

Thank you! 🙏

---

## Request 2: GET all contacts for business_id without requiring id parameter

**Date:** 2025-11-17
**Priority:** High
**Requested by:** MrPark integration team
**Status:** WORKAROUND IMPLEMENTED ✅

### Current Behavior

The BasicAuth endpoint `GET /mrcall/v1/crm/contact/{businessId}` currently:
- Accepts optional `id` query parameter
- Calls `psqlService.search(businessId, id)`
- Returns empty list when `id` is not provided (None)

**Code reference:** `CrmContactResource.scala:285-288`
```scala
psqlService.search(
  businessId = businessId,
  id = contactId  // Returns empty if None
)
```

### Desired Behavior

When `id` parameter is not provided, please return **all contacts** for that business_id (with pagination).

This would enable:
```bash
# Get all contacts for business
GET /mrcall/v1/crm/contact/{businessId}
# Returns: all contacts (paginated)

# Get specific contact
GET /mrcall/v1/crm/contact/{businessId}?id={contactId}
# Returns: single contact
```

### Use Case

MrPark needs to retrieve all contacts for a business to:
1. Check if contact exists before creating (prevent duplicates)
2. Filter contacts client-side by custom variables
3. List all contacts for the user

### ✅ Workaround Implemented (MrPark)

**Date:** 2025-11-18

We discovered that the BasicAuth endpoint DOES support `CrmContactSearch` in the POST body!

```python
# API Endpoint
POST /mrcall/v1/crm/contact/{businessId}
Content-Type: application/json

{
  "from": 0,
  "size": 100
}
```

**Implementation:**
1. Updated `StarChatClient.search_contacts()` to use POST with CrmContactSearch body
2. Added `search_contacts_paginated()` method for fetching all contacts with pagination
3. Created `ListAllContactsTool` for the agent to list all business contacts
4. Tool groups results by RELATIONSHIP_TYPE for better visibility

**Usage:**
```
You: puoi cercare tutti i contatti nel business per favore?
MrPark: [Fetches all contacts using ListAllContactsTool]
Found 127 total contacts: customer=45, lead=32, prospect=28, unknown=22
```

### API Enhancement Still Needed

While the workaround works, it would be cleaner if the API explicitly documented the POST body support:
- Document that POST with CrmContactSearch is the recommended approach
- Ensure pagination works reliably (test with large datasets)
- Consider supporting query parameters as alternative to body

### Implementation Notes

The `psqlService.search()` method already supports returning all contacts. We just needed to use the correct HTTP method (POST) and body format (CrmContactSearch).

Thank you! 🙏

---

## Request 3: (Future requests go here)

