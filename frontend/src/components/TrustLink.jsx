import { Star } from 'lucide-react'
import { Link } from 'react-router-dom'

// Compact trust line for a person card, linking to their public review page.
export default function TrustLink({ person }) {
  return (
    <Link to={`/users/${person.id}`} className="mt-2 flex items-center justify-between gap-3 text-sm hover:underline">
      <span className="inline-flex items-center gap-1">
        <Star className="size-4 fill-brass text-brass" aria-hidden="true" />
        {person.review_count ? (
          <>
            {person.rating_average.toFixed(1)} · {person.review_count} review{person.review_count === 1 ? '' : 's'}
          </>
        ) : (
          <span className="text-ink-soft">No reviews yet</span>
        )}
      </span>
      <span>
        Trust score <span className="font-mono font-medium">{person.trust_score}</span>
      </span>
    </Link>
  )
}
