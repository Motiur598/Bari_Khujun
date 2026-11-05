import { Check, LoaderCircle, Minus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { compareListings } from '../../api/rentals.js'
import {
  CATEGORIES,
  GUEST_POLICIES,
  METER_TYPES,
  areaLabel,
  floorLabel,
  formatTaka,
  gateLabel,
  tenantCosts,
} from '../../constants/rentals.js'
import { useCompare } from '../../context/CompareContext.jsx'
import { Alert } from '../ui.jsx'

const yesNo = (value) =>
  value ? (
    <span className="inline-flex items-center gap-1 text-gate-dark">
      <Check className="size-4" aria-hidden="true" /> Yes
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-ink-soft">
      <Minus className="size-4" aria-hidden="true" /> No
    </span>
  )

// `lowest` rows highlight the cheapest column(s) when the values differ.
const SECTIONS = [
  {
    title: 'Monthly cost for one tenant',
    rows: [
      { label: 'Rent', amount: (l) => tenantCosts(l).rent, lowest: true },
      {
        label: 'Base rent (whole flat)',
        amount: (l) => l.pricing.base_rent,
        // A sublet prices its seat or rooms, not the flat.
        format: (l) => (l.sublet ? 'Sublet by seat or room' : formatTaka(l.pricing.base_rent)),
      },
      { label: 'Service charge', amount: (l) => tenantCosts(l).service, lowest: true },
      { label: 'Utilities (estimate)', amount: (l) => tenantCosts(l).utility, lowest: true },
      { label: 'Maid (estimate)', amount: (l) => tenantCosts(l).maid, lowest: true },
      { label: 'Total (estimate)', amount: (l) => tenantCosts(l).total, lowest: true, strong: true },
      {
        label: 'Deposit',
        amount: (l) => tenantCosts(l).deposit,
        format: (l) =>
          `${l.pricing.deposit_months} month${l.pricing.deposit_months === 1 ? '' : 's'} · ${formatTaka(tenantCosts(l).deposit)}`,
        lowest: true,
      },
    ],
  },
  {
    title: 'House rules',
    rows: [
      { label: 'Meter', render: (l) => METER_TYPES[l.house_rules.meter_type] },
      { label: 'Gate', render: (l) => gateLabel(l.house_rules.gate_closing_time) },
      { label: 'Guests', render: (l) => GUEST_POLICIES[l.house_rules.guest_policy] },
      { label: 'Smoking allowed', render: (l) => yesNo(l.house_rules.smoking_allowed) },
    ],
  },
  {
    title: 'Building',
    rows: [
      { label: 'Floor', render: (l) => `${floorLabel(l.building.floor_level)} of ${l.building.total_floors}` },
      { label: 'Lift', render: (l) => yesNo(l.building.has_elevator) },
      { label: 'Generator backup', render: (l) => yesNo(l.building.has_generator_backup) },
      { label: 'Bedrooms / baths', render: (l) => `${l.building.bedrooms} / ${l.building.bathrooms}` },
      { label: 'Size', render: (l) => (l.building.size_sqft ? `${l.building.size_sqft} sq ft` : 'Not given') },
    ],
  },
  {
    title: 'Seats',
    rows: [
      {
        label: 'Free seats',
        render: (l) => (l.seats ? `${l.seats.available_seats} of ${l.seats.total_seats}` : 'Whole flat'),
      },
      { label: 'Current flatmates', render: (l) => (l.seats ? l.seats.flatmates.length || 'None listed' : '—') },
    ],
  },
]

function amountCell(row, listing, lowestValue) {
  const value = row.amount(listing)
  const isLowest = row.lowest && lowestValue !== null && value === lowestValue
  return (
    <span className={`font-mono ${isLowest ? 'font-semibold text-gate-dark' : ''} ${row.strong ? 'text-base' : ''}`}>
      {row.format ? row.format(listing) : formatTaka(value)}
      {isLowest && <span className="ml-1.5 font-sans text-[10px] font-semibold uppercase tracking-wider">Lowest</span>}
    </span>
  )
}

function lowestOf(row, listings) {
  if (!row.lowest || listings.length < 2) return null
  const values = listings.map(row.amount)
  const min = Math.min(...values)
  return values.every((value) => value === min) ? null : min
}

export default function CompareModal() {
  const { items, isOpen, close, remove } = useCompare()
  const dialogRef = useRef(null)
  const [listings, setListings] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const idKey = items.map((item) => item.id).join(',')
  // Hide removed columns immediately instead of waiting for the refetch.
  const shown = listings.filter((listing) => items.some((item) => item.id === listing.id))

  useEffect(() => {
    const dialog = dialogRef.current
    if (isOpen && !dialog.open) dialog.showModal()
    if (!isOpen && dialog.open) dialog.close()
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    if (!idKey) {
      close()
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    compareListings(idKey.split(','))
      .then((data) => {
        if (cancelled) return
        setListings(data)
        // Drop listings that were deleted since they were picked.
        const found = new Set(data.map((listing) => listing.id))
        idKey.split(',').forEach((id) => found.has(id) || remove(id))
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [isOpen, idKey, close, remove])

  return (
    <dialog
      ref={dialogRef}
      onClose={close}
      onClick={(event) => event.target === dialogRef.current && close()}
      aria-labelledby="compare-heading"
      className="m-auto max-h-[92dvh] w-[calc(100%-2rem)] max-w-5xl overflow-hidden rounded-xl bg-sheet p-0 text-ink shadow-2xl"
    >
      <div className="flex max-h-[92dvh] flex-col">
        <div className="flex items-center justify-between gap-4 border-b border-rule px-5 py-4">
          <h2 id="compare-heading" className="font-display text-2xl font-extrabold uppercase tracking-wide">
            Compare side by side
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close comparison"
            className="rounded-md p-1.5 text-ink-soft hover:bg-plaster hover:text-ink"
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {error && (
            <div className="p-5">
              <Alert>{error}</Alert>
            </div>
          )}
          {loading && shown.length === 0 && (
            <div className="grid place-items-center p-12 text-ink-soft" role="status">
              <LoaderCircle className="size-6 animate-spin" aria-label="Loading comparison" />
            </div>
          )}
          {shown.length > 0 && (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="align-top">
                  <th scope="col" className="sticky left-0 z-10 w-28 bg-sheet p-3 text-left sm:w-44 sm:p-4">
                    <span className="sr-only">Detail</span>
                  </th>
                  {shown.map((listing) => {
                    const category = CATEGORIES[listing.category]
                    return (
                      <th key={listing.id} scope="col" className="min-w-40 p-3 text-left font-normal sm:p-4">
                        <div className="flex items-start justify-between gap-2">
                          <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${category.badge}`}>
                            {category.label}
                          </span>
                          <button
                            type="button"
                            onClick={() => remove(listing.id)}
                            aria-label={`Remove ${listing.title} from comparison`}
                            className="rounded p-0.5 text-ink-soft hover:bg-plaster hover:text-ink"
                          >
                            <X className="size-4" aria-hidden="true" />
                          </button>
                        </div>
                        <Link
                          to={`/rentals/${listing.id}`}
                          onClick={close}
                          className="mt-2 block font-semibold leading-snug hover:underline"
                        >
                          {listing.title}
                        </Link>
                        <p className="mt-0.5 text-xs text-ink-soft">{areaLabel(listing.location)}</p>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              {SECTIONS.map((section) => (
                <tbody key={section.title}>
                  <tr>
                    <th
                      scope="colgroup"
                      colSpan={shown.length + 1}
                      className="sticky left-0 bg-plaster px-4 py-2 text-left text-xs font-semibold uppercase tracking-widest text-ink-soft"
                    >
                      {section.title}
                    </th>
                  </tr>
                  {section.rows.map((row) => {
                    const lowest = row.amount ? lowestOf(row, shown) : null
                    return (
                      <tr key={row.label} className="border-b border-rule last:border-b-0">
                        <th scope="row" className="sticky left-0 z-10 bg-sheet px-3 py-2.5 text-left font-medium sm:px-4">
                          {row.label}
                        </th>
                        {shown.map((listing) => (
                          <td key={listing.id} className="px-3 py-2.5 sm:px-4">
                            {row.amount ? amountCell(row, listing, lowest) : row.render(listing)}
                          </td>
                        ))}
                      </tr>
                    )
                  })}
                </tbody>
              ))}
            </table>
          )}
        </div>
      </div>
    </dialog>
  )
}
