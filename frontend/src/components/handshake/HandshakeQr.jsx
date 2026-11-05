import { Copy, RefreshCw } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { useEffect, useState } from 'react'
import { formatTaka } from '../../constants/rentals.js'

function useCountdown(expiresAt) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(timer)
  }, [])
  const minutes = Math.max(0, Math.round((new Date(expiresAt).getTime() - now) / 60_000))
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`
}

// The owner hands over the key: the handshake QR is drawn inside a large key tag with a green eyelet.
export default function HandshakeQr({ issued, onRegenerate, regenerating }) {
  const remaining = useCountdown(issued.expires_at)
  const [copied, setCopied] = useState(false)
  const { booking } = issued

  async function copyToken() {
    try {
      await navigator.clipboard.writeText(issued.token)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
      <div className="flex shrink-0 flex-col items-center" aria-label="Handshake QR code">
        <span aria-hidden="true" className="h-5 w-px bg-leaf" />
        <div className="relative rotate-1 rounded-2xl border-2 border-ink bg-white px-4 pb-4 pt-9 shadow-lg">
          <span aria-hidden="true" className="absolute left-1/2 top-2.5 size-4 -translate-x-1/2 rounded-full border-[3px] border-leaf bg-plaster" />
          <QRCodeSVG value={issued.token} size={208} level="M" marginSize={0} fgColor="#264076" title="Handshake code" />
          <p className="mt-3 text-center font-display text-lg font-extrabold uppercase tracking-widest">Handshake</p>
        </div>
      </div>
      <div className="min-w-0 space-y-2 text-sm">
        <p className="font-semibold">Show this to {booking.tenant.full_name} at the property.</p>
        <p className="text-ink-soft">
          They scan it from their dashboard. That confirms the tenancy at {formatTaka(booking.agreed_rent)} a month, releases
          the deposit to you, and creates the lease PDF.
        </p>
        <p className="text-ink-soft">
          Works once. Expires in <span className="font-medium text-ink">{remaining}</span>.
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          <button
            type="button"
            onClick={copyToken}
            className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-2.5 py-1.5 text-xs font-semibold hover:border-ink"
          >
            <Copy className="size-3.5" aria-hidden="true" /> {copied ? 'Copied' : 'Copy code'}
          </button>
          <button
            type="button"
            onClick={onRegenerate}
            disabled={regenerating}
            className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-2.5 py-1.5 text-xs font-semibold hover:border-ink disabled:opacity-60"
          >
            <RefreshCw className={`size-3.5 ${regenerating ? 'animate-spin' : ''}`} aria-hidden="true" /> New code
          </button>
        </div>
        <p className="text-xs text-ink-soft">A new code replaces this one immediately.</p>
      </div>
    </div>
  )
}
