import L from 'leaflet'
import { LoaderCircle, LocateFixed, Lock, Map as MapIcon, MapPin } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { MapContainer, Marker, useMap, useMapEvents } from 'react-leaflet'
import { areaFor, fullAddressFrom, reverseGeocode } from '../api/geocode.js'
import { locatePoint } from '../api/locations.js'
import { getAreas, getLandmarks } from '../api/rentals.js'
import { DHAKA_CENTER } from '../constants/rentals.js'
import { BaseTiles, MAP_LIMITS, MapStyleSwitch, PlaceLabels } from './map/MapLayers.jsx'
import PlaceSearch from './search/PlaceSearch.jsx'
import { TextField } from './ui.jsx'

const housePinIcon = L.divIcon({ className: '', iconSize: [0, 0], html: '<span class="house-pin"></span>' })
const LOOKUP_DELAY_MS = 500
const GPS_ERRORS = {
  1: 'Location access is blocked. Allow it for this site in your browser, or click the map instead.',
  2: "Your device couldn't find its position. Click the map instead.",
  3: 'Finding your position took too long. Try again, or click the map instead.',
}

const ADDRESS_FIELDS = ['area_name', 'sub_area', 'formatted_address']

export const EMPTY_LOCATION = { city: 'Dhaka', area_name: '', sub_area: '', formatted_address: '', position: null }

// Form state <-> API shape. `position` is [lat, lng] for Leaflet; the API stores GeoJSON [lng, lat] at `geo`.
export const locationFromListing = ({ geo, sub_area, ...rest }) => ({
  ...rest,
  sub_area: sub_area ?? '',
  position: [geo.coordinates[1], geo.coordinates[0]],
})
export const locationToPayload = ({ position, city, area_name, sub_area, formatted_address }) => ({
  city: city.trim(),
  area_name: area_name.trim(),
  sub_area: sub_area.trim() || null,
  formatted_address: formatted_address.trim(),
  geo: { type: 'Point', coordinates: [Number(position[1].toFixed(6)), Number(position[0].toFixed(6))] },
})

function MapClicks({ onPick }) {
  useMapEvents({ click: (event) => onPick([event.latlng.lat, event.latlng.lng]) })
  return null
}

// `target` is { position, zoom } or, for a division / district / upazila, { bounds }.
function FlyTo({ target }) {
  const map = useMap()
  useEffect(() => {
    if (target?.bounds) map.flyToBounds(target.bounds, { duration: 0.8, padding: [16, 16] })
    else if (target) map.flyTo(target.position, target.zoom, { duration: 0.8 })
  }, [map, target])
  return null
}

