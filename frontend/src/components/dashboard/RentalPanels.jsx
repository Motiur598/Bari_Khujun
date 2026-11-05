import { CheckCircle2, Download, LoaderCircle, ScanLine } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { downloadFile, getErrorMessage } from '../../api/client.js'
import { cancelBooking, generateHandshakeQr, getMyBookings, leasePath, rejectBooking, scanAndConfirm } from '../../api/handshake.js'
import { BOOKING_STATUS, DEPOSIT_METHODS, ESCROW_STATUS, formatDateTime } from '../../constants/marketplace.js'
import { CATEGORIES, formatDay, formatTaka, unitLabel } from '../../constants/rentals.js'
import HandshakeQr from '../handshake/HandshakeQr.jsx'
import TenantQRScanner from '../handshake/TenantQRScanner.jsx'
import { Alert, Button, EmptyState, Stamp } from '../ui.jsx'

function useBookings(side) {
  const [bookings, setBookings] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => {
    getMyBookings(side).then(setBookings, (err) => setError(getErrorMessage(err)))
  }, [side])
  useEffect(load, [load])
  const replace = (next) => setBookings((list) => list.map((b) => (b.id === next.id ? next : b)))
  return { bookings, error, setError, replace, reload: load }
}

function EscrowLedger({ entries }) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer font-medium text-ink-soft hover:text-ink">Escrow record ({entries.length})</summary>
      <ol className="mt-2 space-y-1.5 border-l-2 border-rule pl-3">
        {entries.map((entry, index) => (
          <li key={index}>
            <span className="font-mono text-xs text-ink-soft">{formatDateTime(entry.at)}</span>
            <p>{entry.note}</p>
          </li>
        ))}
      </ol>
    </details>
  )
}

function BookingSummary({ booking, counterpart }) {
  const category = CATEGORIES[booking.listing.category]
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
          {category.label} · {booking.listing.area}
        </p>
        <Link to={`/rentals/${booking.listing_id}`} className="mt-0.5 block font-semibold hover:underline">
          {booking.listing.title}
        </Link>
        {booking.unit && <p className="text-sm font-medium">{unitLabel(booking.unit)}</p>}
        <p className="mt-1 text-sm text-ink-soft">
          {counterpart} · moves in {formatDay(booking.move_in_date)} · {formatTaka(booking.agreed_rent)}/month
        </p>
        <p className="text-sm text-ink-soft">
          Deposit {formatTaka(booking.deposit.amount)} via {DEPOSIT_METHODS[booking.deposit.method]} (ref.{' '}
          <span className="font-mono">{booking.deposit.reference}</span>) · {ESCROW_STATUS[booking.escrow_status]}
        </p>
      </div>
      <Stamp tone={BOOKING_STATUS[booking.status].tone}>{BOOKING_STATUS[booking.status].label}</Stamp>
    </div>
  )
}

function LeaseActions({ booking }) {
  const [error, setError] = useState('')
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={() => downloadFile(leasePath(booking.id), `${booking.lease_number}.pdf`).catch(() => setError('The lease PDF isn’t available.'))}
        className="inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-2 text-sm font-semibold text-white hover:bg-ink/90"
      >
        <Download className="size-4" aria-hidden="true" /> Lease {booking.lease_number}
      </button>
      <Link to={`/leases/${booking.id}`} className="text-sm font-semibold text-gate hover:underline">
        Open lease
      </Link>
      {booking.lease_verify_url && (
        <a href={booking.lease_verify_url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-gate hover:underline">
          Verification page
        </a>
      )}
      {error && <span className="text-sm text-tag-owner">{error}</span>}
    </div>
  )
}

