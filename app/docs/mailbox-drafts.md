# Mailbox drafts in Desktop

Email → Drafts lists the mailbox drafts returned by the engine. The folder
badge refreshes while Email is active. The list reloads every 30 seconds, on
window focus and after the engine reconnects. Its mailbox filter uses the
same mailbox identifiers as Inbox and Sent.

Opening a draft reads its current mailbox content through `drafts.get`. Refresh
in the detail view reopens the exact selected handle. If an edit saved in Gmail
replaces that handle, return to the list and select the refreshed entry. Editing
plain text, recipients or subject sends only changed fields through
`drafts.update`. A successful Save selects the replacement handle in
`result.draft.id`. The editor keeps no persisted body or second draft.
Rich-text body editing stays in Gmail. Drafts with attachments can be viewed
or moved to Trash; their edit and send buttons are disabled to preserve the
complete message.

Send and Move to Trash call the engine with the opaque mailbox draft ID and
a random request key. The window's profile-scoped local storage retains the
opaque draft ID, mailbox ID when available, action, key and optional
`sentConfirmed` flag. It contains no editable body. Reopening or reloading
the view lists pending operations even when a consumed draft is absent
from Drafts. That entry offers Check send or
Check Trash for the same operation. Check send is read-only. Once Sent is
verified, a pending retirement offers Remove sent draft, which repeats the
original key without transmitting again. The editor stays disabled until it settles. A confirmed result
removes the row after a fresh mailbox read. A definite refusal before dispatch
allows correction. A draft sent or deleted in Gmail is never recreated by the UI.

Mailbox authentication and provider failures appear in the Drafts view with
a Refresh action. An unavailable count is omitted from the badge rather than
reported as zero.

`npm run typecheck` and `npm run build` validate the app. `npm run test:drafts`
runs the actual Email view and preload bridge in headless Chromium against
synthetic RPC responses. Set `MRCALL_PLAYWRIGHT_MODULE` to an installed Playwright
module and `MRCALL_BROWSER_BINARY` to Chromium when they are not discoverable
by their defaults. The browser check covers current Gmail edits, sparse save,
uncertain-send replay across remount, external removal, attachment preservation,
Trash and authorization recovery. It establishes UI behavior, not a live Gmail
or installed-engine acceptance result.
