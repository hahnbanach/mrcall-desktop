/** Window event Settings fires after a mailbox is added, changed or
 *  removed; the Email view (always mounted) re-reads `mailboxes.list`
 *  on it. Dispatched with `new Event(MAILBOXES_CHANGED_EVENT)`. */
export const MAILBOXES_CHANGED_EVENT = 'mrcall:mailboxes-changed'
