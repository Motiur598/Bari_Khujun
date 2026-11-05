import { Check, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { advanceTicket, commentOnTicket, getTickets, reportIssue, ticketPhotoPath } from '../../api/operations.js'
import { formatDateTime } from '../../constants/marketplace.js'
import { TICKET_CATEGORIES, TICKET_PRIORITIES, TICKET_STEPS } from '../../constants/operations.js'
import AuthImage from '../AuthImage.jsx'
import { Alert, Button, EmptyState, Segmented, TextField } from '../ui.jsx'

function ReportForm({ lease, onCreated }) {
  const photoInput = useRef(null)
  const [form, setForm] = useState({ category: 'PLUMBING', priority: 'NORMAL', title: '', description: '' })
  const [photos, setPhotos] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (field) => (value) => setForm({ ...form, [field]: value })

  async function handleSubmit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      onCreated(await reportIssue({ bookingId: lease.id, ...form, title: form.title.trim(), description: form.description.trim(), photos }))
      setForm({ category: 'PLUMBING', priority: 'NORMAL', title: '', description: '' })
      setPhotos([])
      photoInput.current.value = ''
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-rule bg-sheet p-5">
      <h3 className="font-semibold">Report a problem</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">What kind</span>
          <select value={form.category} onChange={(e) => set('category')(e.target.value)} className="w-full rounded-md border border-rule bg-white px-3 py-2.5">
            {Object.entries(TICKET_CATEGORIES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Segmented legend="How soon" name="priority" value={form.priority} options={Object.entries(TICKET_PRIORITIES)} onChange={set('priority')} />
      </div>
      <TextField label="Short title" required minLength={3} maxLength={120} placeholder="Kitchen sink is blocked" value={form.title} onChange={(e) => set('title')(e.target.value)} />
      <div>
        <label htmlFor="ticket-description" className="mb-1.5 block text-sm font-medium">
          Details <span className="font-normal text-ink-soft">(optional)</span>
        </label>
        <textarea
          id="ticket-description"
          rows={3}
          maxLength={2000}
          value={form.description}
          onChange={(e) => set('description')(e.target.value)}
          className="w-full rounded-md border border-rule bg-white px-3 py-2.5"
        />
      </div>
      <label className="block text-sm">
        <span className="mb-1.5 block font-medium">Photos (up to 5)</span>
        <input
          ref={photoInput}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          onChange={(e) => setPhotos([...e.target.files].slice(0, 5))}
          className="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-rule file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-semibold"
        />
      </label>
      <Alert>{error}</Alert>
      <Button type="submit" busy={busy}>
        Send to owner
      </Button>
    </form>
  )
}

function StatusTrack({ status }) {
  const reached = TICKET_STEPS.findIndex(([key]) => key === status)
  return (
    <ol className="flex items-center gap-1 text-xs" aria-label={`Status: ${TICKET_STEPS[reached][1]}`}>
      {TICKET_STEPS.map(([key, label], index) => (
        <li key={key} className="flex items-center gap-1">
          {index > 0 && <span aria-hidden="true" className={`h-0.5 w-6 ${index <= reached ? 'bg-gate' : 'bg-rule'}`} />}
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${
              index < reached ? 'bg-gate/10 text-gate-dark' : index === reached ? 'bg-gate text-white' : 'bg-plaster text-ink-soft'
            }`}
          >
            {index < reached && <Check className="size-3" aria-hidden="true" />}
            {label}
          </span>
        </li>
      ))}
    </ol>
  )
}

function TicketCard({ ticket, side, onChange }) {
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const next = { OPEN: ['IN_PROGRESS', 'Start work'], IN_PROGRESS: ['RESOLVED', 'Mark resolved'] }[ticket.status]

  async function run(action) {
    setBusy(true)
    setError('')
    try {
      onChange(await action())
      setNote('')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const who = (actor) => (actor === 'OWNER' ? ticket.owner.full_name : ticket.tenant.full_name)
  return (
    <article className="rounded-xl border border-rule bg-sheet p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
            {TICKET_CATEGORIES[ticket.category]} ·{' '}
            <span className={ticket.priority === 'URGENT' ? 'text-tag-owner' : ''}>{TICKET_PRIORITIES[ticket.priority]}</span>
          </p>
          <h3 className="mt-0.5 font-semibold">{ticket.title}</h3>
        </div>
        <StatusTrack status={ticket.status} />
      </div>
      {ticket.description && <p className="mt-2 whitespace-pre-line text-sm">{ticket.description}</p>}
      {ticket.photos.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {ticket.photos.map((photo) => (
            <li key={photo.id} className="w-28 overflow-hidden rounded-md border border-rule">
              <AuthImage path={ticketPhotoPath(ticket.id, photo.id)} alt={`Photo for ${ticket.title}`} className="aspect-square w-full" />
            </li>
          ))}
        </ul>
      )}
      <ol className="mt-4 space-y-2 border-l-2 border-rule pl-3 text-sm">
        {ticket.updates.map((update, index) => (
          <li key={index}>
            <span className="font-mono text-xs text-ink-soft">{formatDateTime(update.at)}</span>{' '}
            <span className="font-medium">{who(update.actor)}</span>
            {update.status && <span className="text-ink-soft"> → {TICKET_STEPS.find(([key]) => key === update.status)[1].toLowerCase()}</span>}
            {update.note && <p>{update.note}</p>}
          </li>
        ))}
      </ol>
      <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-rule pt-4">
        <TextField
          label={side === 'OWNER' && next ? 'Note (optional with a status change)' : 'Add a note'}
          maxLength={500}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="min-w-0 flex-1"
        />
        <button
          type="button"
          disabled={busy || !note.trim()}
          onClick={() => run(() => commentOnTicket(ticket.id, note.trim()))}
          className="rounded-md border border-rule bg-white px-3 py-2.5 text-sm font-semibold hover:border-ink disabled:opacity-50"
        >
          Post note
        </button>
        {side === 'OWNER' && next && (
          <Button type="button" busy={busy} onClick={() => run(() => advanceTicket(ticket.id, next[0], note.trim()))}>
            {next[1]}
          </Button>
        )}
      </div>
      <Alert>{error}</Alert>
    </article>
  )
}

export default function MaintenanceSection({ lease }) {
  const [tickets, setTickets] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getTickets(lease.id).then(setTickets, (err) => setError(getErrorMessage(err)))
  }, [lease.id])

  const replace = (next) => setTickets((list) => list.map((ticket) => (ticket.id === next.id ? next : ticket)))
  const canReport = lease.viewer_side === 'TENANT' && lease.status === 'CONFIRMED'

  return (
    <div className="space-y-4">
      {canReport && <ReportForm lease={lease} onCreated={(ticket) => setTickets((list) => [ticket, ...(list ?? [])])} />}
      {error && <Alert>{error}</Alert>}
      {tickets === null ? (
        <LoaderCircle className="mx-auto size-6 animate-spin text-ink-soft" aria-label="Loading repairs" />
      ) : tickets.length === 0 ? (
        <EmptyState title="No repairs reported.">
          {lease.viewer_side === 'OWNER' ? 'Problems your tenant reports appear here.' : canReport ? null : 'Repairs can be reported while the lease is active.'}
        </EmptyState>
      ) : (
        tickets.map((ticket) => <TicketCard key={ticket.id} ticket={ticket} side={lease.viewer_side} onChange={replace} />)
      )}
    </div>
  )
}
