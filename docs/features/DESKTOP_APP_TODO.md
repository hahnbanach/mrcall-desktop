# Desktop Application - Future Development

## Status
🟡 **MEDIUM PRIORITY** - Local-First Experience

## Business Impact

**Target Users**:
- Power users who prefer desktop apps over web
- Users who need offline access
- Privacy-conscious users preferring local data storage
- Professionals who want system tray integration

**Why Important**:
- **Better UX**: Native OS integration, keyboard shortcuts, system notifications
- **Offline support**: Work without internet connection
- **Performance**: Faster than web app (local database)
- **Privacy**: Local-first option for sensitive data
- **Differentiation**: Desktop app = premium offering

**Use Cases**:
- Sales professionals working offline (flights, low connectivity)
- Executives preferring desktop apps
- Users with privacy requirements (local data storage)
- Power users wanting keyboard shortcuts and quick access

## Current State

### What Exists
- ✅ **Multi-tenant backend**: API supports desktop client authentication
- ✅ **REST API**: All features accessible via API endpoints
- ✅ **Supabase sync**: Cloud storage ready for hybrid sync
- ✅ **JWT authentication**: Token-based auth works for desktop

### What's Missing
- ❌ **Desktop app**: No Tauri/Electron application
- ❌ **Local database**: No SQLite for offline storage
- ❌ **Sync engine**: No hybrid cloud/local sync
- ❌ **System integration**: No tray icon, keyboard shortcuts
- ❌ **Auto-updates**: No built-in update mechanism

## Planned Features

### 1. Tauri Desktop Application

**Why Tauri over Electron**:
- **Smaller**: 600KB vs 60MB (Electron)
- **Faster**: Rust backend, native webview
- **Secure**: Sandboxed by default
- **Cross-platform**: Windows, macOS, Linux

**Tech Stack**:
```toml
[dependencies]
tauri = "2.0"
tauri-plugin-sql = "2.0"          # SQLite integration
tauri-plugin-window = "2.0"       # System tray
tauri-plugin-notification = "2.0" # Native notifications
tauri-plugin-updater = "2.0"      # Auto-updates
```

**Frontend**: Vue 3 (reuse existing dashboard)
**Backend**: Rust (Tauri)
**Database**: SQLite (local) + Supabase (cloud)

### 2. Local SQLite Database

**Schema** (mirror cloud schema):
```sql
-- Email cache
CREATE TABLE emails (
  id TEXT PRIMARY KEY,
  gmail_message_id TEXT,
  thread_id TEXT,
  from_email TEXT,
  to_emails TEXT,
  subject TEXT,
  body TEXT,
  date TIMESTAMP,
  synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Calendar events cache
CREATE TABLE calendar_events (
  id TEXT PRIMARY KEY,
  external_id TEXT,
  provider TEXT, -- 'google', 'microsoft'
  summary TEXT,
  start_time TIMESTAMP,
  end_time TIMESTAMP,
  attendees TEXT,
  synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Contacts cache
CREATE TABLE contacts (
  id TEXT PRIMARY KEY,
  email TEXT,
  name TEXT,
  phone TEXT,
  whatsapp TEXT,
  synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tasks cache
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  contact_email TEXT,
  contact_name TEXT,
  task_view TEXT,
  status TEXT,
  priority INTEGER,
  synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sync state
CREATE TABLE sync_state (
  resource_type TEXT PRIMARY KEY, -- 'emails', 'calendar', 'contacts', 'tasks'
  last_sync_at TIMESTAMP,
  last_sync_token TEXT
);
```

### 3. Hybrid Sync Engine

