// Mailboxes UI with fake RPCs: the Settings MailboxesCard and the Email
// view's mailbox chip, filter and archive rollback. No engine, browser or
// network. Test dependencies: see test-preparation.mjs (react +
// react-test-renderer under MRCALL_UI_TEST_DEPS). Run from app/ or the root.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import Module, { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const appRequire = createRequire(path.join(here, '../package.json'))
const testRequire = createRequire(
  path.join(process.env.MRCALL_UI_TEST_DEPS ?? '/tmp/mrcall-preparation-ui-tests', 'package.json')
)
const ts = appRequire('typescript')
const React = testRequire('react')
const { create, act } = testRequire('react-test-renderer')
const auth = { currentUser: { uid: 'account-A', email: 'owner@example.test' } }
const invalidators = new Set()
const empty = () => null
function load(relative, extra = '') {
  const file = path.join(here, '../src/renderer/src', relative)
  const mod = new Module(file)
  mod.require = (name) => {
    if (name === 'firebase/auth') return { onAuthStateChanged: () => () => {} }
    if (!name.startsWith('.')) return testRequire(name)
    if (name.endsWith('/config')) return { auth }
    if (name.endsWith('/authUtils')) return { ensureEngineSession: async () => true, onAuthSessionInvalidated: (fn) => { invalidators.add(fn); return () => invalidators.delete(fn) }, isAuthSessionActive: () => true }
    if (name.endsWith('/errors')) return { errorMessage: String, isProfileLockedError: () => false }
    if (name.endsWith('/lib/mailboxes')) return { MAILBOXES_CHANGED_EVENT: 'mrcall:mailboxes-changed' }
    if (name.endsWith('/store/thread')) return { useThread: () => ({ setTaskThreadFilter() {} }) }
    return { default: empty }
  }
  mod._compile(
    ts.transpileModule(fs.readFileSync(file, 'utf8') + extra, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 }
    }).outputText,
    file
  )
  return mod.exports
}

// Browser globals the Email view touches outside React.
global.document = { addEventListener() {}, removeEventListener() {}, activeElement: null }
global.requestAnimationFrame = (fn) => fn()
global.CSS = { escape: (s) => s }

const primary = {
  id: 'mb-primary', address: 'owner@example.test', imap_host: 'imap.example.test', imap_port: 993,
  smtp_host: 'smtp.example.test', smtp_port: 587, preset: null, is_primary: true, configured: true,
  state: 'ok', last_sync_at: '2026-09-30T08:00:00', last_error: null, created_at: '2026-09-01T00:00:00'
}
const pec = {
  id: 'mb-pec', address: 'pec@pec.net', imap_host: 'imap.pec-email.com', imap_port: 993,
  smtp_host: 'smtp.pec-email.com', smtp_port: 465, preset: 'pec.net', is_primary: false, configured: true,
  state: 'error', last_sync_at: null, last_error: 'pec@pec.net: the server refused the login', created_at: '2026-09-30T00:00:00'
}
const presets = [
  { id: 'gmail.com', label: 'gmail.com', domains: ['gmail.com', 'googlemail.com'], imap_host: 'imap.gmail.com', imap_port: 993, imap_security: 'ssl', smtp_host: 'smtp.gmail.com', smtp_port: 587, smtp_security: 'starttls', username: 'full_address', password_label: 'App password' },
  { id: 'pec.net', label: 'PEC.net (Register.it)', domains: ['pec.net'], imap_host: 'imap.pec-email.com', imap_port: 993, imap_security: 'ssl', smtp_host: 'smtp.pec-email.com', smtp_port: 465, smtp_security: 'ssl', username: 'full_address', password_label: 'PEC mailbox password' }
]
let listed = [primary, pec]
let testAnswer = { ok: false, status: 'auth', message: 'the server rejected the username or password' }
const calls = { test: [], add: [], update: [], remove: [], listInbox: [], listSent: [], search: [], archive: [] }
const sidecar = new Set()
const listeners = new Map()
global.window = {
  addEventListener: (name, fn) => { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn) },
  removeEventListener: (name, fn) => { listeners.get(name)?.delete(fn) },
  dispatchEvent: (event) => { for (const fn of listeners.get(event.type) ?? []) fn(event); return true },
  zylch: {
    onSidecarStatus: (fn) => { sidecar.add(fn); return () => sidecar.delete(fn) },
    mailboxes: {
      list: async () => ({ mailboxes: listed }),
      presets: async () => ({ presets }),
      test: async (p) => { calls.test.push(p); return await testAnswer },
      add: async (p) => { calls.add.push(p); listed = [...listed, { ...pec, id: 'mb-new', address: p.address, state: 'never', last_error: null }]; return { ok: true, status: 'ok', mailbox: listed[listed.length - 1] } },
      update: async (p) => { calls.update.push(p); return { ok: false, status: 'unreachable', message: 'imap.pec-email.com:9993: connection refused' } },
      remove: async (id) => { calls.remove.push(id); listed = listed.filter((m) => m.id !== id); return { ok: true, status: 'ok' } }
    }
  }
}

