import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { join } from 'path'
import { SidecarClient } from './sidecar'

const ZYLCH_CWD = process.env.ZYLCH_CWD || '/path/to/engine'
const ZYLCH_BINARY = process.env.ZYLCH_BINARY || join(ZYLCH_CWD, 'venv/bin/zylch')
const ZYLCH_PROFILE = process.env.ZYLCH_PROFILE || 'user@example.com'

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
  sidecar.on('exit', () => {
    console.error('[main] sidecar exited')
  })
  sidecar.start()
}

function registerIpc(): void {
  ipcMain.handle('rpc:call', async (_e, method: string, params: unknown, timeout?: number) => {
    if (!sidecar) throw new Error('sidecar not started')
    return sidecar.call(method, params, timeout ?? 60000)
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