**Sync Strategy**:
```rust
// Rust backend sync engine
pub struct SyncEngine {
    local_db: SqliteConnection,
    cloud_api: SupabaseClient,
    auth_token: String,
}

impl SyncEngine {
    // Two-way sync: Cloud → Local, Local → Cloud
    pub async fn sync_all(&self) -> Result<SyncReport> {
        let mut report = SyncReport::new();

        // 1. Pull from cloud (if online)
        if self.is_online().await {
            report.emails_pulled = self.pull_emails().await?;
            report.calendar_pulled = self.pull_calendar().await?;
            report.contacts_pulled = self.pull_contacts().await?;

            // 2. Push local changes to cloud
            report.emails_pushed = self.push_emails().await?;
            report.calendar_pushed = self.push_calendar().await?;
        }

        // 3. Update local indexes
        self.rebuild_indexes().await?;

        Ok(report)
    }

    // Incremental sync using last_sync_token
    async fn pull_emails(&self) -> Result<usize> {
        let last_sync = self.get_last_sync("emails").await?;

        let new_emails = self.cloud_api.get_emails_since(last_sync).await?;

        for email in new_emails {
            self.local_db.upsert_email(&email).await?;
        }

        self.set_last_sync("emails", Utc::now()).await?;

        Ok(new_emails.len())
    }
}
```

**Conflict Resolution**:
- Cloud wins for read-only data (emails, calendar events)
- Local wins for user actions (tasks, notes)
- Last-write-wins for contacts

### 4. System Integration

**System Tray Icon**:
```rust
use tauri::SystemTray, SystemTrayEvent;

let tray = SystemTray::new().with_menu(
    SystemTrayMenu::new()
        .add_item(CustomMenuItem::new("show", "Show Zylch"))
        .add_separator()
        .add_item(CustomMenuItem::new("sync", "Sync Now"))
        .add_item(CustomMenuItem::new("gaps", "Relationship Gaps"))
        .add_separator()
        .add_item(CustomMenuItem::new("quit", "Quit"))
);

tauri::Builder::default()
    .system_tray(tray)
    .on_system_tray_event(|app, event| match event {
        SystemTrayEvent::MenuItemClick { id, .. } => match id.as_str() {
            "show" => show_main_window(app),
            "sync" => trigger_sync(app),
            "gaps" => show_gaps_view(app),
            "quit" => std::process::exit(0),
            _ => {}
        },
        _ => {}
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
```

**Global Keyboard Shortcuts**:
- `Cmd/Ctrl + Shift + Z` → Show Zylch window
- `Cmd/Ctrl + Shift + S` → Trigger sync
- `Cmd/Ctrl + Shift + G` → Show relationship gaps

**Native Notifications**:
```rust
use tauri::api::notification::Notification;

// New relationship gap detected
Notification::new("com.zylch.desktop")
    .title("Relationship Gap Detected")
    .body("John Smith's email awaiting response (3 days)")
    .icon("icons/gap.png")
    .show()?;
```

### 5. Offline Mode

**Offline Detection**:
```typescript
// Frontend Vue 3
import { ref, onMounted } from 'vue'

const isOnline = ref(navigator.onLine)

onMounted(() => {
  window.addEventListener('online', () => isOnline.value = true)
  window.addEventListener('offline', () => isOnline.value = false)
})

// Show offline banner
<div v-if="!isOnline" class="offline-banner">
  ⚠️ Offline Mode - Changes will sync when online
</div>
```

**Offline Capabilities**:
- ✅ View cached emails, calendar, contacts
- ✅ Search local data
- ✅ Create/update tasks
- ✅ Draft emails (save locally, send when online)
- ❌ Cannot sync new emails (requires internet)
- ❌ Cannot send emails (requires internet)

### 6. Auto-Updates

**Tauri Updater**:
```rust
use tauri::updater;

tauri::Builder::default()
    .setup(|app| {
        let handle = app.handle();

        // Check for updates on startup
        tauri::async_runtime::spawn(async move {
            match handle.updater().check().await {
                Ok(update) => {
                    if update.is_update_available() {
                        // Download and install update
                        update.download_and_install().await?;

                        // Restart app
                        handle.restart();
                    }
                }
                Err(e) => eprintln!("Failed to check for updates: {}", e),
            }
        });

        Ok(())
    })
    .run(tauri::generate_context!())
```

**Update Server**:
- GitHub Releases for version hosting
- Semantic versioning (v1.0.0, v1.1.0, etc.)
- Signed updates for security

## Technical Requirements

### Development Dependencies
```bash
# Tauri CLI
cargo install tauri-cli

# Rust toolchain
rustup update stable

# Frontend (Vue 3)
npm install -g @vue/cli
```

