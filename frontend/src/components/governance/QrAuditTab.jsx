import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { getQrHandshakes, revokeQr } from '../../api/governance.js'
import { formatDateTime } from '../../constants/marketplace.js'
import { CODE_STATES, QR_EVENTS } from '../../constants/governance.js'
import { Spinner } from '../dashboard/RentalPanels.jsx'
import { Alert, EmptyState, Segmented, Stamp } from '../ui.jsx'

const FILTERS = [
  ['', 'All'],
  ['ACTIVE', 'Live'],
  ['EXPIRED', 'Expired'],
  ['USED', 'Confirmed'],
  ['NONE', 'Closed'],
]

function HandshakeRow({ row, onRevoked, onBan }) {
  const [error, setError] = useState('')
  const rejected = row.events.filter((e) => e.event === 'SCAN_REJECTED').length

  async function revoke() {
    const reason = window.prompt('Why are you revoking this code?')
    if (!reason || reason.trim().length < 3) return
    try {
      await revokeQr(row.booking_id, reason.trim())
      onRevoked()
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  return (
    <li className="rounded-xl border border-rule bg-sheet">
      <details>
        <summary className="flex cursor-pointer flex-wrap items-center gap-x-4 gap-y-2 p-4 marker:content-none">
          <div className="min-w-0 flex-1">
            <Link to={`/rentals/${row.listing_id}`} className="font-semibold hover:underline" onClick={(e) => e.stopPropagation()}>
              {row.listing_title}
            </Link>
            <p className="text-sm text-ink-soft">
              {row.owner.full_name} → {row.tenant.full_name} · {row.codes_issued} code{row.codes_issued === 1 ? '' : 's'} issued
              {rejected > 0 && <span className="text-tag-owner"> · {rejected} rejected scan{rejected === 1 ? '' : 's'}</span>}
            </p>
          </div>
          <div className="text-right text-xs text-ink-soft">
            <p className="font-mono">{formatDateTime(row.last_event_at)}</p>
            {row.expires_at && <p>expires {formatDateTime(row.expires_at)}</p>}
            {row.lease_number && <p className="font-mono">{row.lease_number}</p>}
          </div>
          <Stamp tone={CODE_STATES[row.code_state].tone}>{CODE_STATES[row.code_state].label}</Stamp>
        </summary>
        <div className="border-t border-rule px-4 pb-4 pt-3">
          <ol className="space-y-1.5 border-l-2 border-rule pl-3 text-sm">
            {row.events.map((event, index) => (
              <li key={index}>
                <span className="font-mono text-xs text-ink-soft">{formatDateTime(event.at)}</span>{' '}
                <span className={`font-medium ${event.event === 'SCAN_REJECTED' || event.event === 'REVOKED' ? 'text-tag-owner' : ''}`}>
                  {QR_EVENTS[event.event]}
                </span>
                {event.nonce_fp && <span className="font-mono text-xs text-ink-soft"> #{event.nonce_fp}</span>}
                {event.detail && <span className="text-ink-soft"> · {event.detail}</span>}
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs text-ink-soft">#… is a fingerprint of each code's single-use nonce, so you can tell codes apart.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {['ACTIVE', 'EXPIRED'].includes(row.code_state) && (
              <button type="button" onClick={revoke} className="rounded-md border border-rule bg-white px-3 py-1.5 text-sm font-semibold hover:border-ink">
                Revoke code
              </button>
            )}
            <button
              type="button"
              onClick={() => onBan(row.owner)}
              className="rounded-md border border-tag-owner/40 px-3 py-1.5 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8"
            >
              Ban owner
            </button>
          </div>
          <Alert>{error}</Alert>
        </div>
      </details>
    </li>
  )
}

export default function QrAuditTab({ onBan, refreshKey, onChanged }) {
  const [state, setState] = useState('')
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setRows(null)
    getQrHandshakes(state).then(setRows, (err) => setError(getErrorMessage(err)))
  }, [state])
  useEffect(load, [load, refreshKey])

  return (
    <div className="space-y-4">
      <Segmented legend="Codes" name="qr-filter" value={state} options={FILTERS} onChange={setState} className="sm:w-[32rem]" />
      {error && <Alert>{error}</Alert>}
      {rows === null ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <EmptyState title="No handshakes match." />
      ) : (
        <ul className="space-y-2">
          {rows.map((row) => (
            <HandshakeRow
              key={row.booking_id}
              row={row}
              onBan={onBan}
              onRevoked={() => {
                load()
                onChanged()
              }}
            />
          ))}
        </ul>
      )}
    </div>
  )
}
