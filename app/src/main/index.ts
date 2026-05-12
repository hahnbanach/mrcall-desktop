import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, shell } from 'electron'
import { join } from 'path'
import { statSync, existsSync } from 'fs'
import { homedir } from 'os'
import { SidecarClient } from './sidecar'
import {
  createProfileFS,
  createProfileForFirebaseUser,
  listProfilesWithEmail,
  ProfileSummary,
  profileDir,
  readProfileEnvValue
} from './profileFS'
import { cancelGoogleSignin, startGoogleSignin } from './googleSignin'
import { GOOGLE_SIGNIN_CLIENT_ID, GOOGLE_SIGNIN_CLIENT_SECRET } from './oauthConfig'

// Brand the running process. Three layers each cover a different surface:
//
//  - `app.setName()`      → the auto-built macOS appMenu (About / Hide / Quit)
//                          and `app.getName()` everywhere it's read
//  - `process.title`      → Activity Monitor / `ps` output
//  - `package.json`       → `productName` at top level is what
//                          electron-builder bakes into the packaged
//                          bundle's CFBundleName + what Electron's
//                          `app.getName()` reads at startup
//
// The Cmd-Tab label and the bold app name in the menu bar (next to the
// Apple logo) read from the .app bundle's Info.plist — `app.setName()`
// cannot reach those. `scripts/patch-electron-name.mjs` (run via
// `postinstall`) fixes this for dev. Packaged builds get the right
// CFBundleName from electron-builder + `productName` at install time.
app.setName('MrCall Desktop')
process.title = 'MrCall Desktop'

// MrCall icon used as: BrowserWindow `icon` (Windows/Linux taskbar) and as
// the macOS Dock / Cmd-Tab override in dev. In packaged macOS builds the
// .icns inside Contents/Resources (auto-baked by electron-builder from
// build/icon.png) is what the system uses, so we don't override the Dock
// icon there. The path is relative to `out/main/` (electron-vite build
// output); in packaged builds `build/` is not shipped, so we only touch
// it in dev.
const ICON_PATH = join(__dirname, '../../build/icon.png')

// Sidecar binary path.
//
// - In dev (`npm run dev`): fall back to the developer's local venv,
//   overridable via ZYLCH_BINARY env var.
// - In a packaged app (`npm run dist`): electron-builder copies the
//   sidecar into `<app>/Contents/Resources/bin/zylch` (macOS) or
//   `<app>\resources\bin\zylch.exe` (Windows). `process.resourcesPath`
//   resolves to that directory at runtime.
//
// ZYLCH_CWD is only used in dev; the packaged sidecar is self-contained
// (PyInstaller single-file) and doesn't need a specific cwd. Defaults to
// the user's home directory — always exists, doesn't matter what it is
// because the Python sidecar locates its data via `~/.zylch` regardless
// of cwd. Override with ZYLCH_CWD=/path/to/repo if running uninstalled
// Python imports out of a checkout.
const ZYLCH_CWD = process.env.ZYLCH_CWD || homedir()
function resolveSidecarBinary(): string {
  if (process.env.ZYLCH_BINARY) return process.env.ZYLCH_BINARY
  if (app.isPackaged) {
    const name = process.platform === 'win32' ? 'zylch.exe' : 'zylch'
    return join(process.resourcesPath, 'bin', name)
  }
  // Dev fallback: legacy local-checkout layout (engine venv at the
  // repo root). Use ZYLCH_BINARY for any other layout.
  return join(ZYLCH_CWD, 'private', 'zylch-standalone', 'venv', 'bin', 'zylch')
}
// Deferred until app.whenReady so `app.isPackaged` is reliable.
let ZYLCH_BINARY = ''

// Per-method default timeouts (ms). Callers may override by passing an
// explicit `timeout` — this map only sets the default when none given.
const METHOD_TIMEOUTS: Record<string, number> = {
  'chat.send': 600000, // 10 min — embedding download + tool-use loop
  'tasks.solve': 600000, // 10 min — multi-turn tool use
  'update.run': 600000, // 10 min — IMAP sync + memory + task detection
  'narration.summarize': 60000 // Haiku is fast, but first-run model
  // downloads (fastembed, etc.) briefly block the sidecar asyncio loop
  // while a parallel chat.send initialises — 60s avoids spurious timeouts.
}