### Build Tools
```toml
# Cargo.toml
[package]
name = "zylch-desktop"
version = "1.0.0"
edition = "2021"

[dependencies]
tauri = { version = "2.0", features = ["system-tray", "notification", "updater"] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
tokio = { version = "1", features = ["full"] }
sqlx = { version = "0.7", features = ["sqlite", "runtime-tokio-native-tls"] }
reqwest = { version = "0.11", features = ["json"] }
```

### Platform-Specific
**macOS**: Code signing with Apple Developer certificate
**Windows**: Code signing with certificate (Authenticode)
**Linux**: AppImage, .deb, .rpm packages

## Implementation Phases

### Phase 1: Tauri Setup (Week 1)
**Duration**: 3-4 days
**Tasks**:
1. Initialize Tauri project
2. Configure Rust backend
3. Integrate existing Vue 3 frontend
4. Set up dev environment
5. Test hello world app on all platforms

### Phase 2: Local Database (Week 1-2)
**Duration**: 3-4 days
**Tasks**:
1. Set up SQLite with sqlx
2. Create database schema
3. Implement migrations
4. Create data access layer (DAL)
5. Test CRUD operations

### Phase 3: Sync Engine (Week 2-3)
**Duration**: 5-7 days
**Tasks**:
1. Implement cloud API client
2. Build two-way sync logic
3. Handle conflict resolution
4. Add incremental sync with tokens
5. Test sync with real data
6. Handle edge cases (offline, sync conflicts)

### Phase 4: System Integration (Week 3)
**Duration**: 3-4 days
**Tasks**:
1. Implement system tray
2. Add global keyboard shortcuts
3. Create native notifications
4. Test on all platforms (macOS, Windows, Linux)

### Phase 5: Auto-Updates (Week 4)
**Duration**: 2-3 days
**Tasks**:
1. Set up GitHub Releases workflow
2. Implement Tauri updater
3. Code sign for macOS and Windows
4. Test update flow

### Phase 6: Polish & Release (Week 4-5)
**Duration**: 3-5 days
**Tasks**:
1. Create installers (.dmg, .exe, AppImage)
2. Write desktop app documentation
3. Create video tutorials
4. Beta test with power users
5. Public release

## Success Metrics

### Technical Metrics
- **App Size**: <10MB installed (vs 60MB+ for Electron)
- **Startup Time**: <2 seconds cold start
- **Sync Speed**: Full sync in <30 seconds
- **Offline Support**: 100% of read features work offline

### Business Metrics
- **Desktop Adoption**: >15% of users install desktop app
- **Power User Retention**: >80% of desktop users are power users
- **Premium Positioning**: Desktop app increases perceived value

### User Experience Metrics
- **Installation Time**: <1 minute to install and launch
- **User Satisfaction**: >4.7/5 stars for desktop app
- **Offline Usage**: >30% of desktop users use offline mode

## Related Documentation

- **Architecture**: `docs/architecture/overview.md` - Hybrid sync architecture
- **API**: `docs/api/` - REST API endpoints for desktop client
- **Frontend**: `frontend/ARCHITECTURE.md` - Reusable Vue 3 components

## Open Questions

1. **Linux Support**: Which distros to officially support?
   - **Proposal**: Ubuntu/Debian, Fedora/RHEL (via .deb and .rpm)

2. **Sync Frequency**: How often to auto-sync in desktop app?
   - **Proposal**: Every 5 minutes when online + manual sync button

3. **Data Encryption**: Should local SQLite database be encrypted?
   - **Proposal**: Use SQLCipher for encrypted local database

4. **Multi-Account**: Should desktop app support multiple users?
   - **Proposal**: v1 = single user, v2 = account switching

5. **Portable Mode**: Should we offer a portable version (no installer)?
   - **Proposal**: Yes, for USB stick usage and no-install scenarios

---

**Priority**: 🟡 **MEDIUM - Power User Experience**

**Owner**: Desktop Team (New hire or Mario)

**Dependencies**:
- Tauri knowledge (learn Rust)
- Vue 3 frontend (already exists)
- REST API (already exists)

**Next Steps**:
1. Research Tauri best practices
2. Set up Tauri development environment
3. Create proof-of-concept desktop app
4. Decide on sync strategy

**Estimated Timeline**: 5-6 weeks

**Last Updated**: December 2025