// Where the property is. The owner pins the building (GPS, a click, or dragging the pin), and every move looks the
// point up on OpenStreetMap to fill the area, sub-area and full address, and finds its division, district and
// upazila/thana (tenants narrow their search by those). Fields the owner has typed in are kept.
// `value` is { city, area_name, sub_area, formatted_address, position: [lat, lng] | null }.
export default function LocationPickerMap({ value, onChange }) {
  const id = useId()
  const [areas, setAreas] = useState([])
  const [landmarks, setLandmarks] = useState([])
  const [mapStyle, setMapStyle] = useState('streets')
  // { division, district, upazila } of the pin, 'outside' Bangladesh, or null while unknown. A saved listing has it.
  const [region, setRegion] = useState(() =>
    value.district ? { division: value.division, district: value.district, upazila: value.upazila } : null,
  )
  const areasRef = useRef(areas)
  areasRef.current = areas
  const [flyTarget, setFlyTarget] = useState(null)
  const [status, setStatus] = useState(null) // { busy, tone, text }
  const [accuracy, setAccuracy] = useState(null)
  const latest = useRef(value)
  latest.current = value
  // An existing listing's address was written by its owner, so a pin move doesn't overwrite it.
  const typed = useRef(Object.fromEntries(ADDRESS_FIELDS.map((field) => [field, Boolean(value[field])])))
  const lookup = useRef({ timer: null, controller: null, found: null })

  useEffect(() => {
    getAreas().then(setAreas, () => setAreas([]))
    getLandmarks().then(setLandmarks, () => setLandmarks([]))
    const pending = lookup.current
    return () => {
      clearTimeout(pending.timer)
      pending.controller?.abort()
    }
  }, [])

  function fill(found, { force = false } = {}) {
    const next = { ...latest.current }
    // The map's sub-area belongs to the map's area, so it isn't used under a different area the owner typed.
    const ownArea = typed.current.area_name && next.area_name.trim().toLowerCase() !== found.area_name.toLowerCase()
    for (const field of ADDRESS_FIELDS) {
      if (field === 'sub_area' && ownArea && !force) continue
      // An empty sub-area is a real answer (the new spot has none); an empty area or address just means "unknown".
      if ((found[field] || field === 'sub_area') && (force || !typed.current[field])) {
        next[field] = found[field]
        typed.current[field] = false
      }
    }
    if (found.city) next.city = found.city
    onChange(next)
  }

  function lookUp(position) {
    const pending = lookup.current
    clearTimeout(pending.timer)
    pending.controller?.abort()
    setStatus({ busy: true, text: 'Looking up the address…' })
    pending.timer = setTimeout(async () => {
      const controller = new AbortController()
      pending.controller = controller
      // Our own lookup: null outside Bangladesh, undefined when it couldn't be asked.
      const inBangladesh = locatePoint(position[0], position[1]).catch(() => undefined)
      inBangladesh.then((found) => !controller.signal.aborted && setRegion(found === null ? 'outside' : (found ?? null)))
      try {
        const address = await reverseGeocode(position[0], position[1], controller.signal)
        const place = await inBangladesh
        const area = areaFor(position, address, areasRef.current, place?.upazila)
        // Villages have no city in OpenStreetMap; the district's name is what people write instead.
        const city = address.city ?? address.town ?? place?.district ?? latest.current.city
        pending.found = { ...area, city, formatted_address: fullAddressFrom(address, { ...area, city }) }
        fill(pending.found)
        const kept = ADDRESS_FIELDS.some((field) => typed.current[field])
        setStatus({
          tone: 'ok',
          text: kept
            ? 'Pin moved. The address you typed is kept.'
            : address.road
              ? "Address filled in from the map. Check it, and add the house number if it's missing."
              : "Area filled in from the map. It doesn't know the street here, so add the house and road number.",
          canRefill: kept,
        })
      } catch {
        if (controller.signal.aborted) return
        setStatus({ tone: 'error', text: "Couldn't look up this spot's address. Type the area and address below." })
      }
    }, LOOKUP_DELAY_MS)
  }

  function placePin(position, { fromGps = false } = {}) {
    if (!fromGps) setAccuracy(null)
    setRegion(null)
    onChange({ ...latest.current, position })
    lookUp(position)
  }

  function useMyLocation() {
    if (!navigator.geolocation) {
      setStatus({ tone: 'error', text: "This browser can't share its location. Click the map instead." })
      return
    }
    setStatus({ busy: true, text: 'Finding your location…' })
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const position = [coords.latitude, coords.longitude]
        setAccuracy(Math.round(coords.accuracy))
        setFlyTarget({ position, zoom: 18 })
        placePin(position, { fromGps: true })
      },
      (error) => setStatus({ tone: 'error', text: GPS_ERRORS[error.code] ?? GPS_ERRORS[2] }),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    )
  }

  // Clearing a field hands it back to the map.
  const typedInto = (field) => (event) => {
    typed.current[field] = event.target.value.trim() !== ''
    onChange({ ...latest.current, [field]: event.target.value })
  }

  const popular = areas.filter((area) => area.popular)

  // An address or building found by name drops the pin there (then fine-tune it); an area, campus, division, district
  // or upazila just moves the map.
  function goToPlace(place) {
    const position = [place.lat, place.lng]
    if (place.kind === 'region') {
      const [west, south, east, north] = place.unit.bbox
      setFlyTarget({ bounds: [[south, west], [north, east]] })
    } else if (place.kind === 'place') {
      setFlyTarget({ position, zoom: 18 })
      placePin(position)
    } else {
      setFlyTarget({ position, zoom: place.kind === 'area' ? 15 : 16 })
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button
          type="button"
          onClick={useMyLocation}
          className="inline-flex items-center gap-2 rounded-md bg-ink px-3.5 py-2 text-sm font-semibold text-white hover:bg-ink/85"
        >
          <LocateFixed className="size-4" aria-hidden="true" /> Use my current location
        </button>
        <PlaceSearch
          areas={popular}
          landmarks={landmarks}
          onPick={goToPlace}
          placeholder="or search: Road 4 Uttara, Binodpur, Paba…"
        />
      </div>

      <div className="relative h-80 overflow-hidden rounded-lg border border-rule">
        <MapContainer
          center={value.position ?? DHAKA_CENTER}
          zoom={value.position ? 17 : 13}
          className="size-full cursor-crosshair"
          {...MAP_LIMITS}
        >
          <BaseTiles style={mapStyle} />
          <PlaceLabels />
          <MapClicks onPick={placePin} />
          <FlyTo target={flyTarget} />
          {value.position && (
            <Marker
              position={value.position}
              icon={housePinIcon}
              draggable
              title="Drag onto the building entrance"
              eventHandlers={{
                dragend: (event) => {
                  const { lat, lng } = event.target.getLatLng()
                  placePin([lat, lng])
                },
              }}
            />
          )}
        </MapContainer>
        <MapStyleSwitch value={mapStyle} onChange={setMapStyle} />
        {!value.position && (
          // Under the style switch, clear of the zoom buttons and of the map credits (several lines tall on a phone).
          <p className="pointer-events-none absolute left-12 right-3 top-12 z-[500] ml-auto w-fit rounded-md bg-sheet/95 px-3 py-1.5 text-right text-sm shadow-sm">
            Click the building on the map, or use your current location.
          </p>
        )}
      </div>

      <div className="space-y-1 text-sm" aria-live="polite">
        {value.position ? (
          <>
            <p className="flex flex-wrap items-center gap-x-1.5 font-medium text-gate-dark">
              <Lock className="size-4" aria-hidden="true" />
              Pin locked at <span className="font-mono">{value.position[0].toFixed(5)}, {value.position[1].toFixed(5)}</span>
            </p>
            {region === 'outside' ? (
              <p className="text-tag-owner">This spot is outside Bangladesh. Pin the building on the map of Bangladesh.</p>
            ) : (
              region && (
                <p className="flex flex-wrap items-center gap-x-1.5 text-ink">
                  <MapIcon className="size-4 text-leaf" aria-hidden="true" />
                  {region.upazila}, {region.district} district, {region.division} division
                </p>
              )
            )}
            {accuracy !== null && (
              <p className="text-ink-soft">GPS accurate to about {accuracy} m. Drag the pin onto the entrance if needed.</p>
            )}
          </>
        ) : (
          <p className="flex items-center gap-1.5 text-ink-soft">
            <MapPin className="size-4" aria-hidden="true" /> No pin yet. The listing can't be published until the building is pinned.
          </p>
        )}
        {status && (
          <p className={`flex flex-wrap items-center gap-x-1.5 ${status.tone === 'error' ? 'text-tag-owner' : 'text-ink-soft'}`}>
            {status.busy && <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />}
            {status.text}
            {status.canRefill && (
              <button
                type="button"
                onClick={() => {
                  fill(lookup.current.found, { force: true })
                  setStatus({ tone: 'ok', text: 'Address replaced with the one from the map.' })
                }}
                className="font-semibold text-gate hover:underline"
              >
                Use the map's address
              </button>
            )}
          </p>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <TextField
          label="Area"
          placeholder="Uttara"
          required
          minLength={2}
          maxLength={60}
          list={`${id}-areas`}
          hint="Tenants search by area."
          value={value.area_name}
          onChange={typedInto('area_name')}
        />
        <TextField
          label="Sub-area (optional)"
          placeholder="Sector 7"
          maxLength={60}
          value={value.sub_area}
          onChange={typedInto('sub_area')}
        />
        <TextField label="City" required minLength={2} maxLength={60} value={value.city} onChange={(event) => onChange({ ...latest.current, city: event.target.value })} />
        <TextField
          label="Full address"
          placeholder="House 12, Road 4, Sector 7, Uttara, Dhaka"
          required
          minLength={3}
          maxLength={200}
          value={value.formatted_address}
          onChange={typedInto('formatted_address')}
          className="sm:col-span-3"
        />
        <datalist id={`${id}-areas`}>
          {popular.map((area) => (
            <option key={area.name} value={area.name} />
          ))}
        </datalist>
      </div>
      <p className="text-xs text-ink-soft">
        Addresses come from{' '}
        <a href="https://nominatim.openstreetmap.org/" target="_blank" rel="noreferrer" className="underline">
          OpenStreetMap Nominatim
        </a>
        .
      </p>
    </div>
  )
}
