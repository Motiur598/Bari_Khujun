import { Html5Qrcode } from 'html5-qrcode'
import { Camera, CameraOff, LockKeyhole, X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { DEPOSIT_METHODS, formatDateTime } from '../../constants/marketplace.js'
import { CATEGORIES, formatDay, formatTaka } from '../../constants/rentals.js'
import { Alert, Button } from '../ui.jsx'

// Handshake codes are JWTs: three base64url parts. Anything else is turned away before it reaches the server.
const JWT_FORMAT = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/
const HANDSHAKE_AUDIENCE = 'barikhujun:qr-handshake'
const MAX_CODE_LENGTH = 4000
const NOT_A_CODE = "That isn't a Bari Khujun handshake code. Scan the QR code the owner shows you."

function decodeClaims(token) {
  const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(part.padEnd(Math.ceil(part.length / 4) * 4, '='))
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0))))
}

// Reads a scanned or pasted code against the tenant's own `bookings`. Only the server can check the signature; this
// catches codes that are malformed, expired or not for one of the tenant's open requests, and finds the booking the
// code is for, so the confirmation shows exactly which place gets locked.
export function readHandshakeCode(raw, bookings) {
  const token = raw.trim()
  if (token.length > MAX_CODE_LENGTH || !JWT_FORMAT.test(token)) return { error: NOT_A_CODE }
  let claims
  try {
    claims = decodeClaims(token)
  } catch {
    return { error: NOT_A_CODE }
  }
  if (claims?.aud !== HANDSHAKE_AUDIENCE || typeof claims.exp !== 'number' || typeof claims.agreed_rent !== 'number') {
    return { error: NOT_A_CODE }
  }
  const booking = bookings.find((candidate) => candidate.id === claims.booking_id)
  if (!booking) {
    return { error: "This code wasn't issued for any of your requests. Ask the owner to show the code for your booking." }
  }
  if (booking.status === 'CONFIRMED') return { error: "You've already confirmed this booking. Its lease is on your dashboard." }
  if (booking.status !== 'APPROVED') return { error: "This request is no longer open, so its code can't be used." }
  if (claims.exp * 1000 <= Date.now()) return { error: 'This code has expired. Ask the owner to generate a new one.' }
  return { token, claims, booking }
}

function SummaryRow({ label, children }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3 py-2.5 sm:grid-cols-[9rem_1fr]">
      <dt className="text-sm text-ink-soft">{label}</dt>
      <dd className="min-w-0 break-words text-sm font-medium">{children}</dd>
    </div>
  )
}

