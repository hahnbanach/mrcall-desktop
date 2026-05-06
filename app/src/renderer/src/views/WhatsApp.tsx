/**
 * WhatsApp tab — main-content view triggered from the sidebar.
 *
 * Today this is purely a connection surface: we reuse ConnectWhatsApp
 * (the same card that lives in Settings → Integrations and step 2 of
 * Onboarding) so the user can scan the QR / disconnect / forget device
 * without leaving the WhatsApp tab. Once a real WhatsApp inbox UI is
 * built, it slots in below or replaces the connect card on the
 * connected branch.
 */
import ConnectWhatsApp from './ConnectWhatsApp'

export default function WhatsAppView(): JSX.Element {
  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold mb-2">WhatsApp</h1>
      <p className="text-sm text-brand-grey-80 mb-6">
        Local WhatsApp connection via the Linked Devices flow. Messages and contacts stay on
        this machine — nothing routes through a third-party server.
      </p>
      <ConnectWhatsApp />
    </div>
  )
}
