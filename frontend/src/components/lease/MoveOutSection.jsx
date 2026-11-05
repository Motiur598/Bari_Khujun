import { CalendarCheck } from 'lucide-react'
import { useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { giveMoveOutNotice } from '../../api/operations.js'
import { formatDateTime } from '../../constants/marketplace.js'
import { formatDay } from '../../constants/rentals.js'
import { Alert, Button, TextField } from '../ui.jsx'

export default function MoveOutSection({ lease, onLeaseChange }) {
  const window_ = lease.notice_window
  const [date, setDate] = useState(window_?.earliest ?? '')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const unit = lease.unit ? (lease.unit.whole_room ? 'room' : 'seat') : lease.total_seats ? 'seat' : 'flat'
  const tenantView = lease.viewer_side === 'TENANT'

  async function handleSubmit(event) {
    event.preventDefault()
    if (!window.confirm(`Give notice to move out on ${formatDay(date)}? This can't be withdrawn in the app.`)) return
    setBusy(true)
    setError('')
    try {
      onLeaseChange(await giveMoveOutNotice(lease.id, { move_out_date: date, reason: reason.trim() || null }))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (lease.status === 'ENDED') {
    return (
      <p className="text-sm">
        This lease ended on {formatDateTime(lease.ended_at)}. The {unit} went back on the market that day.
      </p>
    )
  }

  if (lease.move_out) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-rule bg-sheet p-5">
        <CalendarCheck className="mt-0.5 size-5 shrink-0 text-gate" aria-hidden="true" />
        <div className="text-sm">
          <p className="font-semibold">
            {tenantView ? 'You move out' : `${lease.tenant.full_name} moves out`} on {formatDay(lease.move_out.move_out_date)}.
          </p>
          <p className="mt-1 text-ink-soft">
            Notice given {formatDateTime(lease.move_out.notice_given_at)}
            {lease.move_out.reason && ` · “${lease.move_out.reason}”`}. The listing already shows the date the {unit} reopens,
            and it goes back on the market automatically that day.
          </p>
        </div>
      </div>
    )
  }

  if (!tenantView) {
    return <p className="text-sm text-ink-soft">{lease.tenant.full_name} hasn't given notice. The lease runs until they do.</p>
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-rule bg-sheet p-5">
      <p className="text-sm text-ink-soft">
        Give between one and two months' notice. On your move-out date the {unit} reopens for new tenants, and the owner sees
        the date straight away.
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <TextField
          label="Move-out date"
          type="date"
          required
          min={window_.earliest}
          max={window_.latest}
          value={date}
          onChange={(e) => setDate(e.target.value)}
          hint={`Between ${formatDay(window_.earliest)} and ${formatDay(window_.latest)}`}
        />
        <TextField label="Reason (optional)" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="mt-4 space-y-2">
        <Alert>{error}</Alert>
        <Button type="submit" busy={busy}>
          Give notice
        </Button>
      </div>
    </form>
  )
}