// windowId → { sidecar, profile }. Each BrowserWindow has its own sidecar
// bound to a specific profile. Lookup is driven by `event.sender` in IPC
// handlers so every RPC goes to the correct child process.
interface WindowEntry {
  sidecar: SidecarClient
  profile: string
  window: BrowserWindow
}
const windowEntries = new Map<number, WindowEntry>()

function listProfiles(): ProfileSummary[] {
  // Enumerate every subdirectory of ~/.zylch/profiles and resolve each
  // to a `{id, email}` summary. The id is the Firebase UID (dir name);
  // the email is read from the profile's `.env` so the UI can show a
  // human-friendly label. A missing / unreadable .env yields email=null
  // but the profile is still listed.
  try {
    return listProfilesWithEmail()
  } catch (e) {
    console.error('[main] listProfiles failed', e)
    return []
  }
}

function profileExistsById(id: string): boolean {
  return listProfiles().some((p) => p.id === id)
}

function spawnSidecar(profile: string, window: BrowserWindow): SidecarClient {
  // Reuse the "Continue with Google" Desktop OAuth client as the
  // default Calendar client ID. Same Cloud project (`talkmeapp-e696c`),
  // same Desktop type — Google accepts any 127.0.0.1 loopback redirect
  // for installed-app clients, so the existing client ID works for the
  // engine's :19275 Calendar flow without a separate Cloud Console
  // entry. The profile's own GOOGLE_CALENDAR_CLIENT_ID still wins via
  // pydantic when set; this only provides a fallback.
  const envOverrides: Record<string, string> = {}
  if (GOOGLE_SIGNIN_CLIENT_ID) {
    envOverrides['GOOGLE_CALENDAR_CLIENT_ID_DEFAULT'] = GOOGLE_SIGNIN_CLIENT_ID
  }
  // Google's token endpoint enforces client_secret for "Desktop app"
  // type OAuth clients even on PKCE — without it the Calendar token
  // exchange returns 400. The signin OAuth client is Desktop type, so
  // we inject the same secret as a default for the engine's Calendar
  // flow. The profile's GOOGLE_CALENDAR_CLIENT_SECRET wins via pydantic
  // when set (e.g. for users who configure a different OAuth client).
  if (GOOGLE_SIGNIN_CLIENT_SECRET) {
    envOverrides['GOOGLE_CALENDAR_CLIENT_SECRET_DEFAULT'] = GOOGLE_SIGNIN_CLIENT_SECRET
  }
  const sidecar = new SidecarClient({
    // Packaged builds don't need a specific cwd: the PyInstaller
    // binary is self-contained. In dev we keep the repo root so
    // relative imports still resolve if anything ever regresses.
    cwd: app.isPackaged ? process.resourcesPath : ZYLCH_CWD,
    binary: ZYLCH_BINARY,
    profile,
    envOverrides
  })
  sidecar.on('notification', (msg) => {
    console.log(`[main][w${window.id}] notification method=${msg.method}`)
    if (!window.isDestroyed()) {
      window.webContents.send('rpc:notification', msg)
    }
  })
  sidecar.on('stderr', (chunk: string) => {
    // Forward stderr only to the owning window, never broadcast.
    if (!window.isDestroyed()) {
      window.webContents.send('sidecar:stderr', chunk)
    }
  })
  sidecar.on('exit', (info: { code: number | null; signal: NodeJS.Signals | null; classified?: { code: string; message: string; hint?: string } }) => {
    console.error(`[main][w${window.id}] sidecar exited profile=${profile} code=${info?.code} signal=${info?.signal}`)
    // Push a structured status event to the renderer so the
    // SidecarStatusBanner can show a friendly explanation. We send the
    // classified error object verbatim (code/message/hint).
    if (!window.isDestroyed()) {
      const payload = {
        alive: false,
        profile,
        exitCode: info?.code ?? null,
        ...(info?.classified ?? sidecar.classifyError())
      }
      window.webContents.send('sidecar:status', payload)
    }
  })
  sidecar.start()
  // Push an "alive" status as soon as the child is spawned so the banner
  // can clear any prior error after a successful restart.
  setTimeout(() => {
    if (!window.isDestroyed() && sidecar.isAlive()) {
      window.webContents.send('sidecar:status', { alive: true, profile })
    }
  }, 100)
  return sidecar
}