export function OwnerRequestsPanel() {
  const { bookings, error, setError, replace } = useBookings('owner')
  const [issued, setIssued] = useState({}) // booking id -> issued QR
  const [working, setWorking] = useState(null)

  async function act(booking, action) {
    setWorking(booking.id)
    setError('')
    try {
      if (action === 'qr') {
        const result = await generateHandshakeQr(booking.id)
        setIssued((current) => ({ ...current, [booking.id]: result }))
        replace(result.booking)
      } else {
        if (!window.confirm(`Decline ${booking.tenant.full_name}'s request? Their deposit will be marked for refund.`)) return
        replace(await rejectBooking(booking.id))
      }
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setWorking(null)
    }
  }

  if (!bookings) return error ? <Alert>{error}</Alert> : <Spinner />
  if (bookings.length === 0) {
    return <EmptyState title="No rent requests yet.">When a tenant asks to rent one of your listings, it shows up here.</EmptyState>
  }
  return (
    <div className="space-y-3">
      <Alert>{error}</Alert>
      {bookings.map((booking) => (
        <article key={booking.id} className="rounded-xl border border-rule bg-sheet p-5">
          <BookingSummary
            booking={booking}
            counterpart={`${booking.tenant.full_name} (${booking.tenant.kyc_status === 'VERIFIED' ? 'ID verified' : 'ID not verified'}, ${booking.tenant.phone})`}
          />
          {booking.message && <p className="mt-2 rounded-md bg-plaster px-3 py-2 text-sm">“{booking.message}”</p>}
          {issued[booking.id] && booking.status === 'APPROVED' && (
            <div className="mt-4 rounded-lg border border-rule bg-white p-4">
              <HandshakeQr issued={issued[booking.id]} onRegenerate={() => act(booking, 'qr')} regenerating={working === booking.id} />
            </div>
          )}
          {['PENDING_OWNER', 'APPROVED'].includes(booking.status) && (
            <div className="mt-4 flex flex-wrap gap-2">
              {!(issued[booking.id] && booking.status === 'APPROVED') && (
                <Button type="button" busy={working === booking.id} onClick={() => act(booking, 'qr')}>
                  {booking.status === 'PENDING_OWNER' ? 'Approve and show QR' : 'Show handshake QR'}
                </Button>
              )}
              <button
                type="button"
                onClick={() => act(booking, 'reject')}
                disabled={working === booking.id}
                className="rounded-md border border-tag-owner/40 px-4 py-2 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8 disabled:opacity-60"
              >
                Decline
              </button>
            </div>
          )}
          {['CONFIRMED', 'ENDED'].includes(booking.status) && <LeaseActions booking={booking} />}
          <EscrowLedger entries={booking.escrow_ledger} />
        </article>
      ))}
    </div>
  )
}

export function TenantRentalsPanel() {
  const { bookings, error, setError, replace } = useBookings('tenant')
  const [scanningId, setScanningId] = useState(null)
  const [confirmed, setConfirmed] = useState(null)

  // Called from the scanner's confirmation dialog, which shows any error itself.
  async function confirm(token) {
    const result = await scanAndConfirm(token)
    setError('')
    replace(result.booking)
    setConfirmed(result.booking)
    setScanningId(null)
  }

  async function cancel(booking) {
    if (!window.confirm('Cancel this request? Your deposit will be marked for refund.')) return
    try {
      replace(await cancelBooking(booking.id))
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  if (!bookings) return error ? <Alert>{error}</Alert> : <Spinner />
  if (bookings.length === 0) {
    return (
      <EmptyState title="You haven't requested a place yet.">
        Find one on{' '}
        <Link to="/rentals" className="font-semibold text-gate hover:underline">
          the rentals map
        </Link>{' '}
        and choose “Request to rent”.
      </EmptyState>
    )
  }
  return (
    <div className="space-y-3">
      {confirmed && (
        <div className="flex items-start gap-3 rounded-xl border border-gate/40 bg-gate/8 p-4 text-sm text-gate-dark" role="status">
          <CheckCircle2 className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
          <p>
            Handshake confirmed. {confirmed.listing.title} is yours from {formatDay(confirmed.move_in_date)}. Your lease{' '}
            {confirmed.lease_number} is ready to download below.
          </p>
        </div>
      )}
      <Alert>{error}</Alert>
      {bookings.map((booking) => (
        <article key={booking.id} className="rounded-xl border border-rule bg-sheet p-5">
          <BookingSummary booking={booking} counterpart={`Owner ${booking.owner.full_name}, ${booking.owner.phone}`} />
          {booking.status === 'APPROVED' && (
            <div className="mt-4">
              {scanningId === booking.id ? (
                <TenantQRScanner bookings={bookings} onConfirm={confirm} />
              ) : (
                <Button type="button" onClick={() => setScanningId(booking.id)}>
                  <ScanLine className="size-4" aria-hidden="true" /> Scan the owner’s QR
                </Button>
              )}
            </div>
          )}
          {booking.status === 'PENDING_OWNER' && (
            <button type="button" onClick={() => cancel(booking)} className="mt-3 text-sm font-semibold text-tag-owner hover:underline">
              Cancel request
            </button>
          )}
          {['CONFIRMED', 'ENDED'].includes(booking.status) && <LeaseActions booking={booking} />}
          <EscrowLedger entries={booking.escrow_ledger} />
        </article>
      ))}
    </div>
  )
}

export function Spinner() {
  return (
    <div className="grid place-items-center py-12 text-ink-soft" role="status">
      <LoaderCircle className="size-6 animate-spin" aria-label="Loading" />
    </div>
  )
}
