import {
  ArrowLeft,
  ArrowUpDown,
  Bath,
  BedDouble,
  Building2,
  Cigarette,
  CigaretteOff,
  DoorClosed,
  Gauge,
  LoaderCircle,
  Pencil,
  Ruler,
  ShieldCheck,
  Trash2,
  Users,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { MapContainer, Marker } from 'react-leaflet'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { deleteListing, getListing } from '../api/rentals.js'
import ChatWithLister from '../components/ChatWithLister.jsx'
import TrustLink from '../components/TrustLink.jsx'
import VisitScheduler from '../components/VisitScheduler.jsx'
import RequestToRent from '../components/handshake/RequestToRent.jsx'
import CompareToggle from '../components/rentals/CompareToggle.jsx'
import { BaseTiles, centerPinIcon, toLatLng } from '../components/rentals/RentalMap.jsx'
import SeatSplit, { SeatPlan } from '../components/rentals/SeatSplit.jsx'
import { PhotoGallery, RoomPhotoStrip } from '../components/photos/ListingPhotos.jsx'
import { Alert } from '../components/ui.jsx'
import {
  CATEGORIES,
  GUEST_POLICIES,
  HABITS,
  METER_TYPES,
  OCCUPATIONS,
  defaultUnit,
  floorLabel,
  formatAddress,
  formatDay,
  formatTaka,
  gateLabel,
  rentUnit,
  tenantCosts,
  unitChoices,
  unitKey,
  unitLabel,
} from '../constants/rentals.js'
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

// A sublet seat's or room's optional charges, per seat ("None" when there are none).
function Charges({ room, label }) {
  const charges = [
    ['Service', room.service_charge],
    ['Utilities', room.utility_estimate],
    ['Maid', room.maid_estimate],
  ].filter(([, amount]) => amount > 0)
  return (
    <div className="flex flex-wrap gap-x-2 text-sm">
      <dt className="text-ink-soft">{label}:</dt>
      <dd>{charges.length ? charges.map(([name, amount]) => `${name} ${formatTaka(amount)}`).join(' · ') : 'None'}</dd>
    </div>
  )
}

// One room of a sublet: its type, price, charges and photos, with buttons to ask for a seat or the room.
function RoomCard({ listing, room, chosen, onChoose }) {
  const single = room.room_type === 'SINGLE'
  const choices = listing.rental_status === 'RENTED' ? [] : unitChoices(listing).filter((unit) => unit.room_id === room.id)

  return (
    <li className="rounded-xl border border-rule bg-sheet p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <div>
          <h3 className="text-lg font-semibold">{room.name}</h3>
          <p className="text-sm text-ink-soft">{single ? 'Single room' : `Shared room · ${room.seats} seats`}</p>
        </div>
        <p className="text-right">
          <span className="font-mono text-xl font-medium">{formatTaka(room.seat_rent)}</span>
          <span className="text-xs text-ink-soft"> {single ? '/month' : '/seat/month'}</span>
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <SeatPlan total={room.seats} available={room.available_seats} />
        <p className="text-sm">
          {room.available_seats === 0 ? (
            'Taken'
          ) : single ? (
            'Free'
          ) : (
            <>
              <span className="font-semibold">{room.available_seats}</span> of {room.seats} seats free
            </>
          )}
        </p>
      </div>

      <dl className="mt-3 space-y-1">
        <Charges room={room} label={single ? 'Charges' : 'Charges per seat'} />
        {!single && (
          <div className="flex flex-wrap gap-x-2 text-sm">
            <dt className="text-ink-soft">Whole room:</dt>
            <dd>
              <span className="font-mono">{formatTaka(room.seat_rent * room.seats)}</span>/month
              {room.available_seats < room.seats && <span className="text-ink-soft"> (only while every seat is free)</span>}
            </dd>
          </div>
        )}
      </dl>

      <div className="mt-4">
        <RoomPhotoStrip listing={listing} room={room} />
      </div>

      {choices.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {choices.map((unit) => {
            const on = unitKey(unit) === unitKey(chosen)
            return (
              <button
                key={unitKey(unit)}
                type="button"
                aria-pressed={on}
                onClick={() => onChoose(unit)}
                className={`rounded-md border px-3 py-1.5 text-sm font-semibold transition-colors ${
                  on ? 'border-tag-seat bg-tag-seat text-white' : 'border-rule bg-white hover:border-ink'
                }`}
              >
                {single ? 'Choose this room' : unit.whole_room ? 'Choose the whole room' : 'Choose a seat'}
              </button>
            )
          })}
        </div>
      )}
    </li>
  )
}

