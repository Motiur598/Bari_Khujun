import { MapPin } from 'lucide-react'
import { Link } from 'react-router-dom'
import { HANDOVER, PROPERTY_TYPES, formatPrice } from '../../constants/marketplace.js'
import { areaLabel, commuteHint, formatTaka } from '../../constants/rentals.js'
import { CoverPhoto } from '../photos/ListingPhotos.jsx'
import TitleBadge from './TitleBadge.jsx'

export default function SaleCard({ listing, center, active = false, onHover }) {
  const { building, sale } = listing
  const facts = [
    `${building.size_sqft.toLocaleString('en-IN')} sq ft`,
    `${building.bedrooms} bed · ${building.bathrooms} bath`,
    sale.parking_slots ? `${sale.parking_slots} parking` : 'No parking',
    HANDOVER[sale.handover_status],
  ]

  return (
    <article
      onMouseEnter={() => onHover?.(listing.id)}
      onMouseLeave={() => onHover?.(null)}
      className={`relative rounded-lg border border-l-4 border-rule border-l-tag-owner bg-sheet p-4 transition-shadow ${
        active ? 'shadow-md ring-1 ring-ink/25' : 'hover:shadow-sm'
      }`}
    >
      <div className="flex gap-4">
        <CoverPhoto listing={listing} className="size-24 shrink-0 rounded-md sm:size-28" />
        <div className="min-w-0 flex-1">
          {/* The price sits beside the title, or under it on a phone so the title isn't squeezed. */}
          <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
                {PROPERTY_TYPES[listing.property_type]} · {areaLabel(listing.location)}
                {listing.sale_status === 'UNDER_OFFER' && <span className="text-tag-owner"> · Under offer</span>}
              </p>
              <h3 className="mt-1 font-semibold leading-snug">
                <Link to={`/sale/${listing.id}`} className="after:absolute after:inset-0 hover:underline">
                  {listing.title}
                </Link>
              </h3>
            </div>
            <p className="shrink-0 sm:text-right">
              <span className="font-mono text-lg font-medium leading-tight sm:block">{formatPrice(sale.asking_price)}</span>
              <span className="text-xs text-ink-soft"> {formatTaka(listing.price_per_sqft)}/sq ft</span>
            </p>
          </div>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {facts.map((fact) => (
              <li key={fact} className="rounded bg-plaster px-1.5 py-0.5 text-xs text-ink-soft">
                {fact}
              </li>
            ))}
          </ul>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            {center && listing.distance_km != null ? (
              <p className="flex items-center gap-1 text-sm text-ink-soft">
                <MapPin className="size-3.5 shrink-0" aria-hidden="true" />
                {listing.distance_km} km from {center.label} · {commuteHint(listing.distance_km)}
              </p>
            ) : (
              <span />
            )}
            <TitleBadge status={listing.title_status} compact />
          </div>
        </div>
      </div>
    </article>
  )
}
