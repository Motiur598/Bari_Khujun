import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { getMyOffers, respondToOffer } from '../../api/marketplace.js'
import { OFFER_EVENTS, OFFER_STATUS, OFFER_TYPES, formatDateTime, formatPrice } from '../../constants/marketplace.js'
import { formatTaka } from '../../constants/rentals.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { Alert, Button, EmptyState, Stamp } from '../ui.jsx'
import { Spinner } from './RentalPanels.jsx'

function OfferThread({ offer, me, onChange }) {
  const isBuyer = offer.buyer.id === me
  const myTurn = (offer.status === 'AWAITING_SELLER' && !isBuyer) || (offer.status === 'AWAITING_BUYER' && isBuyer)
  const open = offer.status === 'AWAITING_SELLER' || offer.status === 'AWAITING_BUYER'
  const [countering, setCountering] = useState(false)
  const [amount, setAmount] = useState(String(offer.amount))
  const [token, setToken] = useState(String(offer.token_amount ?? ''))
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(null)

  async function respond(action) {
    if (action === 'ACCEPT' && !window.confirm(`Accept ${formatPrice(offer.amount)}? This takes the property off the market.`)) return
    setBusy(action)
    setError('')
    try {
      const payload = { action, note: note.trim() || null }
      if (action === 'COUNTER') {
        payload.amount = Number(amount)
        if (offer.offer_type === 'TOKEN_MONEY') payload.token_amount = Number(token)
      }
      onChange(await respondToOffer(offer.id, payload))
      setCountering(false)
      setNote('')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  const party = (actor) => (actor === 'SYSTEM' ? 'Bari Khujun' : actor === 'BUYER' ? offer.buyer.full_name : offer.seller.full_name)

  return (
    <article className="rounded-xl border border-rule bg-sheet p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
            {OFFER_TYPES[offer.offer_type]} · {isBuyer ? `to ${offer.seller.full_name}` : `from ${offer.buyer.full_name}`}
          </p>
          <Link to={`/sale/${offer.listing_id}`} className="mt-0.5 block font-semibold hover:underline">
            {offer.listing_title}
          </Link>
          <p className="mt-1 text-sm">
            On the table: <span className="font-mono font-medium">{formatTaka(offer.amount)}</span>
            {offer.token_amount != null && (
              <span className="text-ink-soft">
                {' '}
                with <span className="font-mono">{formatTaka(offer.token_amount)}</span> bayna
              </span>
            )}
            <span className="text-ink-soft"> · asking {formatPrice(offer.asking_price)}</span>
          </p>
        </div>
        <Stamp tone={OFFER_STATUS[offer.status].tone}>{OFFER_STATUS[offer.status].label}</Stamp>
      </div>

      <ol className="mt-4 space-y-3 border-l-2 border-rule pl-4">
        {offer.history.map((event, index) => (
          <li key={index} className="relative">
            <span
              aria-hidden="true"
              className={`absolute -left-[1.4rem] top-1 size-3 rounded-full border-2 border-sheet ${
                event.actor === 'BUYER' ? 'bg-tag-bachelor' : event.actor === 'SELLER' ? 'bg-tag-owner' : 'bg-ink-soft'
              }`}
            />
            <p className="text-sm">
              <span className="font-semibold">{party(event.actor)}</span> {OFFER_EVENTS[event.event]}
              {['OFFERED', 'COUNTERED'].includes(event.event) && (
                <>
                  {' '}
                  <span className="font-mono">{formatTaka(event.amount)}</span>
                  {event.token_amount != null && <span className="text-ink-soft"> (bayna {formatTaka(event.token_amount)})</span>}
                </>
              )}
            </p>
            {event.note && <p className="text-sm text-ink-soft">“{event.note}”</p>}
            <p className="font-mono text-xs text-ink-soft">{formatDateTime(event.at)}</p>
          </li>
        ))}
      </ol>

      {open && (
        <div className="mt-4 border-t border-rule pt-4">
          {myTurn ? (
            countering ? (
              <div className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block text-sm">
                    <span className="mb-1 block font-medium">Counter price (৳)</span>
                    <input type="number" min={1} value={amount} onChange={(e) => setAmount(e.target.value)} className="w-full rounded-md border border-rule bg-white px-3 py-2 font-mono" />
                  </label>
                  {offer.offer_type === 'TOKEN_MONEY' && (
                    <label className="block text-sm">
                      <span className="mb-1 block font-medium">Bayna (৳)</span>
                      <input type="number" min={1} value={token} onChange={(e) => setToken(e.target.value)} className="w-full rounded-md border border-rule bg-white px-3 py-2 font-mono" />
                    </label>
                  )}
                </div>
                <NoteField value={note} onChange={setNote} />
                <div className="flex flex-wrap gap-2">
                  <Button type="button" busy={busy === 'COUNTER'} onClick={() => respond('COUNTER')}>
                    Send counter-offer
                  </Button>
                  <button type="button" onClick={() => setCountering(false)} className="px-3 text-sm font-semibold text-ink-soft hover:text-ink">
                    Back
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <NoteField value={note} onChange={setNote} />
                <div className="flex flex-wrap gap-2">
                  <Button type="button" busy={busy === 'ACCEPT'} onClick={() => respond('ACCEPT')}>
                    Accept {formatPrice(offer.amount)}
                  </Button>
                  <button
                    type="button"
                    onClick={() => setCountering(true)}
                    className="rounded-md border border-rule bg-white px-4 py-2 text-sm font-semibold hover:border-ink"
                  >
                    Counter
                  </button>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => respond('REJECT')}
                    className="rounded-md border border-tag-owner/40 px-4 py-2 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8 disabled:opacity-60"
                  >
                    Reject
                  </button>
                </div>
              </div>
            )
          ) : (
            <p className="text-sm text-ink-soft">Waiting for {isBuyer ? offer.seller.full_name : offer.buyer.full_name} to respond.</p>
          )}
          {isBuyer && (
            <button type="button" onClick={() => respond('WITHDRAW')} disabled={busy !== null} className="mt-3 text-sm font-semibold text-tag-owner hover:underline">
              Withdraw offer
            </button>
          )}
          <Alert>{error}</Alert>
        </div>
      )}
    </article>
  )
}

function NoteField({ value, onChange }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">Note (optional)</span>
      <input value={value} maxLength={500} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-rule bg-white px-3 py-2" />
    </label>
  )
}

export default function OffersPanel({ side }) {
  const { user } = useAuth()
  const [offers, setOffers] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getMyOffers(side).then(setOffers, (err) => setError(getErrorMessage(err)))
  }, [side])

  if (!offers) return error ? <Alert>{error}</Alert> : <Spinner />
  if (offers.length === 0) {
    return side === 'seller' ? (
      <EmptyState title="No offers yet.">Offers buyers make on your properties show up here.</EmptyState>
    ) : (
      <EmptyState title="You haven't made any offers.">
        Browse{' '}
        <Link to="/sale" className="font-semibold text-gate hover:underline">
          properties for sale
        </Link>{' '}
        to make one.
      </EmptyState>
    )
  }
  return (
    <div className="space-y-3">
      {offers.map((offer) => (
        <OfferThread
          key={offer.id}
          offer={offer}
          me={user.id}
          onChange={(next) => setOffers((list) => list.map((o) => (o.id === next.id ? next : o)))}
        />
      ))}
    </div>
  )
}
