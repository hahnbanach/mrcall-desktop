/**
 * Compact vendor-engine status row for the sidebar's identity block
 * (rendered in `App.tsx`'s `Sidebar`, between the profile-email chip and
 * `ProfilesDropdown`). Backed by `provision:start` / `provision:status`
 * (`app/src/main/provisionClient.ts` + the IPC handlers in
 * `app/src/main/index.ts`) — this component owns only the render + poll
 * loop, never the HTTP call.
 *
 * `preparing` is the only state that keeps polling: the vendor
 * `provisiond` reconcile loop can take tens of seconds to bring the
 * per-uid daemon up. `active`, `problem` and `not_provisioned` are
 * terminal until the user acts (the "Activate" button) or the window
 * remounts.
 *
 * `not_signed_in` / `no_profile` / `no_window` mean the question is
 * meaningless in the window's current state (no bound profile yet), so
 * the row renders nothing rather than an error chip. Any other
 * `ok:false` from the status poll (session_expired, network_error,
 * server_error, bad_request) is also swallowed silently here rather than
 * shown as a fifth ad-hoc visual state — the brief only specifies
 * renders for the four `ProvisionState` values plus the three "hidden"
 * codes, and a transient network hiccup will self-correct on the next
 * poll tick without a UI invented to explain it.
 *
 * Every visible variant of the row also carries a `ProvisionInfoButton`
 * — the small circled-"i" that opens a plain-language explainer of what
 * the vendor engine is and what "Activate" does. Its own open/close
 * state is a separate concern from the poll-driven `ViewState` above;
 * see `nextInfoOpen`.
 */
import { useEffect, useId, useRef, useState } from 'react'

type ProvisionState = 'active' | 'preparing' | 'problem' | 'not_provisioned'

type StatusResult =
  | { ok: true; state: ProvisionState }
  | { ok: false; code: string; message: string }

type StartResult =
  | { ok: true; uid: string; state: 'preparing' }
  | { ok: false; code: string; message: string }

// Codes that mean "there's no bound profile / signed-in user to ask
// about" — the row disappears entirely rather than showing a chip.
const SILENT_CODES = new Set(['not_signed_in', 'no_profile', 'no_window'])

// One render-ready description of the row, derived purely from the raw
// IPC results below. Kept separate from the component so the state
// machine can be exercised without mounting React.
export type ViewState =
  | { kind: 'loading' }
  | { kind: 'hidden' }
  | { kind: 'active' }
  | { kind: 'preparing' }
  | { kind: 'problem' }
  | { kind: 'not_provisioned'; starting: boolean; startMessage: string | null }

/** Turn a `provision:status` result into what the row should show. */
export function deriveView(result: StatusResult | null): ViewState {
  if (result === null) return { kind: 'loading' }
  if (!result.ok) {
    // Every ok:false code collapses to hidden here — see the module
    // docstring for why the non-SILENT_CODES ones aren't given their own
    // visual state.
    return { kind: 'hidden' }
  }
  if (result.state === 'not_provisioned') {
    return { kind: 'not_provisioned', starting: false, startMessage: null }
  }
  return { kind: result.state }
}

/** Apply a `provision:start` result on top of the "Activate" click. */
export function applyStartResult(result: StartResult): ViewState {
  if (result.ok) return { kind: 'preparing' }
  return { kind: 'not_provisioned', starting: false, startMessage: result.message }
}

const POLL_MS = 5000

// How long to wait before quietly retrying after a NON-silent failure
// (unreachable host, 5xx). Deliberately much slower than POLL_MS: this is
// self-healing, not something a user is waiting on.
const RETRY_MS = 30_000

/** True for the codes that mean "the question does not apply here" —
 * no profile, not signed in, no window. Those hide the row permanently
 * and correctly; every other failure is transient and gets retried. */
export function isSilent(code: string): boolean {
  return SILENT_CODES.has(code)
}

