/** Redacted desktop-to-workspace handoff. Descriptor contents stay in main. */
import { readFileSync } from 'fs'
import { join } from 'path'
import { profileDir } from './profileFS'
import { engineWsUrlFor } from './csDescriptor'

export type WorkspaceStatus =
  | {
      available: true
      uid: string
      email: string
      engineWsUrl: string
      descriptorPath: string
      command: string
    }
  | { available: false; reason: string }

/** Quote a single literal argument for the terminal the user will open. */
export function workspaceCommand(path: string, platform = process.platform): string {
  if (platform === 'win32') {
    return `cs init --descriptor '${path.replace(/'/g, "''")}'`
  }
  return `cs init --descriptor '${path.replace(/'/g, "'\"'\"'")}'`
}

/** No RPC, token exchange, descriptor writes, or secret-bearing error output. */
export function readWorkspaceStatus(
  uid: string,
  expectedUrl = engineWsUrlFor(uid),
  path = join(profileDir(uid), 'cs-descriptor.json'),
  platform = process.platform
): WorkspaceStatus {
  let data: Record<string, unknown>
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'))
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
    data = parsed as Record<string, unknown>
  } catch {
    return {
      available: false,
      reason: 'Workspace access is not available yet. Refresh your sign-in, then check again.'
    }
  }

  const required = ['email', 'uid', 'engine_ws_url', 'firebase_web_api_key', 'refresh_token']
  if (
    data.version !== 1 ||
    required.some((key) => typeof data[key] !== 'string' || !(data[key] as string).trim())
  ) {
    return {
      available: false,
      reason: 'Workspace access is incomplete. Refresh your sign-in to recreate it, then check again.'
    }
  }
  if (data.uid !== uid) {
    return {
      available: false,
      reason: 'Workspace access belongs to a different account. Sign in with this profile again.'
    }
  }
  if ((data.engine_ws_url as string).replace(/\/+$/, '') !== expectedUrl.replace(/\/+$/, '')) {
    return {
      available: false,
      reason: 'Workspace access points to a previous engine. Refresh your sign-in after choosing the engine, then check again.'
    }
  }

  // Deliberately construct the response field by field, never spread the file.
  return {
    available: true,
    uid,
    email: data.email as string,
    engineWsUrl: expectedUrl,
    descriptorPath: path,
    command: workspaceCommand(path, platform)
  }
}
