import { LoaderCircle, Star } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { getLeaseReviews, saveReview } from '../../api/operations.js'
import { formatDateTime } from '../../constants/marketplace.js'
import { Alert, Button } from '../ui.jsx'

const LABELS = ['', 'Poor', 'Below expectations', 'Okay', 'Good', 'Excellent']

export function Stars({ rating, size = 'size-4' }) {
  return (
    <span className="inline-flex" aria-label={`${rating} out of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} className={`${size} ${n <= rating ? 'fill-brass text-brass' : 'text-rule'}`} aria-hidden="true" />
      ))}
    </span>
  )
}

function StarInput({ value, onChange }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-medium">Rating</legend>
      <div className="flex items-center gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <label key={n} className="cursor-pointer rounded p-0.5 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-leaf">
            <input type="radio" name="rating" value={n} checked={value === n} onChange={() => onChange(n)} className="sr-only" />
            <Star className={`size-7 transition-colors ${n <= value ? 'fill-brass text-brass' : 'text-rule hover:text-brass'}`} aria-hidden="true" />
            <span className="sr-only">
              {n} star{n === 1 ? '' : 's'}
            </span>
          </label>
        ))}
        <span className="ml-2 text-sm text-ink-soft">{LABELS[value]}</span>
      </div>
    </fieldset>
  )
}

export default function ReviewSection({ lease }) {
  const other = lease.viewer_side === 'TENANT' ? lease.owner : lease.tenant
  const [reviews, setReviews] = useState(null)
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState('')
  const [saved, setSaved] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getLeaseReviews(lease.id).then((data) => {
      setReviews(data)
      if (data.mine) {
        setRating(data.mine.rating)
        setComment(data.mine.comment)
      }
    }, (err) => setError(getErrorMessage(err)))
  }, [lease.id])

  async function handleSubmit(event) {
    event.preventDefault()
    if (!rating) return setError('Pick a rating from 1 to 5 stars.')
    setBusy(true)
    setError('')
    try {
      const result = await saveReview({ booking_id: lease.id, rating, comment: comment.trim() })
      setSaved(result.reviewee)
      setReviews((current) => ({ ...current, mine: result.review }))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!reviews) return error ? <Alert>{error}</Alert> : <LoaderCircle className="mx-auto size-6 animate-spin text-ink-soft" aria-label="Loading reviews" />

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-rule bg-sheet p-5">
        <div>
          <h3 className="font-semibold">Your review of {other.full_name}</h3>
          <p className="text-sm text-ink-soft">
            Only people who shared a QR-confirmed lease can review each other. Your rating feeds into their trust score, and you can
            update it at any time.
          </p>
        </div>
        <StarInput value={rating} onChange={setRating} />
        <div>
          <label htmlFor="review-comment" className="mb-1.5 block text-sm font-medium">
            What should others know? <span className="font-normal text-ink-soft">(optional)</span>
          </label>
          <textarea
            id="review-comment"
            rows={3}
            maxLength={1000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className="w-full rounded-md border border-rule bg-white px-3 py-2.5"
          />
        </div>
        <Alert>{error}</Alert>
        {saved && (
          <Alert tone="success">
            Review saved. {saved.full_name}'s trust score is now {saved.trust_score}.
          </Alert>
        )}
        <Button type="submit" busy={busy}>
          {reviews.mine ? 'Update review' : 'Post review'}
        </Button>
      </form>

      <div className="rounded-xl border border-rule bg-sheet p-5">
        <h3 className="font-semibold">{other.full_name}'s review of you</h3>
        {reviews.theirs ? (
          <div className="mt-3 space-y-2">
            <Stars rating={reviews.theirs.rating} />
            {reviews.theirs.comment && <p className="text-sm">“{reviews.theirs.comment}”</p>}
            <p className="font-mono text-xs text-ink-soft">Updated {formatDateTime(reviews.theirs.updated_at)}</p>
          </div>
        ) : (
          <p className="mt-2 text-sm text-ink-soft">Not reviewed yet.</p>
        )}
        <Link to={`/users/${other.id}`} className="mt-4 inline-block text-sm font-semibold text-gate hover:underline">
          See all of {other.full_name.split(' ')[0]}'s reviews
        </Link>
      </div>
    </div>
  )
}
