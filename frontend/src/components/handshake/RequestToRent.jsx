import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { getMyBookings, requestToRent } from '../../api/handshake.js'
import { BOOKING_STATUS, DEPOSIT_METHODS, ESCROW_STATUS } from '../../constants/marketplace.js'
import { formatTaka, tenantCosts, unitChoices, unitKey, unitLabel } from '../../constants/rentals.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { Alert, Button, TextField } from '../ui.jsx'

const ROLE_FOR_CATEGORY = { FAMILY_FLAT: 'FAMILY_TENANT', BACHELOR_FLAT: 'BACHELOR_TENANT', BACHELOR_SEAT: 'BACHELOR_TENANT' }

function inDays(days) {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toLocaleDateString('en-CA')
}

// On a bachelor tenant's sublet, `unit` is the seat or room asked for; picking another room calls `onUnitChange`.
export default function RequestToRent({ listing, unit = null, onUnitChange }) {
  const { user } = useAuth()
  const expectedDeposit = tenantCosts(listing, unit).deposit
  const choices = unitChoices(listing)
  const [existing, setExisting] = useState(undefined)
  const [form, setForm] = useState({
    move_in_date: inDays(7),
    deposit_amount: String(expectedDeposit),
    payment_method: 'BKASH',
    payment_reference: '',
    message: '',
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const eligible = user && ROLE_FOR_CATEGORY[listing.category] === user.role && user.id !== listing.lister_id

  // A different seat or room has a different deposit.
  useEffect(() => {
    setForm((current) => ({ ...current, deposit_amount: String(expectedDeposit) }))
  }, [expectedDeposit])

  useEffect(() => {
    if (!eligible) return
    getMyBookings('tenant')
      .then((bookings) => setExisting(bookings.find((b) => b.listing_id === listing.id && ['PENDING_OWNER', 'APPROVED', 'CONFIRMED'].includes(b.status)) ?? null))
      .catch(() => setExisting(null))
  }, [eligible, listing.id])

  if (listing.rental_status === 'RENTED') {
    return <p className="text-sm text-ink-soft">This place has been rented.</p>
  }
  if (!user) {
    return (
      <p className="text-sm text-ink-soft">
        <Link to="/login" state={{ from: { pathname: `/rentals/${listing.id}` } }} className="font-semibold text-gate hover:underline">
          Sign in
        </Link>{' '}
        as a {listing.category === 'FAMILY_FLAT' ? 'family' : 'bachelor'} tenant to request this place.
      </p>
    )
  }
  if (!eligible) {
    return (
      <p className="text-sm text-ink-soft">
        {user.id === listing.lister_id
          ? 'Requests for this listing arrive on your dashboard.'
          : `Only ${listing.category === 'FAMILY_FLAT' ? 'family' : 'bachelor'} tenant accounts can request this place.`}
      </p>
    )
  }
  if (existing === undefined) return null
  if (existing) {
    return (
      <div className="space-y-1 text-sm">
        <p>
          Your request: <span className="font-semibold">{BOOKING_STATUS[existing.status].label}</span>
        </p>
        {existing.unit && <p>{unitLabel(existing.unit)}</p>}
        <p className="text-ink-soft">{ESCROW_STATUS[existing.escrow_status]}.</p>
        <Link to="/dashboard" className="inline-block font-semibold text-gate hover:underline">
          {existing.status === 'APPROVED' ? 'Scan the owner’s QR on your dashboard' : 'Open your dashboard'}
        </Link>
      </div>
    )
  }

  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      setExisting(
        await requestToRent({
          listing_id: listing.id,
          move_in_date: form.move_in_date,
          deposit_amount: Number(form.deposit_amount),
          payment_method: form.payment_method,
          payment_reference: form.payment_reference.trim(),
          message: form.message.trim() || null,
          room_id: unit?.room_id ?? null,
          whole_room: unit?.whole_room ?? false,
        }),
      )
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm text-ink-soft">
        Send the advance by mobile money or bank, then log it here. Bari Khujun holds it as pending until the owner
        answers, and marks it for refund if they decline.
      </p>
      {unit && listing.sublet.let_type === 'SEAT' && (
        <p className="text-sm">
          For: <span className="font-semibold">one seat in a shared room</span> · {formatTaka(tenantCosts(listing, unit).rent)}/month
        </p>
      )}
      {unit && listing.sublet.let_type === 'ROOMS' && (
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">What you're asking for</span>
          <select
            value={unitKey(unit)}
            onChange={(event) => onUnitChange(choices.find((choice) => unitKey(choice) === event.target.value))}
            className="w-full rounded-md border border-rule bg-white px-3 py-2.5"
          >
            {choices.map((choice) => (
              <option key={unitKey(choice)} value={unitKey(choice)}>
                {unitLabel(choice)} · {formatTaka(tenantCosts(listing, choice).rent)}/month
              </option>
            ))}
          </select>
        </label>
      )}
      <TextField label="Move-in date" type="date" required min={inDays(0)} value={form.move_in_date} onChange={set('move_in_date')} />
      <TextField
        label="Advance deposit paid (৳)"
        type="number"
        required
        min={1}
        value={form.deposit_amount}
        onChange={set('deposit_amount')}
        hint={`Listed deposit: ${listing.pricing.deposit_months} month${listing.pricing.deposit_months === 1 ? '' : 's'} = ${formatTaka(expectedDeposit)}`}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Paid with</span>
          <select
            value={form.payment_method}
            onChange={set('payment_method')}
            className="w-full rounded-md border border-rule bg-white px-3 py-2.5"
          >
            {Object.entries(DEPOSIT_METHODS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <TextField
          label="Transaction ID"
          required
          minLength={3}
          maxLength={60}
          placeholder="e.g. 9KD72LQ3XA"
          value={form.payment_reference}
          onChange={set('payment_reference')}
        />
      </div>
      <TextField label="Message to the owner (optional)" maxLength={500} value={form.message} onChange={set('message')} />
      <Alert>{error}</Alert>
      <Button type="submit" busy={busy} className="w-full">
        Request to rent
      </Button>
    </form>
  )
}
