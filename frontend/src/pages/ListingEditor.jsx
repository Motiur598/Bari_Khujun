import { LoaderCircle, Plus, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { uploadPending } from '../api/photos.js'
import { createListing, getListing, updateListing } from '../api/rentals.js'
import LocationPickerMap, { EMPTY_LOCATION, locationFromListing, locationToPayload } from '../components/LocationPickerMap.jsx'
import { PhotoManager, RoomPhotoManager } from '../components/photos/ListingPhotos.jsx'
import SeatSplit from '../components/rentals/SeatSplit.jsx'
import { Alert, Button, Checkbox, FormSection, Segmented, TextField } from '../components/ui.jsx'
import { CATEGORIES, GUEST_POLICIES, HABITS, OCCUPATIONS, formatTaka, seatSplit } from '../constants/rentals.js'
import { useAuth } from '../context/AuthContext.jsx'

const CATEGORY_HELP = {
  FAMILY_FLAT: 'A whole flat for a household.',
  BACHELOR_FLAT: 'A whole flat for students or single professionals.',
  BACHELOR_SEAT: 'Individual seats in a shared flat. Costs are split per seat.',
}
const SUBLET_HELP = 'A seat or rooms in the flat you rent.'

const MAX_HABITS = 6
const MAX_FLATMATES = 20
const MAX_ROOMS = 12
const MAX_ROOM_SEATS = 6
const localToday = () => new Date().toLocaleDateString('en-CA')

// A sublet's optional monthly charges, per seat (for a single room, for the room).
const SUBLET_CHARGES = [
  ['service_charge', 'Service charge (৳)'],
  ['utility_estimate', 'Utilities estimate (৳)'],
  ['maid_estimate', 'Maid estimate (৳)'],
]
const NO_CHARGES = { service_charge: '', utility_estimate: '', maid_estimate: '' }

let roomKeys = 0
// `key` tells rooms apart in the form (and the photos waiting to upload for them); `id` is set once a room is saved.
// `seats` only counts for a shared room.
const newRoom = (number) => ({
  key: `new-${++roomKeys}`,
  id: null,
  name: `Room ${number}`,
  room_type: 'SINGLE',
  seats: '2',
  seat_rent: '',
  ...NO_CHARGES,
})

// What a bachelor tenant sublets: one seat in a shared room, or rooms.
const EMPTY_SUBLET = {
  let_type: 'SEAT',
  seat: { room_size: '2', seat_rent: '', ...NO_CHARGES },
  rooms: [newRoom(1)],
  flatmates: [],
}

const EMPTY_FORM = {
  category: '',
  title: '',
  description: '',
  available_from: localToday(),
  location: EMPTY_LOCATION,
  pricing: { base_rent: '', service_charge: '0', deposit_months: '2', utility_estimate: '0', maid_estimate: '0' },
  building: {
    floor_level: '',
    total_floors: '',
    bedrooms: '',
    bathrooms: '',
    size_sqft: '',
    has_elevator: false,
    has_generator_backup: false,
  },
  house_rules: {
    gate_open_all_night: false,
    gate_closing_time: '23:00',
    guest_policy: 'DAYTIME_ONLY',
    smoking_allowed: false,
    meter_type: 'PREPAID',
  },
  seats: { total_seats: '4', available_seats: '1', flatmates: [] },
  sublet: EMPTY_SUBLET,
}

const EMPTY_FLATMATE = { display_name: '', occupation_type: 'STUDENT', institution: '', habits: [] }

const stringify = (record) => Object.fromEntries(Object.entries(record).map(([key, value]) => [key, String(value ?? '')]))
// Optional charges show as blank rather than 0.
const chargesOf = (room) => Object.fromEntries(SUBLET_CHARGES.map(([key]) => [key, room[key] ? String(room[key]) : '']))

function subletFromListing({ sublet, seats }) {
  const seat = sublet.rooms.find((room) => room.room_type === 'SEAT')
  return {
    let_type: sublet.let_type,
    seat: seat ? { room_size: String(seat.room_size), seat_rent: String(seat.seat_rent), ...chargesOf(seat) } : EMPTY_SUBLET.seat,
    rooms:
      sublet.let_type === 'ROOMS'
        ? sublet.rooms.map((room) => ({
            key: room.id,
            id: room.id,
            name: room.name,
            room_type: room.room_type,
            seats: String(room.room_type === 'SHARED' ? room.seats : 2),
            seat_rent: String(room.seat_rent),
            ...chargesOf(room),
          }))
        : [newRoom(1)],
    flatmates: seats.flatmates,
  }
}

function fromListing(listing) {
  const { building, house_rules: rules, seats } = listing
  return {
    category: listing.category,
    title: listing.title,
    description: listing.description,
    available_from: listing.available_from,
    location: locationFromListing(listing.location),
    pricing: stringify(listing.pricing),
    building: {
      ...stringify(building),
      has_elevator: building.has_elevator,
      has_generator_backup: building.has_generator_backup,
    },
    house_rules: {
      ...rules,
      gate_open_all_night: rules.gate_closing_time === null,
      gate_closing_time: rules.gate_closing_time ?? '23:00',
    },
    seats: seats
      ? { total_seats: String(seats.total_seats), available_seats: String(seats.available_seats), flatmates: seats.flatmates }
      : EMPTY_FORM.seats,
    sublet: listing.sublet ? subletFromListing(listing) : EMPTY_SUBLET,
  }
}

function subletToPayload({ let_type, seat, rooms, flatmates }) {
  const amount = (value) => Number(value || 0)
  const charges = (room) => Object.fromEntries(SUBLET_CHARGES.map(([key]) => [key, amount(room[key])]))
  return {
    let_type,
    seat: let_type === 'SEAT' ? { room_size: Number(seat.room_size), seat_rent: Number(seat.seat_rent), ...charges(seat) } : null,
    rooms:
      let_type === 'ROOMS'
        ? rooms.map((room) => ({
            id: room.id,
            name: room.name.trim(),
            room_type: room.room_type,
            seats: room.room_type === 'SHARED' ? Number(room.seats) : 1,
            seat_rent: Number(room.seat_rent),
            ...charges(room),
          }))
        : [],
    flatmates: flatmates.map((mate) => ({ ...mate, display_name: mate.display_name.trim(), institution: mate.institution.trim() })),
  }
}

function toPayload(form, isSublet) {
  const { building, house_rules: rules, seats } = form
  return {
    category: form.category,
    title: form.title.trim(),
    description: form.description.trim(),
    available_from: form.available_from,
    location: locationToPayload(form.location),
    // A sublet prices its seat or rooms itself; only the deposit is listing-wide.
    pricing: isSublet
      ? { deposit_months: Number(form.pricing.deposit_months) }
      : Object.fromEntries(Object.entries(form.pricing).map(([key, value]) => [key, Number(value || 0)])),
    building: {
      floor_level: Number(building.floor_level),
      total_floors: Number(building.total_floors),
      bedrooms: Number(building.bedrooms),
      bathrooms: Number(building.bathrooms),
      size_sqft: building.size_sqft ? Number(building.size_sqft) : null,
      has_elevator: building.has_elevator,
      has_generator_backup: building.has_generator_backup,
    },
    house_rules: {
      gate_closing_time: rules.gate_open_all_night ? null : rules.gate_closing_time,
      guest_policy: rules.guest_policy,
      smoking_allowed: rules.smoking_allowed,
      meter_type: rules.meter_type,
    },
    seats:
      form.category === 'BACHELOR_SEAT' && !isSublet
        ? {
            total_seats: Number(seats.total_seats),
            available_seats: Number(seats.available_seats),
            flatmates: seats.flatmates.map((mate) => ({
              ...mate,
              display_name: mate.display_name.trim(),
              institution: mate.institution.trim(),
            })),
          }
        : null,
    sublet: isSublet ? subletToPayload(form.sublet) : null,
  }
}

function OptionalLabel({ children }) {
  return (
    <>
      {children} <span className="font-normal text-ink-soft">(optional)</span>
    </>
  )
}

// The optional per-seat charges of a sublet's seat or room.
function ChargeFields({ values, onChange }) {
  return SUBLET_CHARGES.map(([key, label]) => (
    <TextField
      key={key}
      label={<OptionalLabel>{label}</OptionalLabel>}
      hint={key === 'utility_estimate' ? 'Gas, electricity, water and internet.' : undefined}
      type="number"
      min={0}
      placeholder="None"
      value={values[key]}
      onChange={(event) => onChange(key, event.target.value)}
    />
  ))
}

// One room of a sublet, in its own section: its type, rent, optional charges and photos.
function SubletRoomSection({ room, index, savedListing, onChange, pendingPhotos, onPendingPhotosChange, onListingChange }) {
  const set = (field) => (value) => onChange({ ...room, [field]: value })
  const shared = room.room_type === 'SHARED'
  const seats = Number(room.seats) || 0
  const perSeat = (Number(room.seat_rent) || 0) + SUBLET_CHARGES.reduce((sum, [key]) => sum + (Number(room[key]) || 0), 0)
  const savedRoom = savedListing?.sublet?.rooms.find((item) => item.id === room.id) ?? null

  return (
    <FormSection title={`Room ${index + 1}`} description="This room's rent and charges each month, in taka. Leave a charge blank if there isn't one.">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Room name" required maxLength={40} value={room.name} onChange={(event) => set('name')(event.target.value)} />
        <Segmented
          legend="Let as"
          name={`room-type-${room.key}`}
          value={room.room_type}
          options={[
            ['SINGLE', 'Single room'],
            ['SHARED', 'Shared room'],
          ]}
          onChange={set('room_type')}
        />
        {shared && (
          <TextField
            label="Seats in the room"
            hint="Tenants take one seat, or the whole room while every seat is free."
            type="number"
            required
            min={2}
            max={MAX_ROOM_SEATS}
            value={room.seats}
            onChange={(event) => set('seats')(event.target.value)}
          />
        )}
        <TextField
          label={shared ? 'Rent per seat (৳)' : 'Rent for the room (৳)'}
          type="number"
          required
          min={1}
          value={room.seat_rent}
          onChange={(event) => set('seat_rent')(event.target.value)}
        />
        <ChargeFields values={room} onChange={(key, value) => set(key)(value)} />
      </div>
      {perSeat > 0 && (
        <p className="rounded-md bg-plaster px-3 py-2 text-sm">
          {shared ? (
            <>
              A seat costs <span className="font-mono font-semibold">{formatTaka(perSeat)}</span> a month in all
              {seats >= 2 && (
                <>
                  ; the whole room <span className="font-mono font-semibold">{formatTaka(perSeat * seats)}</span>
                </>
              )}
              .
            </>
          ) : (
            <>
              The room costs <span className="font-mono font-semibold">{formatTaka(perSeat)}</span> a month in all.
            </>
          )}
        </p>
      )}
      <div>
        <p className="mb-2 text-sm font-medium">
          Photos of this room <span className="font-normal text-ink-soft">(up to 4)</span>
        </p>
        <RoomPhotoManager
          listing={savedListing}
          room={savedRoom}
          onListingChange={onListingChange}
          pending={pendingPhotos}
          onPendingChange={onPendingPhotosChange}
        />
      </div>
    </FormSection>
  )
}

function FlatmateEditor({ mate, index, onChange, onRemove }) {
  const set = (field) => (value) => onChange({ ...mate, [field]: value })
  const toggleHabit = (habit) => {
    if (mate.habits.includes(habit)) return set('habits')(mate.habits.filter((item) => item !== habit))
    const opposite = { SMOKER: 'NON_SMOKER', NON_SMOKER: 'SMOKER' }[habit]
    set('habits')([...mate.habits.filter((item) => item !== opposite), habit])
  }

  return (
    <li className="rounded-lg border border-rule bg-white p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Flatmate {index + 1}</p>
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove flatmate ${index + 1}`}
          className="rounded p-1 text-ink-soft hover:bg-plaster hover:text-ink"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <TextField
          label="First name or nickname"
          required
          maxLength={40}
          value={mate.display_name}
          onChange={(event) => set('display_name')(event.target.value)}
        />
        <Segmented
          legend="Occupation"
          name={`occupation-${index}`}
          value={mate.occupation_type}
          options={Object.entries(OCCUPATIONS)}
          onChange={set('occupation_type')}
        />
        <TextField
          label={mate.occupation_type === 'STUDENT' ? 'University' : 'Job and workplace'}
          required
          minLength={2}
          maxLength={100}
          value={mate.institution}
          onChange={(event) => set('institution')(event.target.value)}
          className="sm:col-span-2"
        />
      </div>
      <fieldset className="mt-4">
        <legend className="mb-1.5 text-sm font-medium">Habits (up to {MAX_HABITS})</legend>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(HABITS).map(([habit, label]) => {
            const on = mate.habits.includes(habit)
            return (
              <button
                key={habit}
                type="button"
                aria-pressed={on}
                disabled={!on && mate.habits.length >= MAX_HABITS}
                onClick={() => toggleHabit(habit)}
                className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-40 ${
                  on ? 'border-tag-seat bg-tag-seat text-white' : 'border-rule text-ink-soft hover:border-ink'
                }`}
              >
                {label}
              </button>
            )
          })}
        </div>
      </fieldset>
    </li>
  )
}

