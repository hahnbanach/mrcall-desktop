import { indexedDBLocalPersistence, type Persistence } from 'firebase/auth'

type StoredValue = Record<string, unknown> | string
type IndexedPersistence = Persistence & {
  _isAvailable(): Promise<boolean>
  _set(key: string, value: StoredValue): Promise<void>
  _get<T extends StoredValue>(key: string): Promise<T | null>
  _withRetries<T>(operation: (db: IDBDatabase) => Promise<T>): Promise<T>
  localCache: Record<string, StoredValue | null>
}

// Firebase exposes the persistence constructor through its public Persistence
// type. Retain its database, retries, listener polling and partition isolation.
const IndexedPersistence = indexedDBLocalPersistence as unknown as new () => IndexedPersistence
const STORE = 'firebaseLocalStorage'
const userFields = ['email', 'displayName', 'photoURL', 'phoneNumber', 'tenantId',
  '_redirectEventId', 'createdAt', 'lastLoginAt', 'apiKey', 'appName'] as const
const providerFields = ['uid', 'providerId', 'displayName', 'email', 'phoneNumber', 'photoURL'] as const
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)

function filtered(key: unknown, value: unknown): StoredValue | null {
  if (typeof key !== 'string') return null
  if (key.startsWith('firebase:persistence:')) {
    return value === 'LOCAL' || value === 'SESSION' || value === 'NONE' ? value : null
  }
  const prefix = ['firebase:authUser:', 'firebase:redirectUser:'].find(prefix => key.startsWith(prefix))
  if (!prefix || !object(value) || typeof value.uid !== 'string' || !value.uid
      || typeof value.emailVerified !== 'boolean' || typeof value.isAnonymous !== 'boolean'
      || !object(value.stsTokenManager) || typeof value.stsTokenManager.refreshToken !== 'string'
      || !value.stsTokenManager.refreshToken || typeof value.apiKey !== 'string'
      || typeof value.appName !== 'string' || key !== prefix + value.apiKey + ':' + value.appName) return null
  const clean: Record<string, unknown> = {
    uid: value.uid, emailVerified: value.emailVerified, isAnonymous: value.isAnonymous,
    stsTokenManager: { refreshToken: value.stsTokenManager.refreshToken }
  }
  for (const name of userFields) {
    if (value[name] !== undefined && value[name] !== null) {
      if (typeof value[name] !== 'string') return null
      clean[name] = value[name]
    }
  }
  if (!Array.isArray(value.providerData)) return null
  const providers: Record<string, unknown>[] = []
  clean.providerData = providers
  for (const provider of value.providerData) {
    if (!object(provider)) return null
    const info: Record<string, unknown> = {}
    for (const name of providerFields) {
      if (provider[name] !== undefined && provider[name] !== null) {
        if (typeof provider[name] !== 'string') return null
        info[name] = provider[name]
      }
    }
    providers.push(info)
  }
  return clean
}

function scrub(db: IDBDatabase, key?: string): Promise<StoredValue | null> {
  // Read and replace within one transaction. A delayed migration must never
  // resurrect a session deleted by logout in another renderer.
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, 'readwrite')
    const request = transaction.objectStore(STORE).openCursor(key)
    let result: StoredValue | null = null
    transaction.oncomplete = () => resolve(result)
    transaction.onerror = transaction.onabort = () => reject(new Error('Firebase session storage unavailable'))
    request.onsuccess = () => {
      const cursor = request.result
      if (!cursor) return
      const row = cursor.value
      const clean = filtered(row.fbase_key, row.value)
      if (clean === null) cursor.delete()
      else if (JSON.stringify(clean) !== JSON.stringify(row.value)) cursor.update({ fbase_key: row.fbase_key, value: clean })
      if (key !== undefined) result = clean
      cursor.continue()
    }
  })
}

/** Durable refresh credentials; short-lived Firebase ID tokens remain in memory. */
export class RefreshOnlyPersistence extends IndexedPersistence {
  static readonly type = 'LOCAL'

  async _isAvailable(): Promise<boolean> {
    if (!await super._isAvailable()) return false
    // Remove historical ID tokens from every auth row in this partition before
    // the SDK restores any user. Unknown/malformed rows are never adopted.
    await this._withRetries(db => scrub(db))
    return true
  }

  async _set(key: string, value: StoredValue): Promise<void> {
    const clean = filtered(key, value)
    if (clean === null) throw new Error('Invalid persisted Firebase session')
    await super._set(key, clean)
  }

  async _get<T extends StoredValue>(key: string): Promise<T | null> {
    const clean = await this._withRetries(db => scrub(db, key))
    this.localCache[key] = clean
    return clean as T | null
  }
}
