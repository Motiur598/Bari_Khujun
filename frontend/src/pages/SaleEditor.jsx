import { LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { createSale, getSale, updateSale } from '../api/marketplace.js'
import { uploadPending } from '../api/photos.js'
import LocationPickerMap, { EMPTY_LOCATION, locationFromListing, locationToPayload } from '../components/LocationPickerMap.jsx'
import { PhotoManager } from '../components/photos/ListingPhotos.jsx'
import { Alert, Button, Checkbox, FormSection, Segmented, TextField } from '../components/ui.jsx'
import { HANDOVER, PROPERTY_TYPES, formatPrice } from '../constants/marketplace.js'
import { formatTaka } from '../constants/rentals.js'
import { useAuth } from '../context/AuthContext.jsx'

const EMPTY_FORM = {
  property_type: 'APARTMENT',
  title: '',
  description: '',
  location: EMPTY_LOCATION,
  building: { floor_level: '', total_floors: '', bedrooms: '', bathrooms: '', size_sqft: '', has_elevator: false, has_generator_backup: false },
  sale: { asking_price: '', price_negotiable: true, parking_slots: '0', handover_status: 'READY_FLAT', expected_handover: '', blueprint_url: '' },
}

function fromListing(listing) {
  const { building, sale } = listing
  const text = (value) => (value == null ? '' : String(value))
  return {
    property_type: listing.property_type,
    title: listing.title,
    description: listing.description,
    location: locationFromListing(listing.location),
    building: {
      ...Object.fromEntries(['floor_level', 'total_floors', 'bedrooms', 'bathrooms', 'size_sqft'].map((k) => [k, text(building[k])])),
      has_elevator: building.has_elevator,
      has_generator_backup: building.has_generator_backup,
    },
    sale: {
      asking_price: text(sale.asking_price),
      price_negotiable: sale.price_negotiable,
      parking_slots: text(sale.parking_slots),
      handover_status: sale.handover_status,
      expected_handover: text(sale.expected_handover),
      blueprint_url: text(sale.blueprint_url),
    },
  }
}

function toPayload(form) {
  const { building, sale } = form
  const isHouse = form.property_type === 'HOUSE'
  return {
    property_type: form.property_type,
    title: form.title.trim(),
    description: form.description.trim(),
    location: locationToPayload(form.location),
    building: {
      // A house is recorded from the ground floor up.
      floor_level: isHouse ? 0 : Number(building.floor_level),
      total_floors: Number(building.total_floors),
      bedrooms: Number(building.bedrooms),
      bathrooms: Number(building.bathrooms),
      size_sqft: Number(building.size_sqft),
      has_elevator: building.has_elevator,
      has_generator_backup: building.has_generator_backup,
    },
    sale: {
      asking_price: Number(sale.asking_price),
      price_negotiable: sale.price_negotiable,
      parking_slots: Number(sale.parking_slots || 0),
      handover_status: sale.handover_status,
      expected_handover: sale.handover_status === 'UNDER_CONSTRUCTION' ? sale.expected_handover : null,
      blueprint_url: sale.blueprint_url.trim() || null,
    },
  }
}

export default function SaleEditor() {
  const { id } = useParams()
  return <SaleForm key={id ?? 'new'} id={id} />
}

function SaleForm({ id }) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [form, setForm] = useState(EMPTY_FORM)
  const [savedListing, setSavedListing] = useState(null)
  const [pendingPhotos, setPendingPhotos] = useState([])
  const [pendingVideo, setPendingVideo] = useState(null)
  const photoErrors = useLocation().state?.photoErrors ?? []
  const [loading, setLoading] = useState(Boolean(id))
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!id) return
    getSale(id)
      .then((listing) => {
        if (listing.lister_id !== user.id) return setLoadError('You can only edit your own listings.')
        setForm(fromListing(listing))
        setSavedListing(listing)
      })
      .catch((err) => setLoadError(getErrorMessage(err)))
      .finally(() => setLoading(false))
  }, [id, user.id])

  const setField = (field) => (value) => setForm((current) => ({ ...current, [field]: value }))
  const setIn = (section, field) => (value) => setForm((current) => ({ ...current, [section]: { ...current[section], [field]: value } }))
  const bind = (section, field) => ({ value: form[section][field], onChange: (event) => setIn(section, field)(event.target.value) })

  const needsPhoto = !id && pendingPhotos.length === 0
  const missing = !form.location.position
    ? needsPhoto
      ? 'Add at least one photo and pin the property on the map to publish.'
      : 'Pin the property on the map to publish.'
    : needsPhoto
      ? 'Add at least one photo to publish.'
      : ''

  async function handleSubmit(event) {
    event.preventDefault()
    if (!form.location.position) return setError('Pin the property on the map to show where it is.')
    setError('')
    setBusy(true)
    try {
      if (id) {
        navigate(`/sale/${(await updateSale(id, toPayload(form))).id}`)
        return
      }
      const { listing, failed } = await uploadPending(await createSale(toPayload(form)), { photos: pendingPhotos, video: pendingVideo })
      // The listing exists either way; if a photo failed, the owner retries from the editor.
      navigate(failed.length ? `/sale/${listing.id}/edit` : `/sale/${listing.id}`, { state: { photoErrors: failed } })
    } catch (err) {
      setError(getErrorMessage(err))
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="grid flex-1 place-items-center text-ink-soft" role="status">
        <LoaderCircle className="size-6 animate-spin" aria-label="Loading property" />
      </div>
    )
  }
  if (loadError) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
        <Alert>{loadError}</Alert>
      </div>
    )
  }

  const price = Number(form.sale.asking_price) || 0
  const size = Number(form.building.size_sqft) || 0
  const isHouse = form.property_type === 'HOUSE'

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-28 pt-8 sm:px-6">
      <h1 className="font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">
        {id ? 'Edit property' : 'Sell a property'}
      </h1>
      <p className="mt-3 text-ink-soft">
        After publishing, upload the title documents from the property page to earn the Verified title badge.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-6">
        <FormSection title="The basics">
          <Segmented legend="Property type" name="property_type" value={form.property_type} options={Object.entries(PROPERTY_TYPES)} onChange={setField('property_type')} />
          <TextField label="Title" required minLength={5} maxLength={120} placeholder="3-bed lake-facing apartment, Dhanmondi" value={form.title} onChange={(e) => setField('title')(e.target.value)} />
          <div>
            <label htmlFor="sale-description" className="mb-1.5 block text-sm font-medium">
              Description <span className="font-normal text-ink-soft">(optional)</span>
            </label>
            <textarea
              id="sale-description"
              rows={4}
              maxLength={2000}
              value={form.description}
              onChange={(e) => setField('description')(e.target.value)}
              className="w-full rounded-md border border-rule bg-white px-3 py-2.5 focus:border-gate focus:outline-none focus-visible:outline-2 focus-visible:outline-gate"
            />
          </div>
        </FormSection>

        <FormSection title="Price and handover">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Asking price (৳)"
              type="number"
              required
              min={1}
              hint={price ? `${formatPrice(price)}${size ? ` · ${formatTaka(Math.round(price / size))}/sq ft` : ''}` : undefined}
              {...bind('sale', 'asking_price')}
            />
            <TextField label="Parking slots" type="number" min={0} max={20} {...bind('sale', 'parking_slots')} />
          </div>
          <Checkbox label="Price is negotiable" checked={form.sale.price_negotiable} onChange={setIn('sale', 'price_negotiable')} />
          <Segmented legend="Handover" name="handover" value={form.sale.handover_status} options={Object.entries(HANDOVER)} onChange={setIn('sale', 'handover_status')} />
          {form.sale.handover_status === 'UNDER_CONSTRUCTION' && (
            <TextField label="Expected handover" type="date" required {...bind('sale', 'expected_handover')} className="sm:w-56" />
          )}
          <TextField
            label="Floor plan image URL (optional)"
            type="url"
            placeholder="https://…/floor-plan.png"
            hint="A link to a JPG, PNG or SVG of the layout."
            {...bind('sale', 'blueprint_url')}
          />
        </FormSection>

        <FormSection
          title="Photos"
          description="Show the rooms, the building and the view. Buyers skip listings without photos."
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

        <FormSection title="Location" description="Pin the exact building. Buyers looking in this area will find it.">
          <LocationPickerMap value={form.location} onChange={setField('location')} />
        </FormSection>

        <FormSection title="Building">
          <div className="grid gap-4 sm:grid-cols-3">
            <TextField label="Size (sq ft)" type="number" required min={80} {...bind('building', 'size_sqft')} />
            {!isHouse && <TextField label="Floor" hint="0 for ground floor." type="number" required min={0} max={79} {...bind('building', 'floor_level')} />}
            <TextField label={isHouse ? 'Storeys' : 'Floors in building'} type="number" required min={1} max={80} {...bind('building', 'total_floors')} />
            <TextField label="Bedrooms" type="number" required min={1} max={12} {...bind('building', 'bedrooms')} />
            <TextField label="Bathrooms" type="number" required min={1} max={12} {...bind('building', 'bathrooms')} />
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <Checkbox label="Lift" checked={form.building.has_elevator} onChange={setIn('building', 'has_elevator')} />
            <Checkbox label="Generator backup" checked={form.building.has_generator_backup} onChange={setIn('building', 'has_generator_backup')} />
          </div>
        </FormSection>

        <Alert>{error}</Alert>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {missing && <p className="mr-auto text-sm text-ink-soft">{missing}</p>}
          <Link to={id ? `/sale/${id}` : '/listings'} className="px-3 py-2 text-sm font-semibold text-ink-soft hover:text-ink">
            Cancel
          </Link>
          <Button type="submit" busy={busy} disabled={Boolean(missing)}>
            {id ? 'Save changes' : 'Publish property'}
          </Button>
        </div>
      </form>
    </div>
  )
}