// Resolver used by IPC handlers — `event.sender` is a WebContents.
function entryFromEvent(event: Electron.IpcMainInvokeEvent): WindowEntry | null {
  const win = BrowserWindow.fromWebContents(event.sender)
  if (!win) return null
  return windowEntries.get(win.id) ?? null
}

// Spawn a sidecar for an existing window and register it in
// windowEntries. Called by `auth:bindProfile` after Firebase signin
// attaches a sidecar to an auth-pending window in-place.
function attachSidecarToWindow(win: BrowserWindow, profile: string): SidecarClient {
  const sidecar = spawnSidecar(profile, win)
  const existing = windowEntries.get(win.id)
  if (existing) {
    // Should not happen — caller is expected to check first.
    console.warn(
      `[main][w${win.id}] attachSidecarToWindow called but window already has a sidecar (profile=${existing.profile}) — replacing`
    )
    try {
      existing.sidecar.stop()
    } catch {}
  }
  windowEntries.set(win.id, { sidecar, profile, window: win })
  if (!win.isDestroyed()) {
    win.setTitle(`MrCall Desktop — ${profile}`)
  }
  return sidecar
}

// Auth-pending window: created at boot, no sidecar yet. The renderer
// mounts FirebaseAuthGate; once the user signs in, the renderer asks
// main to attach a sidecar via `auth:bindProfile(uid)`. If the
// UID-keyed profile dir doesn't exist, the renderer shows the
// Onboarding wizard which creates it and then attaches.
//
// `win.on('closed')` is also registered here so that if the user
// closes the window before binding a sidecar, we clean up the (empty)
// entry — defensive, the entry won't exist yet but the listener stays.
function createAuthPendingWindow(emailHint?: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    show: false,
    title: 'MrCall Desktop — Sign in',
    icon: existsSync(ICON_PATH) ? ICON_PATH : undefined,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  win.on('ready-to-show', () => win.show())
  win.webContents.setWindowOpenHandler((d) => {
    shell.openExternal(d.url)
    return { action: 'deny' }
  })

  win.on('closed', () => {
    const entry = windowEntries.get(win.id)
    if (entry) {
      console.log(`[main][w${win.id}] auth-pending window closed, stopping sidecar`)
      entry.sidecar.stop()
      windowEntries.delete(win.id)
    }
  })

  // `?email=<hint>` lets the SignIn screen pre-fill the email input when
  // the window was opened from the "Other profiles" picker. The hint is
  // a convenience only — the actual profile binding happens after the
  // user signs in, keyed by the Firebase UID returned by Firebase Auth.
  const devUrl = process.env['ELECTRON_RENDERER_URL']
  const qs = emailHint ? `?email=${encodeURIComponent(emailHint)}` : ''
  if (devUrl) {
    win.loadURL(devUrl + qs)
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'), {
      query: emailHint ? { email: emailHint } : undefined
    })
  }
  return win
}