// The flatmate list with its add button. `max` caps how many can be described.
function FlatmateList({ flatmates, onChange, max }) {
  return (
    <>
      <ul className="mt-3 space-y-3">
        {flatmates.map((mate, index) => (
          <FlatmateEditor
            key={index}
            mate={mate}
            index={index}
            onChange={(next) => onChange(flatmates.map((item, i) => (i === index ? next : item)))}
            onRemove={() => onChange(flatmates.filter((_, i) => i !== index))}
          />
        ))}
      </ul>
      <button
        type="button"
        onClick={() => onChange([...flatmates, { ...EMPTY_FLATMATE }])}
        disabled={flatmates.length >= max}
        className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-3 py-2 text-sm font-semibold hover:border-ink disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Plus className="size-4" aria-hidden="true" /> Add flatmate
      </button>
    </>
  )
}

// Keyed by id so switching between "new" and "edit" never carries form state across.
export default function ListingEditor() {
  const { id } = useParams()
  return <EditorForm key={id ?? 'new'} id={id} />
}

function EditorForm({ id }) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const isSublet = user.role === 'BACHELOR_TENANT'
  const [form, setForm] = useState(() => (isSublet ? { ...EMPTY_FORM, category: 'BACHELOR_SEAT' } : EMPTY_FORM))
  const [savedListing, setSavedListing] = useState(null)
  const [pendingPhotos, setPendingPhotos] = useState([])
  const [pendingVideo, setPendingVideo] = useState(null)
  // Photos picked for sublet rooms that haven't been saved yet, by room key.
  const [roomPhotos, setRoomPhotos] = useState({})
  const photoErrors = useLocation().state?.photoErrors ?? []
  const [loading, setLoading] = useState(Boolean(id))
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    getListing(id)
      .then((listing) => {
        if (cancelled) return
        if (listing.lister_id !== user.id) setLoadError('You can only edit your own listings.')
        else {
          setForm(fromListing(listing))
          setSavedListing(listing)
        }
      })
      .catch((err) => !cancelled && setLoadError(getErrorMessage(err)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [id, user.id])

  const setField = (field) => (value) => setForm((current) => ({ ...current, [field]: value }))
  const setIn = (section, field) => (value) =>
    setForm((current) => ({ ...current, [section]: { ...current[section], [field]: value } }))
  const bind = (section, field) => ({
    value: form[section][field],
    onChange: (event) => setIn(section, field)(event.target.value),
  })

  const isSeat = form.category === 'BACHELOR_SEAT'
  const totalSeats = Number(form.seats.total_seats)
  const occupiedSeats = Math.max(0, totalSeats - Number(form.seats.available_seats))
  const flatmates = form.seats.flatmates
  const setFlatmates = setIn('seats', 'flatmates')
  const preview = isSeat && !isSublet && totalSeats >= 2 ? seatSplit(form.pricing, totalSeats) : null

  // A bachelor tenant's sublet: one seat, or rooms each in their own section.
  const { sublet } = form
  const lettingRooms = isSublet && sublet.let_type === 'ROOMS'
  const setSublet = (field) => (value) => setForm((current) => ({ ...current, sublet: { ...current.sublet, [field]: value } }))
  const setSeat = (field, value) => setSublet('seat')({ ...sublet.seat, [field]: value })
  const bedrooms = Number(form.building.bedrooms) || 0

  function setRoomCount(count) {
    const { rooms } = sublet
    if (count >= rooms.length) {
      setSublet('rooms')([...rooms, ...Array.from({ length: count - rooms.length }, (_, index) => newRoom(rooms.length + index + 1))])
      return
    }
    const dropped = rooms.slice(count)
    const photos = dropped.reduce((sum, room) => sum + (savedListing?.sublet?.rooms.find((item) => item.id === room.id)?.photos.length ?? 0), 0)
    const names = dropped.map((room) => room.name).join(', ')
    if (photos && !window.confirm(`Remove ${names}? Their photos will be deleted when you save.`)) return
    setSublet('rooms')(rooms.slice(0, count))
    setRoomPhotos((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !dropped.some((room) => room.key === key))))
  }

  const needsPhoto = !id && pendingPhotos.length === 0
  const missing = !form.location.position
    ? needsPhoto
      ? 'Add at least one photo and pin the building on the map to publish.'
      : 'Pin the building on the map to publish.'
    : needsPhoto
      ? 'Add at least one photo to publish.'
      : ''

  async function handleSubmit(event) {
    event.preventDefault()
    if (!form.category) return setError('Choose what you are listing.')
    if (!form.location.position) return setError('Pin the building on the map to show where it is.')
    if (isSeat && !isSublet && flatmates.length > occupiedSeats) {
      return setError(`You listed ${flatmates.length} flatmates but only ${occupiedSeats} seats are taken.`)
    }
    if (lettingRooms && sublet.rooms.length > bedrooms) {
      return setError(`You're letting ${sublet.rooms.length} rooms but the flat has ${bedrooms} bedroom${bedrooms === 1 ? '' : 's'}.`)
    }
    setError('')
    setBusy(true)
    // Rooms come back in the order they were sent, now with ids, so photos picked for new rooms can follow them.
    const roomUploads = (listing) =>
      lettingRooms
        ? sublet.rooms.map((room, index) => [listing.sublet.rooms[index].id, roomPhotos[room.key] ?? []]).filter(([, files]) => files.length)
        : []
    try {
      if (id) {
        const updated = await updateListing(id, toPayload(form, isSublet))
        const { listing, failed } = await uploadPending(updated, { roomPhotos: roomUploads(updated) })
        if (failed.length) {
          // Saved, but stay here with the saved rooms so the photos can be added again.
          setSavedListing(listing)
          setForm(fromListing(listing))
          setRoomPhotos({})
          setError(`Saved, but some photos didn't upload: ${failed.join('. ')}. Add them again.`)
          setBusy(false)
          return
        }
        navigate(`/rentals/${listing.id}`)
        return
      }
      const created = await createListing(toPayload(form, isSublet))
      const { listing, failed } = await uploadPending(created, { photos: pendingPhotos, video: pendingVideo, roomPhotos: roomUploads(created) })
      // The listing exists either way; if a photo failed, the owner retries from the editor.
      navigate(failed.length ? `/listings/${listing.id}/edit` : `/rentals/${listing.id}`, { state: { photoErrors: failed } })
    } catch (err) {
      setError(getErrorMessage(err))
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="grid flex-1 place-items-center text-ink-soft" role="status">
        <LoaderCircle className="size-6 animate-spin" aria-label="Loading listing" />
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
        <Alert>{loadError}</Alert>
        <Link to="/listings" className="mt-4 inline-block text-sm font-semibold text-gate hover:underline">
          Back to my listings
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-28 pt-8 sm:px-6">
      <h1 className="font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">
        {id ? 'Edit listing' : isSublet ? 'Sublet seats' : 'Post a listing'}
      </h1>
      <p className="mt-3 text-ink-soft">
        {isSublet
          ? 'Let a seat or rooms in the flat you rent, each with its own rent.'
          : 'Tenants see these details in search and in side-by-side comparisons.'}
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-6">
        <FormSection title="What are you listing?">
          <fieldset>
            <legend className="sr-only">Category</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              {Object.entries(CATEGORIES).map(([key, category]) => {
                const locked = isSublet && key !== 'BACHELOR_SEAT'
                return (
                  <label
                    key={key}
                    className={`relative rounded-lg border-2 p-4 transition-colors has-[:checked]:border-ink has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-leaf ${
                      locked ? 'cursor-not-allowed opacity-45' : 'cursor-pointer border-rule bg-white hover:border-ink-soft'
                    }`}
                  >
                    <input
                      type="radio"
                      name="category"
                      value={key}
                      checked={form.category === key}
                      disabled={locked}
                      onChange={() => setField('category')(key)}
                      className="sr-only"
                    />
                    <span className="flex items-center gap-2 font-semibold">
                      <span aria-hidden="true" className="size-3 rounded-full" style={{ background: category.pin }} />
                      {category.label}
                    </span>
                    <span className="mt-1 block text-sm text-ink-soft">{isSublet && key === 'BACHELOR_SEAT' ? SUBLET_HELP : CATEGORY_HELP[key]}</span>
                  </label>
                )
              })}
            </div>
            {isSublet && (
              <p className="mt-2 text-xs text-ink-soft">As a tenant you can sublet seats, not whole flats.</p>
            )}
          </fieldset>
          {isSublet && (
            <fieldset>
              <legend className="mb-1.5 text-sm font-medium">What are you letting?</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  ['SEAT', 'A single seat', 'One bed in a shared room.'],
                  ['ROOMS', 'Rooms', 'One or more rooms, each with its own rent.'],
                ].map(([value, label, help]) => (
                  <label
                    key={value}
                    className="cursor-pointer rounded-lg border-2 border-rule bg-white p-4 transition-colors hover:border-ink-soft has-[:checked]:border-ink has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-leaf"
                  >
                    <input
                      type="radio"
                      name="let_type"
                      value={value}
                      checked={sublet.let_type === value}
                      onChange={() => setSublet('let_type')(value)}
                      className="sr-only"
                    />
                    <span className="block font-semibold">{label}</span>
                    <span className="mt-1 block text-sm text-ink-soft">{help}</span>
                  </label>
                ))}
              </div>
              {lettingRooms && (
                <label className="mt-4 block sm:w-56">
                  <span className="mb-1.5 block text-sm font-medium">How many rooms?</span>
                  <select
                    value={sublet.rooms.length}
                    onChange={(event) => setRoomCount(Number(event.target.value))}
                    className="w-full rounded-md border border-rule bg-white px-3 py-2.5"
                  >
                    {Array.from({ length: MAX_ROOMS }, (_, index) => (
                      <option key={index + 1} value={index + 1}>
                        {index + 1} room{index ? 's' : ''}
                      </option>
                    ))}
                  </select>
                  <span className="mt-1 block text-xs text-ink-soft">Up to the flat's bedrooms. Each room gets its own section below.</span>
                </label>
              )}
            </fieldset>
          )}
          <TextField
            label="Title"
            required
            minLength={5}
            maxLength={120}
            placeholder={isSeat ? 'Two seats in a quiet student flat near Azimpur' : '3-bed family flat with lift, Dhanmondi'}
            value={form.title}
            onChange={(event) => setField('title')(event.target.value)}
          />
          <div>
            <label htmlFor="description" className="mb-1.5 block text-sm font-medium">
              Description <span className="font-normal text-ink-soft">(optional)</span>
            </label>
            <textarea
              id="description"
              rows={4}
              maxLength={2000}
              value={form.description}
              onChange={(event) => setField('description')(event.target.value)}
              className="w-full rounded-md border border-rule bg-white px-3 py-2.5 focus:border-gate focus:outline-none focus-visible:outline-2 focus-visible:outline-gate"
            />
          </div>
          <TextField
            label="Available from"
            type="date"
            required
            value={form.available_from}
            onChange={(event) => setField('available_from')(event.target.value)}
            className="sm:w-56"
          />
        </FormSection>

        <FormSection
          title="Photos"
          description={
            lettingRooms
              ? 'Show the flat: the building, kitchen, bathrooms and shared spaces. Each room gets its own photos in its section.'
              : 'Show the room, seat or flat. Posts with clear photos get far more requests.'
          }
        >
          <PhotoManager
            listing={savedListing}
            onListingChange={setSavedListing}
            pending={pendingPhotos}
            onPendingChange={setPendingPhotos}
            pendingVideo={pendingVideo}
            onPendingVideoChange={setPendingVideo}
          />
          {photoErrors.length > 0 && (
            <Alert>
              Some photos didn't upload: {photoErrors.join('. ')}. Add them again here.
            </Alert>
          )}
        </FormSection>

        <FormSection title="Location" description="Pin the exact building. Tenants who are shifting to this area will find it.">
          <LocationPickerMap value={form.location} onChange={setField('location')} />
        </FormSection>

        {!isSublet && (
          <FormSection
            title="Rent and charges"
            description={isSeat ? 'Enter the whole flat’s monthly costs. Each seat’s share is worked out below.' : 'Monthly amounts in taka.'}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField
                label={isSeat ? 'Rent for the whole flat (৳)' : 'Monthly rent (৳)'}
                type="number"
                required
                min={1}
                {...bind('pricing', 'base_rent')}
              />
              <TextField label="Service charge (৳)" type="number" min={0} {...bind('pricing', 'service_charge')} />
              <TextField
                label="Utilities estimate (৳)"
                hint="Gas, electricity, water and internet."
                type="number"
                min={0}
                {...bind('pricing', 'utility_estimate')}
              />
              <TextField label="Maid estimate (৳)" type="number" min={0} {...bind('pricing', 'maid_estimate')} />
              <TextField
                label="Deposit (months of rent)"
                type="number"
                required
                min={0}
                max={12}
                {...bind('pricing', 'deposit_months')}
              />
            </div>
          </FormSection>
        )}

        {isSublet && !lettingRooms && (
          <FormSection title="Rent and charges" description="Monthly amounts in taka for the seat. Leave a charge blank if there isn't one.">
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField
                label="Rent for the seat (৳)"
                type="number"
                required
                min={1}
                value={sublet.seat.seat_rent}
                onChange={(event) => setSeat('seat_rent', event.target.value)}
              />
              <ChargeFields values={sublet.seat} onChange={setSeat} />
              <TextField
                label="Deposit (months of rent)"
                type="number"
                required
                min={0}
                max={12}
                {...bind('pricing', 'deposit_months')}
              />
            </div>
          </FormSection>
        )}

        {lettingRooms && (
          <>
            {sublet.rooms.map((room, index) => (
              <SubletRoomSection
                key={room.key}
                room={room}
                index={index}
                savedListing={savedListing}
                onChange={(next) => setSublet('rooms')(sublet.rooms.map((item) => (item.key === room.key ? next : item)))}
                pendingPhotos={roomPhotos[room.key] ?? []}
                onPendingPhotosChange={(files) => setRoomPhotos((current) => ({ ...current, [room.key]: files }))}
                onListingChange={setSavedListing}
              />
            ))}
            <FormSection title="Deposit" description="Paid in advance for any of the rooms, as months of its rent.">
              <TextField
                label="Deposit (months of rent)"
                type="number"
                required
                min={0}
                max={12}
                className="sm:w-56"
                {...bind('pricing', 'deposit_months')}
              />
            </FormSection>
          </>
        )}

        <FormSection title="Building">
          <div className="grid gap-4 sm:grid-cols-3">
            <TextField
              label="Floor"
              hint="0 for ground floor."
              type="number"
              required
              min={0}
              max={79}
              {...bind('building', 'floor_level')}
            />
            <TextField label="Floors in building" type="number" required min={1} max={80} {...bind('building', 'total_floors')} />
            <TextField label="Size (sq ft)" type="number" min={80} {...bind('building', 'size_sqft')} />
            <TextField
              label="Bedrooms"
              hint={lettingRooms ? `You're letting ${sublet.rooms.length} of them.` : undefined}
              type="number"
              required
              min={lettingRooms ? sublet.rooms.length : 1}
              max={12}
              {...bind('building', 'bedrooms')}
            />
            <TextField label="Bathrooms" type="number" required min={1} max={12} {...bind('building', 'bathrooms')} />
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <Checkbox label="Lift" checked={form.building.has_elevator} onChange={setIn('building', 'has_elevator')} />
            <Checkbox
              label="Generator backup"
              checked={form.building.has_generator_backup}
              onChange={setIn('building', 'has_generator_backup')}
            />
          </div>
        </FormSection>

        <FormSection title="House rules">
          <div className="flex flex-wrap items-end gap-4">
            <TextField
              label="Gate closes at"
              type="time"
              required={!form.house_rules.gate_open_all_night}
              disabled={form.house_rules.gate_open_all_night}
              {...bind('house_rules', 'gate_closing_time')}
              className="w-40"
            />
            <div className="pb-2.5">
              <Checkbox
                label="Gate open all night"
                checked={form.house_rules.gate_open_all_night}
                onChange={setIn('house_rules', 'gate_open_all_night')}
              />
            </div>
          </div>
          <Segmented
            legend="Guests"
            name="guest_policy"
            value={form.house_rules.guest_policy}
            options={Object.entries(GUEST_POLICIES)}
            onChange={setIn('house_rules', 'guest_policy')}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Segmented
              legend="Smoking"
              name="smoking_allowed"
              value={form.house_rules.smoking_allowed}
              options={[
                [false, 'Not allowed'],
                [true, 'Allowed'],
              ]}
              onChange={setIn('house_rules', 'smoking_allowed')}
            />
            <Segmented
              legend="Electricity meter"
              name="meter_type"
              value={form.house_rules.meter_type}
              options={[
                ['PREPAID', 'Prepaid'],
                ['POSTPAID', 'Postpaid'],
              ]}
              onChange={setIn('house_rules', 'meter_type')}
            />
          </div>
        </FormSection>

        {isSeat && !isSublet && (
          <FormSection title="Seats and flatmates" description="Count every bed in the flat, including taken ones.">
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField label="Total seats" type="number" required min={2} max={20} {...bind('seats', 'total_seats')} />
              <TextField
                label="Free seats"
                type="number"
                required
                min={0}
                max={totalSeats || 20}
                {...bind('seats', 'available_seats')}
              />
            </div>

            {preview && (
              <div className="rounded-lg border border-tag-seat/30 bg-white p-4">
                <p className="mb-2 text-sm font-semibold">What each tenant pays</p>
                <SeatSplit pricing={form.pricing} totalSeats={totalSeats} split={preview} />
              </div>
            )}

            <div>
              <p className="text-sm font-medium">
                Current flatmates{' '}
                <span className="font-normal text-ink-soft">
                  ({flatmates.length} of {occupiedSeats} taken seats described)
                </span>
              </p>
              <FlatmateList flatmates={flatmates} onChange={setFlatmates} max={occupiedSeats} />
            </div>
          </FormSection>
        )}

        {isSublet && (
          <FormSection
            title={lettingRooms ? 'Current flatmates' : 'Seat and flatmates'}
            description="The people already living in the flat, so tenants know who they'd share with."
          >
            {!lettingRooms && (
              <TextField
                label="Seats in the room"
                hint="This seat and the ones already taken."
                type="number"
                required
                min={2}
                max={MAX_ROOM_SEATS}
                value={sublet.seat.room_size}
                onChange={(event) => setSeat('room_size', event.target.value)}
                className="sm:w-56"
              />
            )}
            <div>
              <p className="text-sm font-medium">
                Current flatmates <span className="font-normal text-ink-soft">({sublet.flatmates.length} described)</span>
              </p>
              <FlatmateList flatmates={sublet.flatmates} onChange={setSublet('flatmates')} max={MAX_FLATMATES} />
            </div>
          </FormSection>
        )}

        <Alert>{error}</Alert>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {missing && <p className="mr-auto text-sm text-ink-soft">{missing}</p>}
          <Link to={id ? `/rentals/${id}` : '/listings'} className="px-3 py-2 text-sm font-semibold text-ink-soft hover:text-ink">
            Cancel
          </Link>
          <Button type="submit" busy={busy} disabled={Boolean(missing)}>
            {id ? 'Save changes' : 'Publish listing'}
          </Button>
        </div>
      </form>
    </div>
  )
}
