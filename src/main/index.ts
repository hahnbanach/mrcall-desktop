import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { join } from 'path'
import { SidecarClient } from './sidecar'

const ZYLCH_CWD = process.env.ZYLCH_CWD || '/home/mal/private/zylch-standalone'
const ZYLCH_BINARY = process.env.ZYLCH_BINARY || join(ZYLCH_CWD, 'venv/bin/zylch')
const ZYLCH_PROFILE = process.env.ZYLCH_PROFILE || 'mario.alemi@cafe124.it'

let sidecar: SidecarClient | null = null
let mainWindow: BrowserWindow | null = null

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    show: false,
    title: 'Zylch',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  mainWindow.on('ready-to-show', () => mainWindow?.show())
  mainWindow.webContents.setWindowOpenHandler((d) => {
    shell.openExternal(d.url)
    return { action: 'deny' }
  })

  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (devUrl) {
    mainWindow.loadURL(devUrl)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

function startSidecar(): void {
  sidecar = new SidecarClient({
    cwd: ZYLCH_CWD,
    binary: ZYLCH_BINARY,
    profile: ZYLCH_PROFILE
  })
  sidecar.on('notification', (msg) => {
    console.log(`[main] notification method=${msg.method}`)
    mainWindow?.webContents.send('rpc:notification', msg)
  })
  sidecar.on('stderr', (chunk: string) => {
    mainWindow?.webContents.send('sidecar:stderr', chunk)
  })
  sidecar.on('exit', () => {
    console.error('[main] sidecar exited')
  })
  sidecar.start()
}

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

function registerIpc(): void {
  ipcMain.handle('rpc:call', async (_e, method: string, params: unknown, timeout?: number) => {
    if (!sidecar) throw new Error('sidecar not started')
    const effective = timeout ?? METHOD_TIMEOUTS[method] ?? 60000
    return sidecar.call(method, params, effective)
  })

  // Returns the active profile email so the renderer can derive its accent
  // colour and window title. Falls back to whatever ZYLCH_PROFILE was set to
  // when the main process started (same constant used to spawn the sidecar).
  ipcMain.handle('profile:current', async (): Promise<string> => ZYLCH_PROFILE)

  // File picker for chat attachments. Returns absolute paths (possibly empty
  // if the user cancelled). Electron resolves paths already.
  ipcMain.handle('dialog:selectFiles', async (): Promise<string[]> => {
    if (!mainWindow) return []
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openFile', 'multiSelections']
    })
    if (result.canceled) return []
    return result.filePaths
  })
}

app.whenReady().then(() => {
  registerIpc()
  startSidecar()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  sidecar?.stop()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  sidecar?.stop()
})