// Restart the sidecar bound to a specific window. Used after
// settings.update so the new .env values are picked up.
//
// Sequencing for the renderer:
//   1. Push `sidecar:status` { alive:false, code:'restarting' } so the
//      banner can show a small blue "Restarting sidecar…" indicator
//      BEFORE the old child dies (otherwise the exit handler would race
//      and the banner could briefly flash red).
//   2. Mark the old client as an intentional restart, then stop() it.
//      The exit handler in spawnSidecar() will see `intentionalRestart`
//      and emit a benign "restarting" status instead of "crashed" /
//      "profile_locked".
//   3. Spawn the new child. spawnSidecar() emits `alive:true` ~100ms
//      after spawn — the renderer treats that as the all-clear signal
//      and dismisses the "Restarting…" banner.
async function restartSidecarForWindow(win: BrowserWindow): Promise<boolean> {
  const entry = windowEntries.get(win.id)
  if (!entry) return false
  console.log(`[main][w${win.id}] restarting sidecar profile=${entry.profile}`)
  if (!win.isDestroyed()) {
    win.webContents.send('sidecar:status', {
      alive: false,
      profile: entry.profile,
      exitCode: null,
      code: 'restarting',
      message: 'Restarting sidecar…'
    })
  }
  entry.sidecar.markIntentionalRestart()
  entry.sidecar.stop()
  await new Promise((r) => setTimeout(r, 500))
  const sidecar = spawnSidecar(entry.profile, win)
  windowEntries.set(win.id, { ...entry, sidecar })
  await new Promise((r) => setTimeout(r, 500))
  return true
}

