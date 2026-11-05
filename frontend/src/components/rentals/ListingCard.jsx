import { MapPin } from 'lucide-react'
import { Link } from 'react-router-dom'
import { CATEGORIES, areaLabel, clockLabel, commuteHint, floorLabel, formatTaka, rentPrefix, rentUnit } from '../../constants/rentals.js'
import { CoverPhoto } from '../photos/ListingPhotos.jsx'
import CompareToggle from './CompareToggle.jsx'

function features(listing) {
  const { building, house_rules: rules } = listing
  return [
    floorLabel(building.floor_level),
    building.has_elevator && 'Lift',
    building.has_generator_backup && 'Generator',
    rules.meter_type === 'PREPAID' ? 'Prepaid meter' : 'Postpaid meter',
    rules.gate_closing_time ? `Gate ${clockLabel(rules.gate_closing_time)}` : 'No gate curfew',
    rules.smoking_allowed ? 'Smoking OK' : 'No smoking',
  ].filter(Boolean)
}

export default function ListingCard({ listing, center, active = false, onHover }) {
  const category = CATEGORIES[listing.category]
  const { seats } = listing

  return (
    <article
      onMouseEnter={() => onHover?.(listing.id)}
      onMouseLeave={() => onHover?.(null)}
      className={`relative rounded-lg border border-l-4 border-rule ${category.edge} bg-sheet p-4 transition-shadow ${
        active ? 'shadow-md ring-1 ring-ink/25' : 'hover:shadow-sm'
      }`}
    >
      <div className="flex gap-4">
        <CoverPhoto listing={listing} className="size-24 shrink-0 rounded-md sm:size-28" />
        <div className="min-w-0 flex-1">
          {/* The rent sits beside the title, or under it on a phone so the title isn't squeezed. */}
          <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
                {category.label}
                {listing.is_sublet && ' · Sublet'} · {areaLabel(listing.location)}
              </p>
              <h3 className="mt-1 font-semibold leading-snug">
                {/* Stretched link: the whole card opens the listing; the compare button sits above it. */}
                <Link to={`/rentals/${listing.id}`} className="after:absolute after:inset-0 hover:underline">
                  {listing.title}
                </Link>
              </h3>
            </div>
            <p className="shrink-0 sm:text-right">
              {rentPrefix(listing) && <span className="text-xs text-ink-soft sm:block">{rentPrefix(listing)}</span>}
              <span className="font-mono text-lg font-medium leading-tight sm:block">{formatTaka(listing.effective_rent)}</span>
              <span className="text-xs text-ink-soft"> {rentUnit(listing)}</span>
            </p>
          </div>

          <ul className="mt-3 flex flex-wrap gap-1.5">
            {features(listing).map((feature) => (
              <li key={feature} className="rounded bg-plaster px-1.5 py-0.5 text-xs text-ink-soft">
                {feature}
              </li>
            ))}
          </ul>

          <div className="mt-3 flex flex-wrap items-end justify-between gap-2">
            <div className="space-y-0.5 text-sm">
              {seats && (
                <p>
                  <span className="font-semibold">{seats.available_seats}</span> of {seats.total_seats} seats free
                  {listing.sublet?.let_type === 'ROOMS' && (
                    <span className="text-ink-soft">
                      {' '}
                      · {listing.sublet.rooms.length} room{listing.sublet.rooms.length === 1 ? '' : 's'}
                    </span>
                  )}
                </p>
              )}
              {center && listing.distance_km != null && (
                <p className="flex items-center gap-1 text-ink-soft">
                  <MapPin className="size-3.5 shrink-0" aria-hidden="true" />
                  {listing.distance_km} km from {center.label} · {commuteHint(listing.distance_km)}
                </p>
              )}
            </div>
            <CompareToggle listing={listing} className="relative z-10" />
          </div>
        </div>
      </div>
    </article>
  )
}
