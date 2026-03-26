# Zylch Web Frontend - DORMANT

**This frontend is NOT under active development.** It was scaffolded as a Vue 3 + Pinia + Tailwind dashboard prototype but is not the primary interface for any product.

## Active Interfaces (where development happens)

| Interface | Location | Stack | Purpose |
|-----------|----------|-------|---------|
| **zylch-cli** | `~/hb/zylch-cli` | Python (Textual TUI) | Primary Zylch user interface |
| **mrcall-dashboard** | `~/hb/mrcall-dashboard` | Vue 3, Vuex, PrimeVue | MrCall business configuration dashboard |

## What this frontend contains

- Vue 3 + Vite + TypeScript
- Pinia state management
- Tailwind CSS
- Views: Login, Dashboard/Chat, Email, Tasks, Calendar, Contacts, Memory, Settings, MrCall, Sync
- Firebase Auth integration
- Deployed prototype at app.zylchai.com (Vercel) - not actively maintained

## Why it exists but is dormant

The frontend was built during Phase G as a proof-of-concept web dashboard. However:
- The **CLI** (`~/hb/zylch-cli`) is the primary user-facing interface for Zylch
- The **MrCall Dashboard** (`~/hb/mrcall-dashboard`) is the primary interface for MrCall configuration
- This frontend may be revisited in the future if a Zylch web app becomes a priority

## If you're making changes

Some backend features (like MrCall training status) have frontend integration code here. This is fine to keep as reference, but **always prioritize** the mrcall-dashboard and zylch-cli for user-facing features.

Do NOT invest time improving or refactoring this frontend unless explicitly asked.