function buildAppMenu(): void {
  const isMac = process.platform === 'darwin'
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac
      ? ([{ role: 'appMenu' as const }] as Electron.MenuItemConstructorOptions[])
      : []),
    {
      label: 'File',
      submenu: [
        {
          label: 'New Window for Profile...',
          accelerator: 'CmdOrCtrl+N',
          click: () => {
            // Ask the focused window's renderer to show the picker UI.
            const target =
              BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
            if (target && !target.isDestroyed()) {
              target.webContents.send('menu:openProfilePicker')
            }
          }
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' }
      ]
    },
    { role: 'editMenu' },
    { role: 'viewMenu' },
    { role: 'windowMenu' }
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

function registerIpc(): void {
  ipcMain.handle('rpc:call', async (event, method: string, params: unknown, timeout?: number) => {
    const entry = entryFromEvent(event)
    if (!entry) {
      throw new Error('no sidecar for this window')
    }
    const effective = timeout ?? METHOD_TIMEOUTS[method] ?? 60000
    try {
      return await entry.sidecar.call(method, params, effective)
    } catch (e) {
      // If the sidecar is dead, decorate the error with the classified
      // reason (e.g. "Profile X is already in use ...") instead of the
      // bare "sidecar not running" / "sidecar exited" string. The
      // renderer surfaces this verbatim.
      if (!entry.sidecar.isAlive()) {
        const cls = entry.sidecar.classifyError()
        const err = new Error(cls.message)
        ;(err as any).code = cls.code
        ;(err as any).hint = cls.hint
        throw err
      }
      throw e
    }
  })

  // Returns the profile this window's sidecar was spawned with as
  // `{id, email}`. `id` is the on-disk directory name (Firebase UID);
  // `email` is read from the profile's `.env` so the UI never has to
  // surface a raw UID.
  ipcMain.handle(
    'profile:current',
    async (event): Promise<ProfileSummary> => {
      const entry = entryFromEvent(event)
      const id = entry?.profile ?? ''
      if (!id) return { id: '', email: null }
      return { id, email: readProfileEnvValue(id, 'EMAIL_ADDRESS') }
    }
  )

  // Enumerate profiles by reading ~/.zylch/profiles/. Each entry carries
  // `{id, email}` so the picker can render a friendly label without
  // every renderer reinventing .env parsing.
  ipcMain.handle(
    'profiles:list',
    async (): Promise<ProfileSummary[]> => listProfiles()
  )

  // Open a fresh auth-pending window. Empty `profile` opens with no
  // SignIn pre-fill ("+ Sign in to another account"); a non-empty
  // `profile` is a profile dir id whose email is used to pre-fill the
  // SignIn input. Either way, the actual profile binding happens after
  // the user signs in, via `auth:bindProfile(uid)`. The signed-in UID —
  // not the picker selection — drives which profile dir gets attached,
  // so the picker can never short-circuit Firebase identity verification.
  ipcMain.handle('window:openForProfile', async (_event, profile: string): Promise<{ ok: boolean }> => {
    if (typeof profile !== 'string') return { ok: false }
    if (!profile) {
      createAuthPendingWindow()
      return { ok: true }
    }
    const entry = listProfiles().find((p) => p.id === profile)
    if (!entry) {
      console.warn(`[main] window:openForProfile unknown profile=${profile}`)
      return { ok: false }
    }
    createAuthPendingWindow(entry.email || undefined)
    return { ok: true }
  })

  // File picker for chat attachments. Returns absolute paths (possibly empty
  // if the user cancelled). Scoped to the originating window so the dialog
  // appears as modal over the correct parent.
  ipcMain.handle('dialog:selectFiles', async (event): Promise<string[]> => {
    const win = BrowserWindow.fromWebContents(event.sender)
    if (!win) return []
    const result = await dialog.showOpenDialog(win, {
      properties: ['openFile', 'multiSelections']
    })
    if (result.canceled) return []
    return result.filePaths
  })

  // Folder picker for settings fields that hold a list of directories
  // (e.g. DOCUMENT_PATHS). Multi-select so the user can pick several at once.
  ipcMain.handle('dialog:selectDirectories', async (event): Promise<string[]> => {
    const win = BrowserWindow.fromWebContents(event.sender)
    if (!win) return []
    const result = await dialog.showOpenDialog(win, {
      properties: ['openDirectory', 'multiSelections']
    })
    if (result.canceled) return []
    return result.filePaths
  })

  // Bind the originating window to a profile keyed by the Firebase UID.
  // Path: renderer's FirebaseAuthGate observes signin, calls this with
  // the UID. We check the on-disk profile dir; if it exists, we attach
  // a sidecar to the current window (in-place — same renderer context,
  // same auth state). If it doesn't exist, we return found=false and
  // the renderer routes to Onboarding, which after createProfile will
  // call this same IPC.
  //
  // Idempotent: if the window already has a sidecar bound to the same
  // profile, returns immediately. If bound to a DIFFERENT profile, we
  // refuse — the caller should open a new window.
  ipcMain.handle(
    'auth:bindProfile',
    async (
      event,
      uid: string
    ): Promise<{ ok: boolean; found: boolean; reason?: string }> => {
      const win = BrowserWindow.fromWebContents(event.sender)
      if (!win) return { ok: false, found: false, reason: 'no window' }
      const trimmed = (uid || '').trim()
      if (!trimmed) return { ok: false, found: false, reason: 'empty uid' }
      const dir = profileDir(trimmed)
      let exists = false
      try {
        exists = statSync(dir).isDirectory()
      } catch {
        exists = false
      }
      if (!exists) {
        console.log(`[main][w${win.id}] auth:bindProfile uid=${trimmed} → not found`)
        return { ok: true, found: false }
      }
      const existing = windowEntries.get(win.id)
      if (existing) {
        if (existing.profile === trimmed) {
          console.log(
            `[main][w${win.id}] auth:bindProfile uid=${trimmed} → already bound, no-op`
          )
          return { ok: true, found: true }
        }
        // Different profile (signOut → re-signin as another user, or
        // the same window cycling through accounts). Drop the old
        // sidecar and attach a fresh one. The user has explicitly
        // signed out of the old identity, so abandoning in-flight ops
        // is the correct semantic.
        console.log(
          `[main][w${win.id}] auth:bindProfile uid=${trimmed} → swapping sidecar (was profile=${existing.profile})`
        )
        try {
          existing.sidecar.markIntentionalRestart()
          existing.sidecar.stop()
        } catch (e) {
          console.warn(`[main][w${win.id}] failed to stop old sidecar`, e)
        }
        windowEntries.delete(win.id)
      } else {
        console.log(
          `[main][w${win.id}] auth:bindProfile uid=${trimmed} → attaching sidecar`
        )
      }
      attachSidecarToWindow(win, trimmed)
      return { ok: true, found: true }
    }
  )

  // Onboarding: create a profile directly on disk. Does NOT involve the
  // sidecar — called from the first-run window where no sidecar exists
  // yet. Mirrors the server-side `profiles.create` semantics.
  ipcMain.handle(
    'onboarding:createProfile',
    async (
      _event,
      email: string,
      values: Record<string, string>
    ): Promise<{ ok: true; profile: string } | { ok: false; error: string }> => {
      try {
        const r = createProfileFS(email, values)
        console.log(
          `[main] onboarding:createProfile ok profile=${r.profile} keys=${JSON.stringify(
            Object.keys(values).sort()
          )}`
        )
        return { ok: true, profile: r.profile }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        console.error(`[main] onboarding:createProfile failed: ${msg}`)
        return { ok: false, error: msg }
      }
    }
  )

  // Firebase-aware onboarding. Same shape as createProfile, but the
  // resulting profile directory is named after the Firebase UID
  // (immutable across email changes) and the .env carries OWNER_ID +
  // EMAIL_ADDRESS so the engine binds its owner-scoped storage to
  // the same identifier the renderer pushes via account.set_firebase_token.
  ipcMain.handle(
    'onboarding:createProfileForFirebaseUser',
    async (
      _event,
      uid: string,
      email: string,
      values: Record<string, string>
    ): Promise<{ ok: true; profile: string } | { ok: false; error: string }> => {
      try {
        const r = createProfileForFirebaseUser(uid, email, values)
        console.log(
          `[main] onboarding:createProfileForFirebaseUser ok profile=${r.profile} email=${email}`
        )
        return { ok: true, profile: r.profile }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        console.error(`[main] onboarding:createProfileForFirebaseUser failed: ${msg}`)
        return { ok: false, error: msg }
      }
    }
  )

  // Onboarding: attach the just-created profile to the originating
  // window in-place. Replaces the older "spawn new window + close old"
  // dance — that path destroyed the renderer context and lost the
  // Firebase auth state, forcing the user to sign in twice. With
  // in-place attach, the same renderer keeps `auth.currentUser` alive
  // across the transition from Onboarding → AppInner.
  //
  // Equivalent to `auth:bindProfile(profile)` for newly-created
  // profiles where the dir is guaranteed to exist; kept under the
  // `onboarding:` namespace for call-site clarity at the wizard.
  ipcMain.handle(
    'onboarding:finalize',
    async (event, profile: string): Promise<{ ok: boolean }> => {
      const win = BrowserWindow.fromWebContents(event.sender)
      if (!win) return { ok: false }
      if (typeof profile !== 'string' || !profile.trim()) return { ok: false }
      const trimmed = profile.trim()
      const existing = windowEntries.get(win.id)
      if (existing) {
        if (existing.profile === trimmed) return { ok: true }
        console.warn(
          `[main][w${win.id}] onboarding:finalize refused: window bound to profile=${existing.profile}`
        )
        return { ok: false }
      }
      try {
        attachSidecarToWindow(win, trimmed)
        return { ok: true }
      } catch (e) {
        console.error('[main] onboarding:finalize failed', e)
        return { ok: false }
      }
    }
  )

  // Open a URL in the user's default browser. The renderer uses this
  // for Google Calendar OAuth consent (and any future link-out) — we
  // deliberately do NOT load the URL inside a BrowserWindow because
  // Google's consent flow needs the user's system password manager and
  // 2FA prompts, which only work in a real browser.
  ipcMain.handle(
    'shell:openExternal',
    async (_event, url: string): Promise<{ ok: boolean }> => {
      if (typeof url !== 'string' || !url) return { ok: false }
      // Defence in depth: only allow http(s) URLs. The renderer
      // should never have a reason to ask for file:// or chrome://.
      let parsed: URL
      try {
        parsed = new URL(url)
      } catch {
        return { ok: false }
      }
      if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
        return { ok: false }
      }
      try {
        await shell.openExternal(url)
        return { ok: true }
      } catch (e) {
        console.error('[main] shell.openExternal failed', e)
        return { ok: false }
      }
    }
  )

  // "Continue with Google" on the SignIn screen. Runs entirely in main
  // process — there's no sidecar in onboarding mode, so we can't
  // delegate to the engine the way post-signin Calendar OAuth does.
  // The result `idToken` is a Google id_token; the renderer feeds it
  // into Firebase via `signInWithCredential(GoogleAuthProvider.credential(idToken))`.
  ipcMain.handle(
    'signin:googleStart',
    async (): Promise<{
      ok: boolean
      idToken?: string
      email?: string | null
      error?: string
    }> => {
      if (!GOOGLE_SIGNIN_CLIENT_ID) {
        return {
          ok: false,
          error:
            'Google sign-in is not configured. Set GOOGLE_SIGNIN_CLIENT_ID before launching the app (see docs/execution-plans/google-signin.md).'
        }
      }
      try {
        const result = await startGoogleSignin({
          clientId: GOOGLE_SIGNIN_CLIENT_ID,
          clientSecret: GOOGLE_SIGNIN_CLIENT_SECRET,
          onAuthUrl: (url) => {
            // Opening in the system browser keeps password manager / 2FA
            // affordances. Failures here are non-fatal — the user can
            // still copy the URL out of the log if needed; the loopback
            // server stays up either way.
            shell.openExternal(url).catch((e) => {
              console.error('[main] shell.openExternal failed for google signin', e)
            })
          }
        })
        console.log(
          `[main] signin:googleStart ok email=${result.email ?? '(unknown)'}`
        )
        return { ok: true, idToken: result.idToken, email: result.email }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        console.error('[main] signin:googleStart failed:', msg)
        return { ok: false, error: msg }
      }
    }
  )

  // Renderer can abort an in-flight Google signin (e.g. user closed the
  // browser tab without consenting and clicked Cancel). Releases :19276.
  ipcMain.handle('signin:googleCancel', async (): Promise<{ cancelled: boolean }> => {
    return { cancelled: cancelGoogleSignin() }
  })

  // Restart the sidecar bound to the originating window (called after
  // settings.update so new .env values are loaded).
  ipcMain.handle('sidecar:restart', async (event): Promise<{ ok: boolean }> => {
    const win = BrowserWindow.fromWebContents(event.sender)
    if (!win) return { ok: false }
    try {
      const ok = await restartSidecarForWindow(win)
      return { ok }
    } catch (e) {
      console.error('[main] sidecar restart failed', e)
      return { ok: false }
    }
  })
}

