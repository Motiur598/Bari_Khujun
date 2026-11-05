import { ArrowLeft, ArrowUpDown, Bath, BedDouble, Building2, CalendarClock, Car, LoaderCircle, Pencil, Ruler, ShieldCheck, Trash2, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { MapContainer, Marker } from 'react-leaflet'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { deleteSale, getSale } from '../api/marketplace.js'
import ChatWithLister from '../components/ChatWithLister.jsx'
import TrustLink from '../components/TrustLink.jsx'
import VisitScheduler from '../components/VisitScheduler.jsx'
import { BaseTiles, centerPinIcon, toLatLng } from '../components/rentals/RentalMap.jsx'
import EmiCalculator from '../components/sale/EmiCalculator.jsx'
import OfferComposer from '../components/sale/OfferComposer.jsx'
import PriceAnalyzer from '../components/sale/PriceAnalyzer.jsx'
import TitleBadge from '../components/sale/TitleBadge.jsx'
import TitleVault from '../components/sale/TitleVault.jsx'
import { PhotoGallery } from '../components/photos/ListingPhotos.jsx'
import { Alert } from '../components/ui.jsx'
import { HANDOVER, PROPERTY_TYPES, formatPrice } from '../constants/marketplace.js'
import { floorLabel, formatAddress, formatDay, formatTaka } from '../constants/rentals.js'
import { ROLES } from '../constants/roles.js'
import { useAuth } from '../context/AuthContext.jsx'

function Section({ title, children }) {
  return (
    <section className="border-t border-rule pt-6">
      <h2 className="font-display text-2xl font-extrabold uppercase tracking-wide">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Fact({ icon: Icon, label, children }) {
  return (
    <div className="flex items-start gap-3">
      <Icon className="mt-0.5 size-5 shrink-0 text-ink-soft" aria-hidden="true" />
      <div>
        <dt className="text-xs font-medium uppercase tracking-wider text-ink-soft">{label}</dt>
        <dd className="mt-0.5 font-medium">{children}</dd>
      </div>
    </div>
  )
}

export default function SaleDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [listing, setListing] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setListing(null)
    getSale(id)
      .then((data) => !cancelled && setListing(data))
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [id])

  if (error && !listing) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
        <Alert>{error}</Alert>
        <Link to="/sale" className="mt-4 inline-block text-sm font-semibold text-gate hover:underline">
          Back to properties for sale
        </Link>
      </div>
    )
  }
  if (!listing) {
    return (
      <div className="grid flex-1 place-items-center text-ink-soft" role="status">
        <LoaderCircle className="size-6 animate-spin" aria-label="Loading property" />
      </div>
    )
  }

  const { building, sale, lister } = listing
  const isSeller = user?.id === listing.lister_id
  const canDelete = isSeller || user?.role === 'ADMIN'

  async function handleDelete() {
    if (!window.confirm('Delete this property? Open offers will be closed and booked visits cancelled.')) return
    try {
      await deleteSale(listing.id)
      navigate(isSeller ? '/listings' : '/sale', { replace: true })
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-28 pt-6 sm:px-6">
      <button
        type="button"
        onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/sale'))}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-soft hover:text-ink"
      >
        <ArrowLeft className="size-4" aria-hidden="true" /> Back
      </button>

      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-tag-owner px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-white">
            {PROPERTY_TYPES[listing.property_type]} for sale
          </span>
          {listing.sale_status === 'UNDER_OFFER' && (
            <span className="rounded border border-tag-owner px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-tag-owner">
              Under offer
            </span>
          )}
          <TitleBadge status={listing.title_status} compact />
        </div>
        <h1 className="mt-3 font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">{listing.title}</h1>
        <p className="mt-2 text-ink-soft">
          {formatAddress(listing.location)}
        </p>
      </header>

      <div className="mt-6">
        <PhotoGallery listing={listing} />
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-8">
          <Section title="The property">
            <dl className="grid gap-5 sm:grid-cols-3">
              <Fact icon={Ruler} label="Size">
                {building.size_sqft.toLocaleString('en-IN')} sq ft
              </Fact>
              <Fact icon={BedDouble} label="Bedrooms">
                {building.bedrooms}
              </Fact>
              <Fact icon={Bath} label="Bathrooms">
                {building.bathrooms}
              </Fact>
              <Fact icon={Building2} label="Floor">
                {listing.property_type === 'HOUSE' ? `${building.total_floors}-storey house` : `${floorLabel(building.floor_level)} of ${building.total_floors}`}
              </Fact>
              <Fact icon={Car} label="Parking">
                {sale.parking_slots ? `${sale.parking_slots} slot${sale.parking_slots === 1 ? '' : 's'}` : 'None'}
              </Fact>
              <Fact icon={CalendarClock} label="Handover">
                {sale.handover_status === 'UNDER_CONSTRUCTION' ? `Expected ${formatDay(sale.expected_handover)}` : HANDOVER.READY_FLAT}
              </Fact>
              <Fact icon={ArrowUpDown} label="Lift">
                {building.has_elevator ? 'Yes' : 'No'}
              </Fact>
              <Fact icon={Zap} label="Generator backup">
                {building.has_generator_backup ? 'Yes' : 'No'}
              </Fact>
            </dl>
          </Section>

          <Section title="Floor plan">
            {sale.blueprint_url ? (
              <a href={sale.blueprint_url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border border-rule bg-white">
                <img src={sale.blueprint_url} alt={`Floor plan of ${listing.title}`} className="max-h-[28rem] w-full object-contain p-2" loading="lazy" />
              </a>
            ) : (
              <p className="text-sm text-ink-soft">The seller hasn't added a floor plan.</p>
            )}
          </Section>

          <Section title="Price per square foot">
            <PriceAnalyzer listing={listing} />
          </Section>

          <Section title="Home loan estimate">
            <EmiCalculator price={sale.asking_price} />
          </Section>

          {listing.description && (
            <Section title="About this property">
              <p className="whitespace-pre-line leading-relaxed">{listing.description}</p>
            </Section>
          )}

          <Section title="Book a visit">
            <VisitScheduler listing={listing} />
          </Section>

          {isSeller && (
            <Section title="Title documents">
              <TitleVault listingId={listing.id} />
            </Section>
          )}
          {user?.role === 'BUYER' && (
            <Section title="Title documents">
              <TitleVault listingId={listing.id} mode="viewer" />
            </Section>
          )}

          <Section title="Location">
            <div className="h-64 overflow-hidden rounded-lg border border-rule">
              <MapContainer center={toLatLng(listing.location)} zoom={15} scrollWheelZoom={false} className="size-full">
                <BaseTiles />
                <Marker position={toLatLng(listing.location)} icon={centerPinIcon} keyboard={false} />
              </MapContainer>
            </div>
          </Section>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <div className="rounded-xl border border-rule bg-sheet p-5">
            <p className="font-mono text-3xl font-medium">{formatPrice(sale.asking_price)}</p>
            <p className="text-sm text-ink-soft">
              {formatTaka(sale.asking_price)} · {formatTaka(listing.price_per_sqft)}/sq ft
              {sale.price_negotiable ? ' · negotiable' : ' · fixed price'}
            </p>
            <div className="mt-4 border-t border-rule pt-4">
              <OfferComposer listing={listing} />
            </div>
          </div>

          {lister && (
            <div className="rounded-xl border border-rule bg-sheet p-5">
              <p className="text-xs font-medium uppercase tracking-wider text-ink-soft">Sold by</p>
              <p className="mt-1 font-semibold">{lister.full_name}</p>
              <p className="text-sm text-ink-soft">{ROLES[lister.role].title}</p>
              <p className="mt-3 text-sm">
                {lister.kyc_status === 'VERIFIED' ? (
                  <span className="inline-flex items-center gap-1 font-medium text-gate-dark">
                    <ShieldCheck className="size-4" aria-hidden="true" /> Identity verified
                  </span>
                ) : (
                  <span className="text-ink-soft">Identity not verified yet</span>
                )}
              </p>
              <p className="mt-1 text-sm">
                <TitleBadge status={listing.title_status} />
              </p>
              <TrustLink person={lister} />
              <ChatWithLister listing={listing} label="Chat with seller" className="mt-4" />
            </div>
          )}

          {error && <Alert>{error}</Alert>}
          {canDelete && (
            <div className="flex gap-2">
              {isSeller && (
                <Link
                  to={`/sale/${listing.id}/edit`}
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-rule bg-white px-3 py-2 text-sm font-semibold hover:border-ink"
                >
                  <Pencil className="size-4" aria-hidden="true" /> Edit
                </Link>
              )}
              <button
                type="button"
                onClick={handleDelete}
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-tag-owner/40 px-3 py-2 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8"
              >
                <Trash2 className="size-4" aria-hidden="true" /> Delete
              </button>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
