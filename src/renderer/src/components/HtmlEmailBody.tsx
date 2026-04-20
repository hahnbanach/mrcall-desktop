import { useState } from 'react'

// Minimal styling baked into the iframe srcDoc so email HTML renders
// with a sane default and images never blow the reading pane wider
// than its container. `base target="_blank"` makes any <a> open via
// the Electron window-open handler, which routes to shell.openExternal.
const IFRAME_CSS = [
  'body{font-family:system-ui,-apple-system,sans-serif;font-size:14px;',
  'color:#1e293b;padding:0;margin:0;line-height:1.5;}',
  'img{max-width:100%!important;height:auto!important;}',
  'pre,code{white-space:pre-wrap;word-break:break-word;}',
  'blockquote{border-left:3px solid #cbd5e1;margin:0.5em 0;',
  'padding:0.25em 0.75em;color:#475569;}',
  'table{max-width:100%;}'
].join('')

function buildSrcDoc(html: string): string {
  // Many email clients send a full document (DOCTYPE + <html> + <body>).
  // Wrapping that inside our own <html><body> produces nested body/html,
  // and browsers stop computing scrollHeight correctly — the content
  // appears cropped to ~1/3 of the pane. If the payload already looks
  // like a full document, inject our <base> and <style> into its <head>
  // instead of wrapping.
  const looksFull = /<(?:!doctype|html|head|body)\b/i.test(html.slice(0, 400))
  const headInject =
    '<meta charset="utf-8"/>' +
    '<base target="_blank"/>' +
    '<style>' +
    IFRAME_CSS +
    '</style>'
  if (looksFull) {
    if (/<head[^>]*>/i.test(html)) {
      return html.replace(/<head([^>]*)>/i, (m) => m + headInject)
    }
    if (/<html[^>]*>/i.test(html)) {
      return html.replace(/<html([^>]*)>/i, (m) => m + '<head>' + headInject + '</head>')
    }
    return '<head>' + headInject + '</head>' + html
  }
  return (
    '<!DOCTYPE html><html><head>' +
    headInject +
    '</head><body>' +
    html +
    '</body></html>'
  )
}

const IFRAME_MIN_HEIGHT = 80
// Safety valve: 10× viewport height. Only exists so a runaway email
// (e.g. an infinite-height CSS bug) can't grow the DOM unboundedly. In
// practice real emails are well under this cap — the reading pane is
// scrollable, so letting the iframe grow to its natural height means
// the user scrolls the pane, not the iframe's inner scrollbar.
function safetyCap(): number {
  if (typeof window === 'undefined') return 10000
  return Math.max(10000, window.innerHeight * 10)
}

/**
 * Isolates HTML email markup inside a fully-sandboxed iframe.
 *
 * sandbox="" disables scripts, forms, same-origin access, top-level
 * navigation, plugins and popups — so even obviously hostile email HTML
 * can't reach the renderer. referrerPolicy="no-referrer" prevents the
 * parent URL leaking to tracking pixels. Height is measured on load to
 * match the content; the outer reading pane handles scroll.
 */
export default function HtmlEmailBody({ html }: { html: string }): JSX.Element {
  const [height, setHeight] = useState<number>(IFRAME_MIN_HEIGHT)
  const handleLoad = (e: React.SyntheticEvent<HTMLIFrameElement>): void => {
    try {
      const doc = e.currentTarget.contentDocument
      if (!doc) return
      // documentElement.scrollHeight is more reliable than body.scrollHeight
      // when emails use table-based layouts or set explicit heights on the
      // body — body can report a stale / collapsed height while <html> sees
      // the full rendered tree.
      const bodyH = doc.body?.scrollHeight ?? 0
      const htmlH = doc.documentElement?.scrollHeight ?? 0
      const measured = Math.max(bodyH, htmlH) + 16
      const capped = Math.min(safetyCap(), Math.max(IFRAME_MIN_HEIGHT, measured))
      setHeight(capped)
    } catch {
      /* cross-origin reads shouldn't happen with srcDoc + sandbox="" */
    }
  }
  return (
    <iframe
      title="email-body"
      sandbox=""
      referrerPolicy="no-referrer"
      loading="lazy"
      srcDoc={buildSrcDoc(html)}
      onLoad={handleLoad}
      style={{ width: '100%', height, border: 0, display: 'block' }}
    />
  )
}
