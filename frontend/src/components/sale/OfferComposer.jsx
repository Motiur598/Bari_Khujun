import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { createOffer } from '../../api/marketplace.js'
import { OFFER_TYPES, formatPrice } from '../../constants/marketplace.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { Alert, Button, Segmented, TextField } from '../ui.jsx'

export default function OfferComposer({ listing }) {
  const { user } = useAuth()
  const asking = listing.sale.asking_price
  const [offerType, setOfferType] = useState('PURCHASE')
  const [amount, setAmount] = useState(String(asking))
  const [token, setToken] = useState(String(Math.round(asking * 0.1)))
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [sent, setSent] = useState(null)
  const [busy, setBusy] = useState(false)

  if (!user) {
    return (
      <p className="text-sm text-ink-soft">
        <Link to="/login" state={{ from: { pathname: `/sale/${listing.id}` } }} className="font-semibold text-gate hover:underline">
          Sign in
        </Link>{' '}
        with a buyer account to make an offer.
      </p>
    )
  }
  if (user.id === listing.lister_id) {
    return (
      <p className="text-sm text-ink-soft">
        Offers on your listing appear on your{' '}
        <Link to="/dashboard" className="font-semibold text-gate hover:underline">
          dashboard
        </Link>
        .
      </p>
    )
  }
  if (user.role !== 'BUYER') return <p className="text-sm text-ink-soft">Only buyer accounts can make offers.</p>
  if (listing.sale_status !== 'AVAILABLE') {
    return <p className="text-sm text-ink-soft">The seller has accepted an offer on this property, so it isn't taking new ones.</p>
  }
  if (sent) {
    return (
      <Alert tone="success">
        Offer of {formatPrice(sent.amount)} sent. Follow the negotiation on your{' '}
        <Link to="/dashboard" className="font-semibold underline">
          dashboard
        </Link>
        .
      </Alert>
    )
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      setSent(
        await createOffer({
          listing_id: listing.id,
          offer_type: offerType,
          amount: Number(amount),
          token_amount: offerType === 'TOKEN_MONEY' ? Number(token) : null,
          note: note.trim() || null,
        }),
      )
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const amountNumber = Number(amount) || 0
  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Segmented
        legend="Type of offer"
        name="offer_type"
        value={offerType}
        options={Object.entries(OFFER_TYPES)}
        onChange={setOfferType}
      />
      <TextField
        label="Your price (৳)"
        type="number"
        required
        min={1}
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        hint={`${formatPrice(amountNumber)} · ${amountNumber < asking ? `${(((asking - amountNumber) / asking) * 100).toFixed(1)}% under` : 'at or above'} the asking price`}
      />
      {offerType === 'TOKEN_MONEY' && (
        <TextField
          label="Bayna you'll pay on signing (৳)"
          type="number"
          required
          min={1}
          max={amountNumber - 1}
          value={token}
          onChange={(event) => setToken(event.target.value)}
          hint="Token money secures the deal before the sale deed; it counts toward the price."
        />
      )}
      <TextField
        label="Note to the seller (optional)"
        maxLength={500}
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <Alert>{error}</Alert>
      <Button type="submit" busy={busy} className="w-full">
        Send offer
      </Button>
    </form>
  )
}
