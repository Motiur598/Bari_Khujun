import { Ban, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { banScammer } from '../../api/governance.js'
import { Alert } from '../ui.jsx'

// Confirmation for the cascading ban. `target` is { id, full_name } or null when closed.
export default function BanDialog({ target, defaultReason = '', onClose, onBanned }) {
  const dialogRef = useRef(null)
  const [reason, setReason] = useState(defaultReason)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const dialog = dialogRef.current
    if (target && !dialog.open) {
      setReason(defaultReason)
      setResult(null)
      setError('')
      dialog.showModal()
    }
    if (!target && dialog.open) dialog.close()
  }, [target, defaultReason])

  async function handleBan() {
    setBusy(true)
    setError('')
    try {
      const outcome = await banScammer(target.id, reason.trim())
      setResult(outcome)
      onBanned?.(outcome)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-labelledby="ban-heading"
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-xl bg-sheet p-0 text-ink shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-rule px-5 py-4">
        <h2 id="ban-heading" className="font-display text-2xl font-extrabold uppercase tracking-wide">
          Ban {target?.full_name}
        </h2>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-soft hover:bg-plaster hover:text-ink">
          <X className="size-5" aria-hidden="true" />
        </button>
      </div>
      <div className="space-y-4 p-5">
        {result ? (
          <Alert tone="success">
            {result.full_name} is banned. Suspended {result.listings_suspended} listing{result.listings_suspended === 1 ? '' : 's'}, cancelled and refunded{' '}
            {result.bookings_cancelled} open request{result.bookings_cancelled === 1 ? '' : 's'}, revoked {result.qr_codes_revoked} live QR code
            {result.qr_codes_revoked === 1 ? '' : 's'}, closed {result.offers_closed} offer{result.offers_closed === 1 ? '' : 's'} and called off{' '}
            {result.visits_cancelled} visit{result.visits_cancelled === 1 ? '' : 's'}.
          </Alert>
        ) : (
          <>
            <div className="text-sm">
              <p>This takes effect immediately and can't be undone from the app:</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-soft">
                <li>They're signed out and can't sign in again.</li>
                <li>All their listings disappear from search.</li>
                <li>Their open rent requests are cancelled, deposits marked for refund, and any live QR code stops working.</li>
                <li>Open offers close and upcoming visits are called off.</li>
              </ul>
              <p className="mt-2 text-ink-soft">Active leases stay in place so current tenants aren't affected.</p>
            </div>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Reason (kept in the audit log)</span>
              <textarea
                rows={3}
                value={reason}
                maxLength={500}
                onChange={(e) => setReason(e.target.value)}
                className="w-full rounded-md border border-rule bg-white px-3 py-2"
              />
            </label>
            <Alert>{error}</Alert>
            <button
              type="button"
              disabled={busy || reason.trim().length < 3}
              onClick={handleBan}
              className="inline-flex items-center gap-1.5 rounded-md bg-tag-owner px-4 py-2.5 text-sm font-semibold text-white hover:bg-tag-owner/90 disabled:opacity-50"
            >
              <Ban className="size-4" aria-hidden="true" /> Ban and suspend everything
            </button>
          </>
        )}
      </div>
    </dialog>
  )
}
