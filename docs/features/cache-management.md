---
description: |
  Cache directory structure: zylch_memory.db (behavioral corrections), contact caches (JSON),
  email archive (local DB), calendar cache, relationship data. CLI commands for management
  include /memory --remove --all (clear behavioral corrections). Note: parts of this predate
  the Supabase migration; the primary storage is now Supabase, not local filesystem.
---

# Cache and Memory Management

This document describes the cache and memory management features in Zylch AI.

## Overview

Zylch AI maintains a cache directory (`cache/`) containing:
- **zylch_memory.db** - Behavioral corrections (memory system)
- **Contact caches** - JSON files with contact information
- **Email archive** - Local email database
- **Calendar cache** - Calendar event data
- **Relationship data** - Relationship analysis results

## CLI Commands

### Memory Management

#### Clear All Memories

```bash
/memory --remove --all
```

**Description:** Deletes ALL behavioral corrections from the memory database (`zylch_memory.db`)

**What it does:**
- Removes `cache/zylch_memory.db`
- Removes `cache/indices/` directory (vector embeddings)

**Safety:** Requires typing 'yes' to confirm

**Example:**
```
Zylch AI > /memory --remove --all
⚠️  WARNING: This will delete ALL behavioral corrections from the memory database!
   This action cannot be undone.

   Type 'yes' to confirm: yes
✅ All behavioral corrections removed from memory database
   Deleted: cache/zylch_memory.db
   Deleted indices: cache/indices
```

### Cache Management

#### Clear Entire Cache

```bash
/cache --clear
```

**Description:** Deletes the entire cache directory contents

**What it does:**
- Removes all files in `cache/` (except `.gitkeep`)
- Removes all subdirectories (`emails/`, `calendar/`, etc.)
- Includes memory database, email archive, contact caches, etc.

**Safety:** Requires typing 'yes' to confirm

**Example:**
```
Zylch AI > /cache --clear
⚠️  WARNING: This will delete ALL cache data!
   This includes:
   - All contact caches
   - Email archive
   - Calendar cache
   - Memory database (behavioral corrections)
   - Relationship data

   This action cannot be undone.

   Type 'yes' to confirm: yes
✅ Cache cleared successfully!
   Freed 7.60 MB
   Location: cache
```

#### View Cache Information

```bash
/cache
```

Shows cache directory contents and usage statistics.

## HTTP API Endpoints

### Get Cache Information

```http
GET /api/admin/cache/info
```

**Response:**
```json
{
    "exists": true,
    "path": "cache",
    "total_size_bytes": 7973565,
    "total_size_mb": 7.6,
    "contents": [
        {
            "type": "directory",
            "name": "emails",
            "size_bytes": 7776973,
            "size_mb": 7.42,
            "file_count": 2
        },
        {
            "type": "file",
            "name": "zylch_memory.db",
            "size_bytes": 65536,
            "size_mb": 0.06
        }
    ]
}
```

### Clear Memory Database

```http
POST /api/admin/memory/clear?confirm=true
```

**Query Parameters:**
- `confirm` (boolean, required): Must be `true` to execute

**Response (Success):**
```json
{
    "success": true,
    "message": "Memory database cleared successfully",
    "details": {
        "deleted": [
            {
                "file": "cache/zylch_memory.db",
                "size_bytes": 65536
            }
        ],
        "total_bytes_freed": 65536,
        "total_mb_freed": 0.06
    }
}
```

**Response (Missing Confirmation):**
```json
{
    "detail": "Must set confirm=true to clear memory. This action cannot be undone."
}
```

### Clear Entire Cache

```http
POST /api/admin/cache/clear?confirm=true
```

**Query Parameters:**
- `confirm` (boolean, required): Must be `true` to execute

**Response (Success):**
```json
{
    "success": true,
    "message": "Cache cleared successfully",
    "details": {
        "deleted": [
            {
                "type": "file",
                "path": "cache/zylch_memory.db",
                "size_bytes": 65536
            },
            {
                "type": "directory",
                "path": "cache/emails",
                "size_bytes": 7776973
            }
        ],
        "total_bytes_freed": 7973565,
        "total_mb_freed": 7.6,
        "cache_location": "cache"
    }
}
```

## API Usage Examples

### Python

```python
import requests

# Get cache info
response = requests.get("http://localhost:8000/api/admin/cache/info")
cache_info = response.json()
print(f"Cache size: {cache_info['total_size_mb']} MB")

# Clear memory (with confirmation)
response = requests.post(
    "http://localhost:8000/api/admin/memory/clear",
    params={"confirm": True}
)
result = response.json()
if result["success"]:
    print(f"Freed {result['details']['total_mb_freed']} MB")

# Clear entire cache (with confirmation)
response = requests.post(
    "http://localhost:8000/api/admin/cache/clear",
    params={"confirm": True}
)
result = response.json()
if result["success"]:
    print(f"Cache cleared: {result['details']['total_mb_freed']} MB freed")
```

### cURL

```bash
# Get cache info
curl http://localhost:8000/api/admin/cache/info

# Clear memory database (with confirmation)
curl -X POST "http://localhost:8000/api/admin/memory/clear?confirm=true"

# Clear entire cache (with confirmation)
curl -X POST "http://localhost:8000/api/admin/cache/clear?confirm=true"
```

### JavaScript/TypeScript

```typescript
// Get cache info
const cacheInfo = await fetch('http://localhost:8000/api/admin/cache/info')
    .then(r => r.json());
console.log(`Cache size: ${cacheInfo.total_size_mb} MB`);

// Clear memory (with confirmation)
const clearMemory = await fetch(
    'http://localhost:8000/api/admin/memory/clear?confirm=true',
    { method: 'POST' }
).then(r => r.json());

if (clearMemory.success) {
    console.log(`Freed ${clearMemory.details.total_mb_freed} MB`);
}

// Clear entire cache (with confirmation)
const clearCache = await fetch(
    'http://localhost:8000/api/admin/cache/clear?confirm=true',
    { method: 'POST' }
).then(r => r.json());

if (clearCache.success) {
    console.log(`Cache cleared: ${clearCache.details.total_mb_freed} MB freed`);
}
```

## Safety Features

Both commands implement safety features to prevent accidental data loss:

1. **CLI**: Interactive confirmation prompt requiring user to type 'yes'
2. **HTTP API**: Requires `confirm=true` query parameter, returns error if missing
3. **Clear messaging**: Detailed warnings about what will be deleted
4. **Detailed response**: Reports exactly what was deleted and how much space was freed

## Use Cases

### Development & Testing

Clear cache during development to test initialization:
```bash
/cache --clear
```

### Memory System Reset

Remove all learned behavioral corrections:
```bash
/memory --remove --all
```

### Troubleshooting

If you experience issues with cached data:
1. Try clearing specific caches first (not implemented yet)
2. Use `/cache --clear` as last resort
3. System will reinitialize caches on next use

## Important Notes

- ⚠️  **Both operations are irreversible** - deleted data cannot be recovered
- The `.gitkeep` file is preserved to maintain directory structure
- After clearing, caches will be rebuilt automatically on next use
- Email archive clearing might require re-syncing emails (time-consuming)
- Consider backing up important data before clearing
