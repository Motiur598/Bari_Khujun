import { Download, LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { downloadFile, getErrorMessage } from '../../api/client.js'
import { confirmInvoice, generateInvoices, getInvoices, payInvoice, receiptPath, rejectInvoicePayment } from '../../api/operations.js'
import { DEPOSIT_METHODS, formatDateTime } from '../../constants/marketplace.js'
import { INVOICE_EVENTS, INVOICE_STATUS, currentPeriod, monthLabel } from '../../constants/operations.js'
import { formatDay, formatTaka } from '../../constants/rentals.js'
import { Alert, Button, EmptyState, Stamp, TextField } from '../ui.jsx'

const UTILITIES = [
  ['electricity', 'Electricity'],
  ['gas', 'Gas'],
  ['water', 'Water'],
]

function BillForm({ lease, onCreated }) {
  const seats = lease.total_seats
  const [form, setForm] = useState({ period: currentPeriod(), electricity: '', gas: '', water: '', due_date: '' })
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value })
  const share = (amount) => (seats ? Math.ceil((Number(amount) || 0) / seats) : Number(amount) || 0)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const batch = await generateInvoices({
        listing_id: lease.listing_id,
        period: form.period,
        electricity: Number(form.electricity || 0),
        gas: Number(form.gas || 0),
        water: Number(form.water || 0),
        due_date: form.due_date || null,
      })
      setResult(batch)
      onCreated()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-rule bg-sheet p-5">
      <h3 className="font-semibold">Bill a month</h3>
      <p className="mt-1 text-sm text-ink-soft">
        {seats
          ? `Enter the whole flat's meter bills. Every active tenant on this listing gets an invoice with their rent plus a 1/${seats} share of each bill.`
          : lease.seats_held != null
            ? 'Enter one seat’s share of each bill. Every tenant you sublet to gets an invoice with their rent, their service charge and that share for each seat they hold.'
            : 'Enter this month’s meter bills. The invoice adds them to the rent and service charge.'}
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-4">
        <TextField label="Month" type="month" required value={form.period} onChange={set('period')} />
        {UTILITIES.map(([key, label]) => (
          <TextField
            key={key}
            label={`${label} (৳)`}
            type="number"
            min={0}
            value={form[key]}
            onChange={set(key)}
            hint={seats && form[key] ? `${formatTaka(share(form[key]))} per seat` : undefined}
          />
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <TextField label="Due date (optional)" type="date" value={form.due_date} onChange={set('due_date')} hint="Defaults to the 10th, or a week from today if that has passed." />
        <Button type="submit" busy={busy}>
          Issue invoices
        </Button>
      </div>
      <div className="mt-3 space-y-2">
        <Alert>{error}</Alert>
        {result && (
          <Alert tone="success">
            {result.created.length
              ? `Issued ${result.created.length} invoice${result.created.length === 1 ? '' : 's'} for ${monthLabel(form.period)}.`
              : 'No new invoices.'}
            {result.skipped.map((s) => ` ${s.tenant_name}: ${s.reason.toLowerCase()}.`).join('')}
          </Alert>
        )}
      </div>
    </form>
  )
}

function PayForm({ invoice, onDone }) {
  const [method, setMethod] = useState('BKASH')
  const [reference, setReference] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      onDone(await payInvoice(invoice.id, { method, reference: reference.trim() }))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 flex flex-wrap items-end gap-3 border-t border-rule pt-4">
      <label className="block text-sm">
        <span className="mb-1 block font-medium">Paid with</span>
        <select value={method} onChange={(e) => setMethod(e.target.value)} className="rounded-md border border-rule bg-white px-3 py-2.5">
          {Object.entries(DEPOSIT_METHODS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <TextField label="Transaction ID" required minLength={3} maxLength={60} value={reference} onChange={(e) => setReference(e.target.value)} />
      <Button type="submit" busy={busy}>
        Send payment details
      </Button>
      <div className="w-full">
        <Alert>{error}</Alert>
      </div>
    </form>
  )
}

function OwnerActions({ invoice, onDone }) {
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run(action) {
    setBusy(true)
    setError('')
    try {
      onDone(await action())
      setRejecting(false)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 border-t border-rule pt-4">
      {invoice.status === 'PAYMENT_SUBMITTED' && !rejecting && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="mr-auto text-sm">
            Check your {DEPOSIT_METHODS[invoice.payment.method]} for <span className="font-mono">{invoice.payment.reference}</span>.
          </p>
          <Button type="button" busy={busy} onClick={() => run(() => confirmInvoice(invoice.id))}>
            Confirm payment
          </Button>
          <button type="button" onClick={() => setRejecting(true)} className="rounded-md border border-tag-owner/40 px-3 py-2 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8">
            Not received
          </button>
        </div>
      )}
      {rejecting && (
        <div className="flex flex-wrap items-end gap-2">
          <TextField label="Tell the tenant what's wrong" required minLength={3} value={note} onChange={(e) => setNote(e.target.value)} className="min-w-0 flex-1" />
          <button
            type="button"
            disabled={busy || note.trim().length < 3}
            onClick={() => run(() => rejectInvoicePayment(invoice.id, note.trim()))}
            className="rounded-md bg-tag-owner px-3 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            Send back
          </button>
        </div>
      )}
      {invoice.status === 'UNPAID' && (
        <button
          type="button"
          disabled={busy}
          onClick={() => window.confirm('Record this invoice as paid in cash?') && run(() => confirmInvoice(invoice.id, { method: 'CASH' }))}
          className="text-sm font-semibold text-gate hover:underline"
        >
          Record a cash payment
        </button>
      )}
      <Alert>{error}</Alert>
    </div>
  )
}

function InvoiceCard({ invoice, side, onChange }) {
  const statusKey = invoice.overdue ? 'OVERDUE' : invoice.status
  const status = INVOICE_STATUS[statusKey]
  const split = invoice.split_seats
  return (
    <article className="rounded-xl border border-rule bg-sheet p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-2xl font-extrabold uppercase tracking-wide">{monthLabel(invoice.period)}</h3>
          <p className="font-mono text-xs text-ink-soft">
            {invoice.number} · due {formatDay(invoice.due_date)}
          </p>
        </div>
        <div className="text-right">
          <Stamp tone={status.tone}>{status.label}</Stamp>
          <p className="mt-2 font-mono text-2xl font-medium">{formatTaka(invoice.total)}</p>
        </div>
      </div>

      <table className="mt-4 w-full text-sm">
        {split && (
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-ink-soft">
              <th className="pb-1 font-medium">Item</th>
              <th className="pb-1 text-right font-medium">Whole flat</th>
              <th className="pb-1 text-right font-medium">÷ {split} seats</th>
            </tr>
          </thead>
        )}
        <tbody>
          {invoice.lines.map((line) => (
            <tr key={line.key} className="border-t border-rule">
              <td className="py-1.5">{line.label}</td>
              {split && <td className="py-1.5 text-right font-mono text-ink-soft">{line.flat_amount != null ? formatTaka(line.flat_amount) : '—'}</td>}
              <td className="py-1.5 text-right font-mono">{formatTaka(line.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {invoice.payment && (
        <p className="mt-3 text-sm text-ink-soft">
          {invoice.payment.recorded_by === 'OWNER' ? 'Recorded by owner' : 'Sent'} via {DEPOSIT_METHODS[invoice.payment.method]} · ref.{' '}
          <span className="font-mono text-ink">{invoice.payment.reference}</span>
        </p>
      )}
      {invoice.status === 'UNPAID' && invoice.history.at(-1)?.event === 'PAYMENT_REJECTED' && (
        <p className="mt-3 rounded-md bg-tag-owner/8 px-3 py-2 text-sm text-tag-owner">
          The owner couldn't find your payment: “{invoice.history.at(-1).note}”
        </p>
      )}

      {invoice.status === 'PAID' && (
        <button
          type="button"
          onClick={() => downloadFile(receiptPath(invoice.id), `${invoice.receipt_number}.pdf`)}
          className="mt-4 inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-2 text-sm font-semibold text-white hover:bg-ink/90"
        >
          <Download className="size-4" aria-hidden="true" /> Receipt {invoice.receipt_number}
        </button>
      )}
      {side === 'TENANT' && invoice.status === 'UNPAID' && <PayForm invoice={invoice} onDone={onChange} />}
      {side === 'OWNER' && invoice.status !== 'PAID' && <OwnerActions invoice={invoice} onDone={onChange} />}

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer font-medium text-ink-soft hover:text-ink">History ({invoice.history.length})</summary>
        <ol className="mt-2 space-y-1 border-l-2 border-rule pl-3">
          {invoice.history.map((event, index) => (
            <li key={index}>
              <span className="font-mono text-xs text-ink-soft">{formatDateTime(event.at)}</span> ·{' '}
              {event.actor === 'OWNER' ? invoice.owner.full_name : invoice.tenant.full_name} {INVOICE_EVENTS[event.event]}
              {event.note && <span className="text-ink-soft"> — {event.note}</span>}
            </li>
          ))}
        </ol>
      </details>
    </article>
  )
}

export default function InvoicesSection({ lease }) {
  const [invoices, setInvoices] = useState(null)
  const [error, setError] = useState('')

  const load = () => getInvoices(lease.id).then(setInvoices, (err) => setError(getErrorMessage(err)))
  useEffect(() => {
    load()
  }, [lease.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const replace = (next) => setInvoices((list) => list.map((invoice) => (invoice.id === next.id ? next : invoice)))
  const unpaid = (invoices ?? []).filter((invoice) => invoice.status !== 'PAID').reduce((sum, invoice) => sum + invoice.total, 0)

  return (
    <div className="space-y-4">
      {lease.viewer_side === 'OWNER' && lease.status === 'CONFIRMED' && <BillForm lease={lease} onCreated={load} />}
      {error && <Alert>{error}</Alert>}
      {invoices === null ? (
        <LoaderCircle className="mx-auto size-6 animate-spin text-ink-soft" aria-label="Loading invoices" />
      ) : invoices.length === 0 ? (
        <EmptyState title="No invoices yet.">
          {lease.viewer_side === 'OWNER' ? 'Bill the first month above.' : 'Monthly bills from the owner show up here.'}
        </EmptyState>
      ) : (
        <>
          {unpaid > 0 && (
            <p className="text-sm">
              Outstanding: <span className="font-mono font-medium">{formatTaka(unpaid)}</span>
            </p>
          )}
          {invoices.map((invoice) => (
            <InvoiceCard key={invoice.id} invoice={invoice} side={lease.viewer_side} onChange={replace} />
          ))}
        </>
      )}
    </div>
  )
}
