# Entity-Based Memory System - Implementation Plan

**Date:** 2025-12-15
**Status:** Approved Design

## 1. Von Neumann Architecture

### Disorganized Memory (This Plan)
- **Purpose:** Messy, human-like memory
- **Characteristics:** Contradictions OK, natural language context
- **Storage:** `memories` table

### Organized Memory (CRM Worker)
- **Purpose:** Clean, structured CRM data
- **Handler:** CRM worker
- **Storage:** CRM-specific tables

## 2. memories Table Schema (DEV MODE - Drop and Recreate)

### Fields
```sql
CREATE TABLE memories (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  namespace TEXT NOT NULL,  -- user:{user_id} or user:{user_id}:entity:{entity_id}
  context TEXT NOT NULL,     -- free-form natural language ONLY
  events JSONB DEFAULT '[]'::jsonb,  -- timestamped history
  embedding vector(384),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Removed Fields
- ❌ created_at
- ❌ confidence
- ❌ state
- ❌ category
- ❌ pattern
- ❌ examples
- ❌ times_applied

## 3. Entity Data Model

### Fields
- **id:** str (UUID - ALWAYS generated)
- **context:** str (free-form natural language description)

### Removed Fields
- ❌ identifier
- ❌ keywords

## 4. Tables to DELETE

- `patterns`
- `avatars`
- `avatar_compute_queue`

## 5. LLM Configuration

- **Model:** Sonnet/Opus (NOT Haiku)
- **Approach:** Channel-agnostic prompt (email, whatsapp, phone_call, teams, etc.)

## 6. Key Principles

1. Every entity gets a UUID
2. Free-form context only (nothing else)
3. Greedy extraction (every message)
4. Human-like memory (contradictions OK)
5. Relationships implicit in natural language
6. **DO NOT INVENT features not requested by user**

## 7. Code Changes

### NEW Files
- `entity_worker.py` (channel-agnostic entity extraction)
- `email_entity_processor.py` (email-specific wrapper)

### MODIFY Files
- `memory_worker.py` (add entity extraction call)
- `crm_worker.py` (remove avatar code, keep CRM logic)

### DELETE
- Avatar-specific code in routes and storage modules