export default function RentalDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [listing, setListing] = useState(null)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)
  // The seat or room picked on a sublet (null: its cheapest free one).
  const [unit, setUnit] = useState(null)

  useEffect(() => {
    let cancelled = false
    setListing(null)
    setError('')
    setUnit(null)
    getListing(id)
      .then((data) => !cancelled && setListing(data))
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [id])

  if (error) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
        <Alert>{error}</Alert>
        <Link to="/rentals" className="mt-4 inline-block text-sm font-semibold text-gate hover:underline">
          Back to search
        </Link>
      </div>
    )
  }
  if (!listing) {
    return (
      <div className="grid flex-1 place-items-center text-ink-soft" role="status">
        <LoaderCircle className="size-6 animate-spin" aria-label="Loading listing" />
      </div>
    )
  }

  const category = CATEGORIES[listing.category]
  const { pricing, building, house_rules: rules, seats, sublet, lister } = listing
  const chosen = sublet ? ((unit && unitChoices(listing).find((choice) => unitKey(choice) === unitKey(unit))) ?? defaultUnit(listing)) : null
  const costs = tenantCosts(listing, chosen)
  // A sublet's charges are optional, so a missing one reads "None".
  const charge = (amount) => (sublet && !amount ? 'None' : formatTaka(amount))
  const seatRoom = sublet?.let_type === 'SEAT' ? sublet.rooms[0] : null
  const isLister = user?.id === listing.lister_id
  const canDelete = isLister || user?.role === 'ADMIN'

  const chooseUnit = (next) => {
    setUnit(next)
    document.getElementById('request-to-rent')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  async function handleDelete() {
    if (!window.confirm('Delete this listing? Open rent requests and booked visits will be cancelled, and deposits marked for refund.')) return
    setDeleting(true)
    try {
      await deleteListing(listing.id)
      navigate(user.role === 'ADMIN' ? '/rentals' : '/listings', { replace: true })
    } catch (err) {
      setError(getErrorMessage(err))
      setDeleting(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-28 pt-6 sm:px-6">
      <button
        type="button"
        onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/rentals'))}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-soft hover:text-ink"
      >
        <ArrowLeft className="size-4" aria-hidden="true" /> Back
      </button>

      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${category.badge}`}>
            {category.label}
          </span>
          {listing.is_sublet && (
            <span className="rounded border border-ink-soft px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-ink-soft">
              Sublet by tenant
            </span>
          )}
          {listing.rental_status === 'RENTED' && (
            <span className="rounded bg-ink px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-white">Rented</span>
          )}
          {listing.reopens_on && (
            <span className="rounded border border-gate px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-gate">
              {listing.category === 'BACHELOR_SEAT' ? 'A seat frees up' : 'Reopens'} {formatDay(listing.reopens_on)}
            </span>
          )}
        </div>
        <h1 className="mt-3 font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">
          {listing.title}
        </h1>
        <p className="mt-2 text-ink-soft">
          {formatAddress(listing.location)} · Available from{' '}
          {formatDay(listing.available_from)}
        </p>
      </header>

      <div className="mt-6">
        <PhotoGallery listing={listing} />
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-8">
          {seats?.split && (
            <Section title="Seat splitter">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <SeatPlan total={seats.total_seats} available={seats.available_seats} />
                <p className="text-sm">
                  <span className="font-semibold">{seats.available_seats}</span> of {seats.total_seats} seats free
                </p>
              </div>
              <div className="mt-5 max-w-lg">
                <SeatSplit pricing={pricing} totalSeats={seats.total_seats} split={seats.split} />
              </div>
            </Section>
          )}

          {seatRoom && (
            <Section title="The seat">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <SeatPlan total={seatRoom.room_size} available={seatRoom.available_seats} />
                <p className="text-sm">
                  One seat in a shared room of {seatRoom.room_size} · {seatRoom.available_seats ? 'free' : 'taken'}
                </p>
              </div>
              <dl className="mt-4 space-y-1">
                <div className="flex flex-wrap gap-x-2 text-sm">
                  <dt className="text-ink-soft">Rent:</dt>
                  <dd>
                    <span className="font-mono">{formatTaka(seatRoom.seat_rent)}</span>/month
                  </dd>
                </div>
                <Charges room={seatRoom} label="Charges" />
              </dl>
            </Section>
          )}

          {sublet?.let_type === 'ROOMS' && (
            <Section title="Rooms">
              <p className="text-sm text-ink-soft">
                <span className="font-semibold text-ink">{seats.available_seats}</span> of {seats.total_seats} seat
                {seats.total_seats === 1 ? '' : 's'} free in {sublet.rooms.length} room{sublet.rooms.length === 1 ? '' : 's'}. A shared
                room can be taken a seat at a time, or whole while every seat in it is free.
              </p>
              <ul className="mt-4 space-y-4">
                {sublet.rooms.map((room) => (
                  <RoomCard key={room.id} listing={listing} room={room} chosen={chosen} onChoose={chooseUnit} />
                ))}
              </ul>
            </Section>
          )}

          <Section title="House rules">
            <dl className="grid gap-5 sm:grid-cols-2">
              <Fact icon={DoorClosed} label="Gate">
                {gateLabel(rules.gate_closing_time)}
              </Fact>
              <Fact icon={Users} label="Guests">
                {GUEST_POLICIES[rules.guest_policy]}
              </Fact>
              <Fact icon={rules.smoking_allowed ? Cigarette : CigaretteOff} label="Smoking">
                {rules.smoking_allowed ? 'Allowed' : 'Not allowed'}
              </Fact>
              <Fact icon={Gauge} label="Electricity">
                {METER_TYPES[rules.meter_type]}
              </Fact>
            </dl>
          </Section>

          <Section title="Building">
            <dl className="grid gap-5 sm:grid-cols-3">
              <Fact icon={Building2} label="Floor">
                {floorLabel(building.floor_level)} of {building.total_floors}
              </Fact>
              <Fact icon={ArrowUpDown} label="Lift">
                {building.has_elevator ? 'Yes' : 'No'}
              </Fact>
              <Fact icon={Zap} label="Generator backup">
                {building.has_generator_backup ? 'Yes' : 'No'}
              </Fact>
              <Fact icon={BedDouble} label="Bedrooms">
                {building.bedrooms}
              </Fact>
              <Fact icon={Bath} label="Bathrooms">
                {building.bathrooms}
              </Fact>
              <Fact icon={Ruler} label="Size">
                {building.size_sqft ? `${building.size_sqft} sq ft` : 'Not given'}
              </Fact>
            </dl>
          </Section>

          {seats && (
            <Section title="Current flatmates">
              {seats.flatmates.length === 0 ? (
                <p className="text-sm text-ink-soft">The lister hasn't added flatmate profiles yet.</p>
              ) : (
                <ul className="grid gap-3 sm:grid-cols-2">
                  {seats.flatmates.map((mate, index) => (
                    <li key={index} className="rounded-lg border border-rule bg-sheet p-4">
                      <p className="font-semibold">{mate.display_name}</p>
                      <p className="text-sm text-ink-soft">
                        {OCCUPATIONS[mate.occupation_type]} · {mate.institution}
                      </p>
                      {mate.habits.length > 0 && (
                        <ul className="mt-2 flex flex-wrap gap-1.5">
                          {mate.habits.map((habit) => (
                            <li key={habit} className="rounded bg-plaster px-1.5 py-0.5 text-xs">
                              {HABITS[habit]}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          )}

          {listing.description && (
            <Section title="About this place">
              <p className="whitespace-pre-line leading-relaxed">{listing.description}</p>
            </Section>
          )}

          {listing.rental_status !== 'RENTED' && (
            <Section title="Book a visit">
              <VisitScheduler listing={listing} />
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
            <p className="font-mono text-3xl font-medium">{formatTaka(sublet ? costs.rent : listing.effective_rent)}</p>
            <p className="text-sm text-ink-soft">{sublet ? `rent a month · ${unitLabel(chosen)}` : `rent ${rentUnit(listing)}`}</p>
            <dl className="mt-4 space-y-2 border-t border-rule pt-4 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-ink-soft">Service charge</dt>
                <dd className="font-mono">{charge(costs.service)}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-ink-soft">Utilities and maid (est.)</dt>
                <dd className="font-mono">{charge(costs.utility + costs.maid)}</dd>
              </div>
              <div className="flex justify-between gap-4 font-semibold">
                <dt>Monthly total (est.)</dt>
                <dd className="font-mono">{formatTaka(costs.total)}</dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-rule pt-2">
                <dt className="text-ink-soft">
                  Deposit ({pricing.deposit_months} month{pricing.deposit_months === 1 ? '' : 's'})
                </dt>
                <dd className="font-mono">{formatTaka(costs.deposit)}</dd>
              </div>
            </dl>
            <CompareToggle listing={listing} className="mt-4 w-full justify-center py-2 text-sm" />
          </div>

          <div id="request-to-rent" className="rounded-xl border border-rule bg-sheet p-5">
            <h2 className="mb-3 font-semibold">Request to rent</h2>
            <RequestToRent listing={listing} unit={chosen} onUnitChange={setUnit} />
          </div>

          {lister && (
            <div className="rounded-xl border border-rule bg-sheet p-5">
              <p className="text-xs font-medium uppercase tracking-wider text-ink-soft">Listed by</p>
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
              <TrustLink person={lister} />
              <ChatWithLister listing={listing} label={listing.is_sublet ? 'Chat with lister' : 'Chat with owner'} className="mt-4" />
            </div>
          )}

          {canDelete && (
            <div className="flex gap-2">
              {isLister && (
                <Link
                  to={`/listings/${listing.id}/edit`}
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-rule bg-white px-3 py-2 text-sm font-semibold hover:border-ink"
                >
                  <Pencil className="size-4" aria-hidden="true" /> Edit listing
                </Link>
              )}
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-tag-owner/40 px-3 py-2 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8 disabled:opacity-60"
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
