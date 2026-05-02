#!/usr/bin/env node
/**
 * Patch the dev Electron.app bundle so that macOS Cmd-Tab and the
 * bold menu-bar app name read "MrCall Desktop" instead of "Electron".
 *
 * Why this exists: in dev, `npm run dev` launches the renderer through
 * node_modules/electron/dist/Electron.app, and macOS reads the visible
 * application name from that bundle's Info.plist (CFBundleName +
 * CFBundleDisplayName). `app.setName()` at runtime does NOT change
 * Cmd-Tab or the menu-bar bold name — those are bundle-level. Packaged
 * builds are unaffected because electron-builder generates a separate
 * "MrCall Desktop.app" bundle with the right Info.plist.
 *
 * Run via npm `postinstall`. Idempotent — safe to re-run after every
 * `npm install` / `npm ci`. After a fresh patch, macOS may need
 * `killall Dock` (or a logout/login) to refresh its launch-services
 * cache; this script prints the hint when it actually changed something.
 *
 * No Linux/Windows action needed — those platforms read the running
 * process name, which `app.setName()` already covers.
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const APP_NAME = 'MrCall Desktop'

if (process.platform !== 'darwin') {
  // Cmd-Tab branding only matters on macOS. On Linux/Windows the launcher
  // reads from the running process / .desktop / shortcut, which other
  // mechanisms already cover.
  process.exit(0)
}

const bundleRoot = resolve(__dirname, '..', 'node_modules', 'electron', 'dist', 'Electron.app')
if (!existsSync(bundleRoot)) {
  console.warn(
    `[patch-electron-name] Electron.app not found at ${bundleRoot} — skipping. ` +
      `Run \`npm install\` first.`
  )
  process.exit(0)
}

// Only the top-level bundle drives Cmd-Tab + menu-bar. Helper bundles
// (Renderer / GPU / Plugin) show in Activity Monitor only — patching
// them is cosmetic and risky, skip.
const plistPath = resolve(bundleRoot, 'Contents', 'Info.plist')
if (!existsSync(plistPath)) {
  console.warn(`[patch-electron-name] Info.plist not found at ${plistPath} — skipping.`)
  process.exit(0)
}

const original = readFileSync(plistPath, 'utf8')

/**
 * Replace the <string>VALUE</string> that immediately follows a
 * <key>NAME</key> entry. Whitespace-tolerant. Returns the new content
 * (or the input unchanged if the key wasn't found / already correct).
 */
function setPlistString(content, key, newValue) {
  const re = new RegExp(
    `(<key>${key}</key>\\s*<string>)([^<]*)(</string>)`,
    'g'
  )
  return content.replace(re, (_m, open, _old, close) => `${open}${newValue}${close}`)
}

let patched = original
patched = setPlistString(patched, 'CFBundleName', APP_NAME)
patched = setPlistString(patched, 'CFBundleDisplayName', APP_NAME)
// Don't touch CFBundleExecutable — it names the actual binary file
// inside Contents/MacOS/, renaming it would prevent the bundle from
// launching.

if (patched === original) {
  console.log(`[patch-electron-name] Info.plist already shows "${APP_NAME}" — no change.`)
  process.exit(0)
}

writeFileSync(plistPath, patched, 'utf8')
console.log(`[patch-electron-name] Patched ${plistPath}`)
console.log(
  '[patch-electron-name] On macOS, run `killall Dock` once if Cmd-Tab still shows the old name.'
)