function bootFirstWindow(): void {
  // Every window starts in auth-pending mode (no sidecar). The
  // renderer's FirebaseAuthGate forces Firebase signin, then asks main
  // to bind a sidecar to the profile dir keyed by the signed-in UID. If
  // no such profile exists, the renderer routes to the onboarding
  // wizard which creates it and binds in-place.
  //
  // Profile selection is therefore a function of the signed-in Firebase
  // identity, not of any disk-order or env-var hint — that's how we
  // guarantee "I signed in as X" and "I see X's data" can never disagree.
  console.log('[main] booting in auth-pending mode')
  createAuthPendingWindow()
}

app.whenReady().then(() => {
  ZYLCH_BINARY = resolveSidecarBinary()
  console.log(`[main] sidecar binary=${ZYLCH_BINARY} isPackaged=${app.isPackaged}`)

  // Override the Dock / Cmd-Tab icon in dev. Without this, macOS shows the
  // Electron.app bundle icon because dev mode runs from
  // node_modules/electron/dist/. In packaged builds the system reads the
  // .icns from Contents/Resources directly — no override needed.
  if (process.platform === 'darwin' && !app.isPackaged && app.dock && existsSync(ICON_PATH)) {
    try {
      app.dock.setIcon(nativeImage.createFromPath(ICON_PATH))
    } catch (e) {
      console.warn('[main] failed to set dock icon:', e)
    }
  }

  registerIpc()
  buildAppMenu()
  bootFirstWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      bootFirstWindow()
    }
  })
})

app.on('window-all-closed', () => {
  // Kill any residual sidecars (should be empty because window.on('closed')
  // already stopped each one, but defensive).
  for (const [, entry] of windowEntries) {
    try {
      entry.sidecar.stop()
    } catch {}
  }
  windowEntries.clear()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  for (const [, entry] of windowEntries) {
    try {
      entry.sidecar.stop()
    } catch {}
  }
  windowEntries.clear()
})
