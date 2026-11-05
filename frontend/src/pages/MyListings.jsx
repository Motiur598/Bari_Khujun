import { LoaderCircle, Pencil, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { relistFlat } from '../api/governance.js'
import { deleteSale, getMySales } from '../api/marketplace.js'
import { deleteListing, getMyListings } from '../api/rentals.js'
import TitleBadge from '../components/sale/TitleBadge.jsx'
import { PROPERTY_TYPES, TITLE_STATUS, formatPrice } from '../constants/marketplace.js'
import { Alert } from '../components/ui.jsx'
import { CATEGORIES, areaLabel, formatTaka, rentPrefix, rentUnit } from '../constants/rentals.js'
import { useAuth } from '../context/AuthContext.jsx'
import { CoverPhoto } from '../components/photos/ListingPhotos.jsx'

// A listing row: photo and details, with the buttons on the right. On a phone the buttons drop under the details,
// so the title keeps the full width.
const ROW = 'grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-x-4 gap-y-3 rounded-lg border border-l-4 border-rule bg-sheet p-4 sm:grid-cols-[4rem_minmax(0,1fr)_auto]'
const ACTIONS = 'col-start-2 flex flex-wrap gap-2 sm:col-start-3'

export default function MyListings() {
  const { user } = useAuth()
  const [listings, setListings] = useState(null)
  const [error, setError] = useState('')
  const isSublet = user.role === 'BACHELOR_TENANT'
  const [sales, setSales] = useState(isSublet ? [] : null)

  useEffect(() => {
    getMyListings()
      .then(setListings)
      .catch((err) => {
        setError(getErrorMessage(err))
        setListings([])
      })
  }, [])

  useEffect(() => {
    if (!isSublet) getMySales().then(setSales, () => setSales([]))
  }, [isSublet])

  async function handleDeleteSale(listing) {
    if (!window.confirm(`Delete “${listing.title}”? Open offers will be closed and booked visits cancelled.`)) return
    try {
      await deleteSale(listing.id)
      setSales((current) => current.filter((item) => item.id !== listing.id))
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  async function handleRelist(listing) {
    if (!window.confirm(`Put “${listing.title}” back on the market? Only do this once the tenant has moved out.`)) return
    try {
      const updated = await relistFlat(listing.id)
      setListings((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  async function handleDelete(listing) {
    if (!window.confirm(`Delete “${listing.title}”? Open rent requests and booked visits will be cancelled, and deposits marked for refund.`)) return
    try {
      await deleteListing(listing.id)
      setListings((current) => current.filter((item) => item.id !== listing.id))
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 pb-28 pt-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">My listings</h1>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/listings/new"
            className="inline-flex items-center gap-1.5 rounded-md bg-gate px-3 py-2 text-sm font-semibold text-white hover:bg-gate-dark"
          >
            <Plus className="size-4" aria-hidden="true" /> {isSublet ? 'Sublet seats' : 'Post a rental'}
          </Link>
          {!isSublet && (
            <Link
              to="/sale/new"
              className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-3 py-2 text-sm font-semibold hover:border-ink"
            >
              <Plus className="size-4" aria-hidden="true" /> Sell a property
            </Link>
          )}
        </div>
      </div>
      {!isSublet && <h2 className="mt-8 text-xs font-semibold uppercase tracking-widest text-ink-soft">For rent</h2>}

      <div className="mt-6 space-y-3">
        <Alert>{error}</Alert>
        {listings === null && (
          <div className="grid place-items-center py-12 text-ink-soft" role="status">
            <LoaderCircle className="size-6 animate-spin" aria-label="Loading your listings" />
          </div>
        )}
        {listings?.length === 0 && !error && (
          <div className="rounded-xl border border-dashed border-rule p-8 text-center">
            <p className="font-medium">You haven’t posted anything yet.</p>
            <p className="mt-1 text-sm text-ink-soft">
              {isSublet
                ? 'Have a free bed in your flat? List the seat and let the splitter work out each share.'
                : 'Add your first flat or seat and it will show up in search right away.'}
            </p>
          </div>
        )}
        {listings?.map((listing) => {
          const category = CATEGORIES[listing.category]
          return (
            <article key={listing.id} className={`${ROW} ${category.edge}`}>
              <CoverPhoto listing={listing} className="size-16 shrink-0 rounded-md" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
                  {category.label} · {areaLabel(listing.location)}
                </p>
                <Link to={`/rentals/${listing.id}`} className="mt-1 block font-semibold hover:underline">
                  {listing.title}
                </Link>
                <p className="mt-1 text-sm">
                  <span className="text-ink-soft">{rentPrefix(listing)}</span>
                  <span className="font-mono">{formatTaka(listing.effective_rent)}</span>
                  <span className="text-ink-soft"> {rentUnit(listing)}</span>
                  {listing.seats && (
                    <span className="text-ink-soft">
                      {' '}
                      · {listing.seats.available_seats} of {listing.seats.total_seats} seats free
                      {listing.sublet?.let_type === 'ROOMS' && ` in ${listing.sublet.rooms.length} room${listing.sublet.rooms.length === 1 ? '' : 's'}`}
                    </span>
                  )}
                </p>
              </div>
              <div className={ACTIONS}>
                {listing.rental_status === 'RENTED' && listing.category !== 'BACHELOR_SEAT' && (
                  <button
                    type="button"
                    onClick={() => handleRelist(listing)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-3 py-1.5 text-sm font-semibold hover:border-ink"
                  >
                    Relist
                  </button>
                )}
                <Link
                  to={`/listings/${listing.id}/edit`}
                  className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-3 py-1.5 text-sm font-semibold hover:border-ink"
                >
                  <Pencil className="size-4" aria-hidden="true" /> Edit
                </Link>
                <button
                  type="button"
                  onClick={() => handleDelete(listing)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-tag-owner/40 px-3 py-1.5 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8"
                >
                  <Trash2 className="size-4" aria-hidden="true" /> Delete
                </button>
              </div>
            </article>
          )
        })}
      </div>
      {!isSublet && (
        <section className="mt-10">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-soft">For sale</h2>
          <div className="mt-3 space-y-3">
            {sales?.length === 0 && (
              <div className="rounded-xl border border-dashed border-rule p-6 text-center text-sm text-ink-soft">
                Nothing for sale. Selling a flat or house? Use “Sell a property” above.
              </div>
            )}
            {sales?.map((listing) => (
              <article key={listing.id} className={`${ROW} border-l-tag-owner`}>
                <CoverPhoto listing={listing} className="size-16 shrink-0 rounded-md" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
                    {PROPERTY_TYPES[listing.property_type]} · {areaLabel(listing.location)}
                    {listing.sale_status === 'UNDER_OFFER' && ' · Under offer'}
                  </p>
                  <Link to={`/sale/${listing.id}`} className="mt-1 block font-semibold hover:underline">
                    {listing.title}
                  </Link>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 text-sm">
                    <span className="font-mono">{formatPrice(listing.sale.asking_price)}</span>
                    {listing.title_status === 'VERIFIED' ? (
                      <TitleBadge status="VERIFIED" compact />
                    ) : (
                      <Link to={`/sale/${listing.id}`} className="text-ink-soft underline-offset-2 hover:underline">
                        {TITLE_STATUS[listing.title_status].label}
                      </Link>
                    )}
                  </p>
                </div>
                <div className={ACTIONS}>
                  <Link
                    to={`/sale/${listing.id}/edit`}
                    className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-3 py-1.5 text-sm font-semibold hover:border-ink"
                  >
                    <Pencil className="size-4" aria-hidden="true" /> Edit
                  </Link>
                  <button
                    type="button"
                    onClick={() => handleDeleteSale(listing)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-tag-owner/40 px-3 py-1.5 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8"
                  >
                    <Trash2 className="size-4" aria-hidden="true" /> Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