// Open/close state for the "What is this?" explanatory popover attached
// to the status row. Kept as a pure reducer — same reasoning as
// `deriveView`/`applyStartResult` above — so the toggle/dismiss logic can
// be exercised without mounting React or a DOM. `toggle` is the (i)
// button's own click; `dismiss` is every other way the popover closes
// (outside click, Escape, focus leaving) and always yields closed
// regardless of the current state.
export type InfoPopoverAction = 'toggle' | 'dismiss'
export function nextInfoOpen(open: boolean, action: InfoPopoverAction): boolean {
  if (action === 'toggle') return !open
  return false
}

// Dot colours drawn from the existing brand palette (tailwind.config.js)
// — no new hex values.
const DOT_CLASS: Record<'active' | 'preparing' | 'problem' | 'not_provisioned', string> = {
  active: 'bg-brand-blue',
  preparing: 'bg-brand-orange',
  problem: 'bg-brand-danger',
  not_provisioned: 'bg-brand-mid-grey'
}

// Small "(i)" affordance next to the status label, explaining what the
// vendor engine is and why "Activate" exists. Follows the same
// outside-click / Escape dismissal pattern as `ProfilesDropdown` in
// `App.tsx` (document-level `mousedown` + `keydown` listeners scoped to
// `open`, `containerRef.contains` to detect outside clicks) rather than
// inventing a second convention. The sidebar is only 220px wide, so the
// panel is an absolutely-positioned popover that is allowed to overflow
// it — same `absolute` + `z-40` idiom `ProfilesDropdown` already uses for
// its own menu, opening downward (`top-full`) like that menu does in
// this same header (`direction="down"`), since there's more room below
// the row than above it.
function ProvisionInfoButton(): JSX.Element {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const panelId = useId()

  const close = (returnFocus: boolean): void => {
    setOpen((prev) => nextInfoOpen(prev, 'dismiss'))
    if (returnFocus) buttonRef.current?.focus()
  }

  useEffect(() => {
    if (!open) return
    // Move keyboard focus into the panel so Escape/Tab work from it
    // immediately, without requiring a prior click inside it.
    panelRef.current?.focus()
    const onDown = (e: MouseEvent): void => {
      const node = containerRef.current
      if (node && !node.contains(e.target as Node)) close(false)
    }
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') close(true)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  return (
    <div ref={containerRef} className="relative shrink-0 leading-none">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((prev) => nextInfoOpen(prev, 'toggle'))}
        aria-label="What is this?"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-brand-mid-grey text-brand-grey-80 text-[9px] leading-none hover:bg-brand-light-grey hover:text-brand-black"
      >
        i
      </button>
      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="dialog"
          aria-label="Running on the MrCall server"
          tabIndex={-1}
          className="absolute z-40 left-0 top-full mt-1 w-[280px] max-w-[calc(100vw-2rem)] bg-white border border-brand-mid-grey rounded shadow-lg p-3 text-[11px] leading-snug text-brand-grey-80"
        >
          <h3 className="text-xs font-semibold text-brand-black mb-1.5">
            Running on the MrCall server
          </h3>
          <p className="mb-2">
            Your assistant normally runs on this computer. It syncs your mailbox, keeps its
            memory of your customers, and prepares replies — but only while the app is open.
            Close it, or shut the Mac, and it stops.
          </p>
          <p className="mb-2">
            Activating puts a copy of your profile on the MrCall server, so the same assistant
            keeps working when your computer is off: overnight, at weekends, while you travel.
          </p>
          <p className="mb-2">
            When you click Activate, the app sends this profile&rsquo;s mailbox settings to the
            server over an encrypted connection, signed in as you. Preparing usually takes under
            a minute.
          </p>
          <ul className="mb-2 pl-4 list-disc space-y-0.5">
            <li>
              <strong className="text-brand-black">Preparing</strong> — the server is setting
              your assistant up.
            </li>
            <li>
              <strong className="text-brand-black">Active</strong> — it is running on the
              server.
            </li>
            <li>
              <strong className="text-brand-black">Problem</strong> — something went wrong. We
              have been notified.
            </li>
          </ul>
          <p>Either way, the app works exactly as before.</p>
        </div>
      )}
    </div>
  )
}