let view
const text = () => JSON.stringify(view.toJSON())
const buttons = (label) => view.root.findAllByType('button').filter((node) => node.children.join('') === label)
const button = (label) => buttons(label)[0]
const input = (id) => view.root.findAll((node) => node.type === 'input' && node.props.id === id)[0]
const render = async (element) => { await act(async () => { view = create(element) }) }
const unmount = () => act(() => view.unmount())
const reconnect = async () => { await act(async () => { for (const fn of sidecar) fn({ alive: true, ready: true, profile: 'p' }) }) }

let changed = 0
window.addEventListener('mrcall:mailboxes-changed', () => { changed++ })

// ── Settings: MailboxesCard ───────────────────────────────────────────
const Card = load('views/Settings.tsx', '\nexport { MailboxesCard };').MailboxesCard
await render(React.createElement(Card))
assert.match(text(), /owner@example\.test/)
assert.match(text(), /Primary/)
assert.match(text(), /pec@pec\.net/)
assert.match(text(), /the server refused the login/, 'last_error is shown')
assert.match(text(), /Last sync: ","never/, 'an unsynced row shows no sync time')
assert.equal(buttons('Remove').length, 1, 'only the additional mailbox offers Remove')
const rows = view.root.findAll((node) => node.type === 'li' && node.props['data-mailbox-id'])
assert.equal(rows.length, 2)
const primaryRow = rows.find((li) => li.props['data-mailbox-id'] === 'mb-primary')
assert.equal(primaryRow.findAllByType('button').length, 0, 'the primary row has no Edit/Remove')

await act(async () => button('Add mailbox').props.onClick())
assert.match(text(), /"Password"/, 'custom preset uses the generic label')
await act(async () => view.root.findAll((n) => n.type === 'select' && n.props.id === 'mailbox-add-preset')[0].props.onChange({ target: { value: 'pec.net' } }))
assert.match(text(), /PEC mailbox password/, 'the preset names the credential')
assert.equal(input('mailbox-add-imap-host').props.value, 'imap.pec-email.com')
assert.equal(input('mailbox-add-smtp-port').props.value, '465')
await act(async () => input('mailbox-add-address').props.onChange({ target: { value: 'new@pec.net' } }))
await act(async () => input('mailbox-add-password').props.onChange({ target: { value: 'pec-secret' } }))
assert.equal(input('mailbox-add-password').props.type, 'password', 'the password field is masked')
assert.equal(button('Save').props.disabled, true, 'Save waits for a successful test')
await act(async () => button('Test connection').props.onClick())
assert.equal(calls.test.length, 1)
assert.deepEqual(calls.test[0], { address: 'new@pec.net', password: 'pec-secret', imap_host: 'imap.pec-email.com', imap_port: 993, smtp_host: 'smtp.pec-email.com', smtp_port: 465 })
assert.match(text(), /Login refused: the server rejected the username or password/)
assert.equal(button('Save').props.disabled, true, 'a refused test keeps Save disabled')
// A test answer that arrives after an edit is dropped: Save stays disabled.
let lateResolve
testAnswer = new Promise((resolve) => { lateResolve = resolve })
await act(async () => button('Test connection').props.onClick())
await act(async () => input('mailbox-add-password').props.onChange({ target: { value: 'pec-secret' } }))
await act(async () => lateResolve({ ok: true, status: 'ok', message: 'late' }))
assert.equal(button('Save').props.disabled, true, 'a test answer older than the latest edit is ignored')
assert.doesNotMatch(text(), /Connection OK/)
testAnswer = { ok: true, status: 'ok', message: 'Logged in; INBOX, Sent and archive folders open' }
await act(async () => button('Test connection').props.onClick())
assert.match(text(), /Connection OK/)
assert.equal(button('Save').props.disabled, false)
// Any edit after a successful test disables Save again.
await act(async () => input('mailbox-add-imap-port').props.onChange({ target: { value: '994' } }))
assert.equal(button('Save').props.disabled, true, 'an edit invalidates the test')
await act(async () => input('mailbox-add-imap-port').props.onChange({ target: { value: '993' } }))
await act(async () => button('Test connection').props.onClick())
await act(async () => button('Save').props.onClick())
assert.equal(calls.add.length, 1)
assert.equal(calls.add[0].preset, 'pec.net')
assert.equal(calls.add[0].password, 'pec-secret')
assert.equal(changed, 1, 'Settings announces the change to the Email view')
assert.match(text(), /Added new@pec\.net/)
assert.match(text(), /new@pec\.net/)
assert.equal(buttons('Remove').length, 2)
assert.ok(!input('mailbox-add-password'), 'the form closes after Save')

