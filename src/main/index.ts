import { app, BrowserWindow, dialog, ipcMain, Menu, shell } from 'electron'
import { join } from 'path'
import { readdirSync, statSync, existsSync } from 'fs'
import { homedir } from 'os'
import { SidecarClient } from './sidecar'

const ZYLCH_CWD = process.env.ZYLCH_CWD || '/path/to/engine'
const ZYLCH_BINARY = process.env.ZYLCH_BINARY || join(ZYLCH_CWD, 'venv/bin/zylch')
const DEFAULT_PROFILE = process.env.ZYLCH_PROFILE || 'user@example.com'

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

function listProfiles(): string[] {
  const dir = join(homedir(), '.zylch', 'profiles')
  if (!existsSync(dir)) return []
  try {
    const names = readdirSync(dir).sort()
    const out: string[] = []
    for (const name of names) {
      const profileDir = join(dir, name)
      const envPath = join(profileDir, '.env')
      try {
        if (statSync(profileDir).isDirectory() && statSync(envPath).isFile()) {
          out.push(name)
        }
      } catch {
        // skip non-dirs or missing .env
      }
    }
    return out
  } catch (e) {
    console.error('[main] listProfiles failed', e)
    return []
  }
}

function spawnSidecar(profile: string, window: BrowserWindow): SidecarClient {
  const sidecar = new SidecarClient({
    cwd: ZYLCH_CWD,
    binary: ZYLCH_BINARY,
    profile
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
  sidecar.on('exit', () => {
    console.error(`[main][w${window.id}] sidecar exited profile=${profile}`)
  })
  sidecar.start()
  return sidecar
}

// Resolver used by IPC handlers — `event.sender` is a WebContents.
function entryFromEvent(event: Electron.IpcMainInvokeEvent): WindowEntry | null {
  const win = BrowserWindow.fromWebContents(event.sender)
  if (!win) return null
  return windowEntries.get(win.id) ?? null
}

function createWindowForProfile(profile: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    show: false,
    title: `Zylch — ${profile}`,
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

  // Spawn a sidecar for this window BEFORE loading the renderer so that
  // early rpc:call invocations can find the mapping. stderr and
  // notifications are routed only to this window's webContents.
  const sidecar = spawnSidecar(profile, win)
  windowEntries.set(win.id, { sidecar, profile, window: win })

  win.on('closed', () => {
    const entry = windowEntries.get(win.id)
    if (entry) {
      console.log(`[main][w${win.id}] window closed, stopping sidecar`)
      entry.sidecar.stop()
      windowEntries.delete(win.id)
    }
  })

  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (devUrl) {
    win.loadURL(devUrl)
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
  return win
}

// Restart the sidecar bound to a specific window. Used after
// settings.update so the new .env values are picked up.
async function restartSidecarForWindow(win: BrowserWindow): Promise<boolean> {
  const entry = windowEntries.get(win.id)
  if (!entry) return false
  console.log(`[main][w${win.id}] restarting sidecar profile=${entry.profile}`)
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
    return entry.sidecar.call(method, params, effective)
  })

  // Returns the profile this window's sidecar was spawned with.
  ipcMain.handle('profile:current', async (event): Promise<string> => {
    const entry = entryFromEvent(event)
    return entry?.profile ?? ''
  })

  // Enumerate profiles by reading ~/.zylch/profiles/.
  ipcMain.handle('profiles:list', async (): Promise<string[]> => listProfiles())

  // Open a new BrowserWindow bound to a profile. If the profile is already
  // in use by another sidecar (CLI or another window), the new sidecar
  // exits fast and the window's renderer will display "Profile already in
  // use" when subsequent rpc:calls fail. We do not pre-check here because
  // the lock file is authoritative on the Python side.
  ipcMain.handle('window:openForProfile', async (_event, profile: string): Promise<{ ok: boolean }> => {
    if (typeof profile !== 'string' || !profile) return { ok: false }
    if (!listProfiles().includes(profile)) {
      console.warn(`[main] window:openForProfile unknown profile=${profile}`)
      return { ok: false }
    }
    createWindowForProfile(profile)
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

app.whenReady().then(() => {
  registerIpc()
  buildAppMenu()
  createWindowForProfile(DEFAULT_PROFILE)
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindowForProfile(DEFAULT_PROFILE)
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