export default function ProvisionStatus(): JSX.Element | null {
  const [view, setView] = useState<ViewState>({ kind: 'loading' })
  const mountedRef = useRef(true)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Shared by the mount-time poll and by `onActivate` after a successful
  // start: fetch status once, render it, and — only while still
  // `preparing` — schedule the next tick. Stops itself the moment the
  // state leaves `preparing`.
  const poll = (): void => {
    void (async () => {
      const result = await window.zylch.provision.status()
      if (!mountedRef.current) return
      const next = deriveView(result)
      setView(next)
      if (next.kind === 'preparing') {
        timerRef.current = setTimeout(poll, POLL_MS)
      } else if (next.kind === 'hidden' && result !== null && !result.ok && !isSilent(result.code)) {
        // A transient failure (the vendor host unreachable, a 5xx) hides
        // the row — but it must not hide it FOREVER. Without this branch
        // a network blip on the very first poll is terminal for the whole
        // feature until the app restarts: the row never renders, so a
        // customer who is not provisioned can never reach the Activate
        // button, and one who IS provisioned is told nothing. Retry
        // quietly, slower than the `preparing` cadence — nobody is
        // watching this row, it just has to heal on its own.
        timerRef.current = setTimeout(poll, RETRY_MS)
      }
    })()
  }

  useEffect(() => {
    mountedRef.current = true
    poll()
    return () => {
      mountedRef.current = false
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onActivate = (): void => {
    setView((prev) =>
      prev.kind === 'not_provisioned'
        ? { ...prev, starting: true, startMessage: null }
        : prev
    )
    void (async () => {
      const result = await window.zylch.provision.start()
      if (!mountedRef.current) return
      const next = applyStartResult(result)
      setView(next)
      if (next.kind === 'preparing') {
        timerRef.current = setTimeout(poll, POLL_MS)
      }
    })()
  }

  if (view.kind === 'loading' || view.kind === 'hidden') return null

  if (view.kind === 'not_provisioned') {
    return (
      <div className="text-[11px] px-2 py-1 rounded border border-brand-mid-grey bg-white text-brand-grey-80 flex flex-col gap-1">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`inline-block w-2 h-2 rounded-full shrink-0 ${DOT_CLASS.not_provisioned}`}
            aria-hidden="true"
          />
          <span className="truncate flex-1" title="Not on the vendor engine">
            Not on the vendor engine
          </span>
          <ProvisionInfoButton />
          <button
            type="button"
            onClick={onActivate}
            disabled={view.starting}
            className="shrink-0 px-1.5 py-0.5 text-[11px] border border-brand-mid-grey rounded text-brand-grey-80 bg-white hover:bg-brand-light-grey disabled:opacity-50"
          >
            {view.starting ? 'Activating…' : 'Activate'}
          </button>
        </div>
        {view.startMessage && (
          <div className="truncate text-brand-danger" title={view.startMessage}>
            {view.startMessage}
          </div>
        )}
      </div>
    )
  }

  const label =
    view.kind === 'active'
      ? 'Vendor engine: active'
      : view.kind === 'preparing'
        ? 'Vendor engine: preparing…'
        : 'Vendor engine: problem'
  const hint =
    view.kind === 'preparing'
      ? 'This can take up to a minute.'
      : view.kind === 'problem'
        ? 'Support has been notified.'
        : null

  return (
    <div className="text-[11px] px-2 py-1 rounded border border-brand-mid-grey bg-white text-brand-grey-80 flex flex-col gap-1">
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`inline-block w-2 h-2 rounded-full shrink-0 ${DOT_CLASS[view.kind]}`}
          aria-hidden="true"
        />
        <span className="truncate flex-1" title={label}>
          {label}
        </span>
        <ProvisionInfoButton />
      </div>
      {hint && (
        <div className="truncate text-brand-grey-80/70" title={hint}>
          {hint}
        </div>
      )}
    </div>
  )
}