// Edit: the refusal from update is shown inline.
const pecRow = () => view.root.findAll((node) => node.type === 'li' && node.props['data-mailbox-id'] === 'mb-pec')[0]
await act(async () => pecRow().findAllByType('button').find((b) => b.children.join('') === 'Edit').props.onClick())
await act(async () => input('edit-mb-pec-imap-port').props.onChange({ target: { value: '9993' } }))
await act(async () => button('Save changes').props.onClick())
assert.deepEqual(calls.update, [{ mailbox_id: 'mb-pec', imap_port: 9993 }])
assert.match(text(), /Server unreachable: imap\.pec-email\.com:9993: connection refused/)

// Remove: confirm first, then the row leaves the list.
await act(async () => pecRow().findAllByType('button').find((b) => b.children.join('') === 'Remove').props.onClick())
const dialogs = view.root.findAll((n) => n.type === 'div' && n.props.role === 'dialog')
assert.equal(dialogs.length, 1, 'a confirm dialog opens before removal')
assert.equal(dialogs[0].props['aria-label'], 'Remove pec@pec.net')
assert.equal(calls.remove.length, 0, 'nothing is removed before confirmation')
await act(async () => button('Remove mailbox').props.onClick())
assert.deepEqual(calls.remove, ['mb-pec'])
assert.doesNotMatch(text(), /"pec@pec\.net"/)
assert.equal(changed, 2)
// A sidecar restart reloads the list from the (new) engine.
listed = [primary, pec]
await reconnect()
assert.match(text(), /"pec@pec\.net"/, 'the card reloads after the sidecar comes back')
// Cancelled probes cannot validate a reopened empty form.
await act(async () => button('Add mailbox').props.onClick())
await act(async () => input('mailbox-add-address').props.onChange({ target: { value: 'cancel@pec.net' } }))
await act(async () => input('mailbox-add-password').props.onChange({ target: { value: 'synthetic-password' } }))
let finishCancelled
 testAnswer = new Promise(resolve => { finishCancelled = resolve })
await act(async () => { button('Test connection').props.onClick() })
await act(async () => button('Cancel').props.onClick())
await act(async () => button('Add mailbox').props.onClick())
await act(async () => finishCancelled({ ok: true, status: 'ok' }))
assert.equal(button('Save').props.disabled, true)
await act(async () => button('Cancel').props.onClick())
// A deferred successful probe cannot authorize Save on a new engine/account.
await act(async () => button('Add mailbox').props.onClick())
await act(async () => input('mailbox-add-address').props.onChange({ target: { value: 'other@pec.net' } }))
await act(async () => input('mailbox-add-password').props.onChange({ target: { value: 'synthetic-private-password' } }))
let finishProbe
 testAnswer = new Promise(resolve => { finishProbe = resolve })
await act(async () => { button('Test connection').props.onClick() })
await reconnect()
await act(async () => finishProbe({ ok: true, status: 'ok' }))
await act(async () => button('Add mailbox').props.onClick())
assert.equal(input('mailbox-add-password').props.value, '')
assert.equal(button('Save').props.disabled, true)
await act(async () => input('mailbox-add-password').props.onChange({ target: { value: 'logout-private-password' } }))
await act(async () => { for (const fn of invalidators) fn() })
assert.doesNotMatch(text(), /logout-private-password|other@pec.net/)
assert.equal(buttons('Save').length, 0)
unmount()
assert.equal(sidecar.size, 0)
const listMailboxes = window.zylch.mailboxes.list
window.zylch.mailboxes.list = async () => { throw new Error('Method not found: mailboxes.list') }
await render(React.createElement(Card))
assert.match(text(), /Update the connected engine/)
assert.equal(button('Add mailbox').props.disabled, true)
unmount()
window.zylch.mailboxes.list = listMailboxes
console.log('MailboxesCard: list, primary badge, preset label, Test before Save, add, update refusal and confirmed remove passed.')