// The last look before the lock: what the code says, next to what the tenant asked for.
function ConfirmHandshakeDialog({ code, onCancel, onConfirm }) {
  const dialogRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const dialog = dialogRef.current
    if (code && !dialog.open) {
      setError('')
      dialog.showModal()
    }
    if (!code && dialog.open) dialog.close()
  }, [code])

  const { claims, booking } = code ?? {}
  const rentMatches = claims?.agreed_rent === booking?.agreed_rent
  const unit = booking?.listing.category === 'BACHELOR_SEAT' ? 'seat' : 'flat'

  async function handleConfirm() {
    setBusy(true)
    setError('')
    try {
      await onConfirm(code.token)
    } catch (err) {
      setError(getErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <dialog
      ref={dialogRef}
      onClose={onCancel}
      aria-labelledby="handshake-confirm-heading"
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-xl bg-sheet p-0 text-ink shadow-2xl"
    >
      {claims && (
        <>
          <div className="flex items-center justify-between border-b border-rule px-5 py-4">
            <h2 id="handshake-confirm-heading" className="font-display text-2xl font-extrabold uppercase tracking-wide">
              Confirm the handshake
            </h2>
            <button type="button" onClick={onCancel} aria-label="Close" className="rounded p-1 text-ink-soft hover:bg-plaster hover:text-ink">
              <X className="size-5" aria-hidden="true" />
            </button>
          </div>
          <div className="space-y-4 p-5">
            <p className="text-sm text-ink-soft">Check these details with the owner before you lock the {unit}.</p>
            <dl className="divide-y divide-rule border-y border-rule">
              <SummaryRow label="Place">
                {booking.listing.title}
                <span className="block font-normal text-ink-soft">
                  {CATEGORIES[booking.listing.category].label} · {booking.listing.area}
                </span>
              </SummaryRow>
              <SummaryRow label="Owner">
                {booking.owner.full_name} · <span className="whitespace-nowrap">{booking.owner.phone}</span>
              </SummaryRow>
              <SummaryRow label="Rent">{formatTaka(claims.agreed_rent)} a month</SummaryRow>
              <SummaryRow label="Moving in">{formatDay(booking.move_in_date)}</SummaryRow>
              <SummaryRow label="Deposit">
                {formatTaka(booking.deposit.amount)} via {DEPOSIT_METHODS[booking.deposit.method]}
              </SummaryRow>
              <SummaryRow label="Code valid until">{formatDateTime(claims.exp * 1000)}</SummaryRow>
            </dl>
            {rentMatches ? (
              <p className="text-sm">
                Confirming releases your {formatTaka(booking.deposit.amount)} deposit to the owner, takes the {unit} off the
                market and creates your lease. You can't undo it.
              </p>
            ) : (
              <Alert>
                This code says {formatTaka(claims.agreed_rent)} a month, but you requested {formatTaka(booking.agreed_rent)}. Don't
                confirm until the owner issues a code for the agreed rent.
              </Alert>
            )}
            <Alert>{error}</Alert>
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={onCancel}
                className="rounded-md border border-rule bg-white px-4 py-2.5 text-sm font-semibold hover:border-ink"
              >
                Back
              </button>
              <Button type="button" onClick={handleConfirm} busy={busy} disabled={!rentMatches}>
                <LockKeyhole className="size-4" aria-hidden="true" /> Confirm and lock
              </Button>
            </div>
          </div>
        </>
      )}
    </dialog>
  )
}

// Tenant side of the handshake: scan (or paste) the owner's code, check it against the tenant's `bookings`, then
// confirm. `onConfirm(token)` performs the lock and should throw on failure, so the error shows in the dialog.
export default function TenantQRScanner({ bookings, onConfirm }) {
  const regionId = `qr-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const scannerRef = useRef(null)
  const [scanning, setScanning] = useState(false)
  const [cameraError, setCameraError] = useState('')
  const [codeError, setCodeError] = useState('')
  const [pasted, setPasted] = useState('')
  const [code, setCode] = useState(null)

  async function stop() {
    const scanner = scannerRef.current
    scannerRef.current = null
    setScanning(false)
    if (scanner?.isScanning) await scanner.stop().catch(() => {})
    scanner?.clear()
  }

  function review(raw) {
    const result = readHandshakeCode(raw, bookings)
    setCodeError(result.error ?? '')
    if (!result.error) setCode(result)
  }

  async function start() {
    setCameraError('')
    setCodeError('')
    const scanner = new Html5Qrcode(regionId, { verbose: false })
    scannerRef.current = scanner
    setScanning(true)
    try {
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 240, height: 240 } },
        (text) => {
          if (scannerRef.current !== scanner) return // the camera can report the same code more than once
          stop()
          review(text)
        },
        () => {}, // frames without a QR code are normal
      )
    } catch {
      setCameraError("Couldn't open a camera. Allow camera access, or paste the code below.")
      await stop()
    }
  }

  useEffect(() => () => {
    const scanner = scannerRef.current
    if (scanner?.isScanning) scanner.stop().catch(() => {})
  }, [])

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-lg border border-rule bg-ink">
        <div id={regionId} className={scanning ? 'min-h-64' : 'hidden'} />
        {!scanning && (
          <div className="grid h-40 place-items-center px-4 text-center text-sm text-white/70">
            Point your camera at the owner's handshake code.
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {scanning ? (
          <button
            type="button"
            onClick={stop}
            className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-3 py-2 text-sm font-semibold hover:border-ink"
          >
            <CameraOff className="size-4" aria-hidden="true" /> Stop camera
          </button>
        ) : (
          <Button type="button" onClick={start}>
            <Camera className="size-4" aria-hidden="true" /> Scan with camera
          </Button>
        )}
      </div>
      {cameraError && <p className="text-sm text-tag-owner">{cameraError}</p>}
      <Alert>{codeError}</Alert>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (pasted.trim()) review(pasted)
        }}
        className="space-y-2 border-t border-rule pt-4"
      >
        <label htmlFor={`${regionId}-paste`} className="block text-sm font-medium">
          No camera? Paste the code
        </label>
        <textarea
          id={`${regionId}-paste`}
          rows={3}
          value={pasted}
          onChange={(event) => setPasted(event.target.value)}
          placeholder="eyJhbGciOi…"
          className="w-full rounded-md border border-rule bg-white px-3 py-2 font-mono text-xs"
        />
        <Button type="submit" disabled={!pasted.trim()}>
          Check pasted code
        </Button>
      </form>

      <ConfirmHandshakeDialog code={code} onCancel={() => setCode(null)} onConfirm={onConfirm} />
    </div>
  )
}
