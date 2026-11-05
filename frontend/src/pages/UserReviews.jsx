import { LoaderCircle, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { getUserReviews } from '../api/operations.js'
import { Stars } from '../components/lease/ReviewSection.jsx'
import { Alert, EmptyState } from '../components/ui.jsx'
import { formatDateTime } from '../constants/marketplace.js'
import { ROLES } from '../constants/roles.js'

// Public trust page: every review here comes from someone who shared a QR-confirmed lease with this person.
export default function UserReviews() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getUserReviews(id).then(setData, (err) => setError(getErrorMessage(err)))
  }, [id])

  if (error) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
        <Alert>{error}</Alert>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="grid flex-1 place-items-center text-ink-soft" role="status">
        <LoaderCircle className="size-6 animate-spin" aria-label="Loading reviews" />
      </div>
    )
  }

  const { summary, reviews } = data
  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-28 pt-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="text-sm font-medium text-ink-soft">{ROLES[summary.role].title}</p>
          <h1 className="font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">{summary.full_name}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 text-sm">
            {summary.kyc_status === 'VERIFIED' ? (
              <span className="inline-flex items-center gap-1 font-medium text-gate-dark">
                <ShieldCheck className="size-4" aria-hidden="true" /> Identity verified
              </span>
            ) : (
              <span className="text-ink-soft">Identity not verified</span>
            )}
            {summary.rating_average != null && (
              <span className="inline-flex items-center gap-1.5">
                <Stars rating={Math.round(summary.rating_average)} /> {summary.rating_average.toFixed(1)} from {summary.review_count}{' '}
                review{summary.review_count === 1 ? '' : 's'}
              </span>
            )}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs font-medium uppercase tracking-widest text-ink-soft">Trust score</p>
          <p className="font-mono text-5xl font-medium">{summary.trust_score}</p>
        </div>
      </div>

      <p className="mt-6 text-sm text-ink-soft">
        Only people who shared a QR-confirmed lease with {summary.full_name.split(' ')[0]} can review them. Everyone starts at 100;
        reviews move the score up or down gradually, so a single rating can't make or break it.
      </p>

      <ul className="mt-6 space-y-3">
        {reviews.length === 0 && <EmptyState title="No reviews yet." />}
        {reviews.map((review) => (
          <li key={review.id} className="rounded-xl border border-rule bg-sheet p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Stars rating={review.rating} />
              <span className="font-mono text-xs text-ink-soft">{formatDateTime(review.updated_at)}</span>
            </div>
            {review.comment && <p className="mt-2">“{review.comment}”</p>}
            <p className="mt-2 text-sm text-ink-soft">
              {review.reviewer.full_name}, {review.reviewer_side === 'TENANT' ? 'tenant' : 'owner'} at {review.listing_title}
            </p>
          </li>
        ))}
      </ul>
    </div>
  )
}