// ── Email view: chip, filter, archive rollback ────────────────────────
const Email = load('views/Email.tsx').default
const thread = {
  thread_id: 't1', subject: 'PEC notice', from_email: 'sender@example.test', from_name: 'Sender', to_email: 'pec@pec.net',
  date: '2026-09-30T09:00:00', snippet: 'hello', unread: false, has_attachments: false, pinned: false, message_count: 1,
  last_email_id: 'e1', mailbox_ids: ['mb-pec']
}
const message = {
  id: 'e1', from_email: 'sender@example.test', from_name: 'Sender', to_email: 'pec@pec.net', cc_email: '', date: '2026-09-30T09:00:00',
  subject: 'PEC notice', body_plain: 'hello', body_html: '', is_auto_reply: false, is_user_sent: false, has_attachments: false,
  attachment_filenames: [], mailbox_id: 'mb-pec', mailbox_address: 'pec@pec.net', original_message_id: null, pec_markers: null
}
let archiveAnswer = { ok: false, archived: 0, mailboxes: [{ mailbox_id: 'mb-pec', attempted: 1, moved: 0, error: 'pec@pec.net: the server refused the login' }] }
window.zylch.emails = {
  listInbox: async (p) => { calls.listInbox.push(p); return { threads: [thread] } },
  listSent: async (p) => { calls.listSent.push(p); return { threads: [] } },
  search: async (p) => { calls.search.push(p); return { threads: [thread] } },
  listByThread: async () => ({ emails: [message] }),
  markRead: async () => ({ ok: true, affected: 1 }),
  pin: async () => ({ ok: true, affected: 1 }),
  archive: async (id) => { calls.archive.push(id); return archiveAnswer },
  deleteLocal: async () => ({ ok: true, deleted: 1 })
}
const chips = () => view.root.findAll((n) => n.type === 'span' && n.props.title === 'Mailbox this message arrived in')
const threadRows = () => view.root.findAll((n) => n.type === 'li' && n.props['data-thread-id'])
const mailboxSelect = () => view.root.findAll((n) => n.type === 'select' && n.props['aria-label'] === 'Mailbox')

listed = [primary, pec]
await render(React.createElement(Email))
assert.equal(threadRows().length, 1)
assert.equal(mailboxSelect().length, 1, 'two mailboxes show the filter')
assert.equal(calls.listInbox.at(-1).mailbox_id, undefined, 'no filter by default')
await act(async () => mailboxSelect()[0].props.onChange({ target: { value: 'mb-pec' } }))
assert.equal(calls.listInbox.at(-1).mailbox_id, 'mb-pec', 'the filter reaches list_inbox')
await act(async () => threadRows()[0].props.onClick())
assert.equal(chips().length, 1, 'the reading pane tags the message with its mailbox')
assert.equal(chips()[0].children.join(''), 'pec@pec.net')
// Archive refused: the thread comes back and the mailbox's error is shown.
await act(async () => button('Archive').props.onClick())
assert.deepEqual(calls.archive, ['t1'])
assert.equal(threadRows().length, 1, 'the optimistic removal is rolled back on ok:false')
assert.match(text(), /Archive failed: pec@pec\.net: the server refused the login/)
// Archive accepted: the thread leaves the list.
archiveAnswer = { ok: true, archived: 1, mailboxes: [{ mailbox_id: 'mb-pec', attempted: 1, moved: 1, error: null }] }
await act(async () => threadRows()[0].props.onClick())
await act(async () => button('Archive').props.onClick())
assert.equal(threadRows().length, 0)
unmount()

listed = [primary]
await render(React.createElement(Email, { active: true }))
assert.equal(mailboxSelect().length, 0, 'one mailbox shows no filter')
await act(async () => threadRows()[0].props.onClick())
assert.equal(chips().length, 0, 'one mailbox shows no chip')
// A mailbox added in Settings after mount: the change event makes the filter appear.
listed = [primary, pec]
await act(async () => { window.dispatchEvent(new Event('mrcall:mailboxes-changed')) })
assert.equal(chips().length, 1, 'a mailbox added after mount tags the open thread')
await act(async () => view.root.findAll((n) => n.type === 'button' && n.props['aria-label'] === 'Back to list')[0].props.onClick())
assert.equal(mailboxSelect().length, 1, 'a mailbox added after mount shows the filter')
await act(async () => mailboxSelect()[0].props.onChange({ target: { value: 'mb-pec' } }))
assert.equal(mailboxSelect()[0].props.value, 'mb-pec')
// The filtered mailbox is removed: the filter falls back to all mailboxes.
listed = [primary]
await act(async () => { window.dispatchEvent(new Event('mrcall:mailboxes-changed')) })
assert.equal(mailboxSelect().length, 0, 'a removed mailbox leaves no filter behind')
assert.equal(calls.listInbox.at(-1).mailbox_id, undefined, 'the cleared filter reloads every mailbox')
unmount()

// The view re-reads the list when it becomes active (App keeps it mounted).
listed = [primary]
await render(React.createElement(Email, { active: false }))
await act(async () => view.update(React.createElement(Email, { active: true })))
listed = [primary, pec]
await act(async () => view.update(React.createElement(Email, { active: false })))
await act(async () => view.update(React.createElement(Email, { active: true })))
assert.equal(mailboxSelect().length, 1, 'becoming active refreshes the mailbox list')
unmount()
assert.equal(sidecar.size, 0)
assert.equal(listeners.get('mrcall:mailboxes-changed').size, 1, 'the view unsubscribes on unmount')
console.log('Email view: mailbox filter, per-message chip only with more than one mailbox, archive rollback on ok:false passed.')
