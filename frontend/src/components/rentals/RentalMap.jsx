import L from 'leaflet'
import '../../lib/leafletIcons.js'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Circle, MapContainer, Marker, Popup, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { Link } from 'react-router-dom'
import { CATEGORIES, DHAKA_CENTER, areaLabel, formatTaka, rentPrefix, rentUnit, shortTaka } from '../../constants/rentals.js'
import { getBoundary } from '../../api/locations.js'
import { CoverPhoto } from '../photos/ListingPhotos.jsx'
import { BaseTiles, MAP_LIMITS, MapStyleSwitch, PlaceLabels, RegionOutline } from '../map/MapLayers.jsx'
import CompareToggle from './CompareToggle.jsx'

export { BaseTiles } from '../map/MapLayers.jsx'

export const centerPinIcon = L.divIcon({ className: '', iconSize: [0, 0], html: '<span class="center-pin"></span>' })

function priceIcon(color, label) {
  return L.divIcon({ className: '', iconSize: [0, 0], html: `<span class="price-pin" style="--pin:${color}">${label}</span>` })
}

// Default pin and popup are for rentals; the sale map passes its own.
const rentalPin = (listing) => ({ color: CATEGORIES[listing.category].pin, label: shortTaka(listing.effective_rent) })

function RentalPopup({ listing }) {
  return (
    <div className="w-56 font-sans">
      <CoverPhoto listing={listing} className="mb-2 h-28 w-full rounded" />
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-soft">
        {CATEGORIES[listing.category].label} · {areaLabel(listing.location)}
      </p>
      <Link to={`/rentals/${listing.id}`} className="mt-1 block font-semibold leading-snug !text-ink hover:underline">
        {listing.title}
      </Link>
      <p className="mt-1 font-mono text-sm">
        <span className="font-sans text-xs text-ink-soft">{rentPrefix(listing)}</span>
        {formatTaka(listing.effective_rent)}
        <span className="font-sans text-xs text-ink-soft"> {rentUnit(listing)}</span>
      </p>
      <CompareToggle listing={listing} className="mt-2" />
    </div>
  )
}

// A listing's `location.geo` is GeoJSON, [lng, lat]; Leaflet wants [lat, lng].
export const toLatLng = (location) => [location.geo.coordinates[1], location.geo.coordinates[0]]

// While `picking`, the map shows a crosshair. The class is toggled on Leaflet's container directly: re-rendering
// MapContainer's className would wipe the classes Leaflet adds to the same element.
function MapClicks({ onPick, picking }) {
  const map = useMap()
  useMapEvents({ click: (event) => onPick?.(event.latlng) })
  useEffect(() => {
    map.getContainer().classList.toggle('map-picking', picking)
  }, [map, picking])
  return null
}

// Re-frames the map when a new search comes back, and repairs Leaflet's size after being hidden: the search circle,
// else the division / district / upazila being searched, else the results, else `focus` (the target area's centre
// when nothing matched).
function FrameResults({ center, radiusKm, listings, focus, framedRegion, fitKey, visible }) {
  const map = useMap()
  const latest = useRef({ center, radiusKm, listings, focus })
  latest.current = { center, radiusKm, listings, focus }

  useEffect(() => {
    if (!visible) return
    map.invalidateSize()
    const { center, radiusKm, listings, focus } = latest.current
    let live = true
    if (center && radiusKm) {
      map.fitBounds(L.latLng(center.lat, center.lng).toBounds(radiusKm * 2000), { padding: [16, 16] })
    } else if (framedRegion) {
      getBoundary(framedRegion).then(
        (feature) => live && map.fitBounds(L.geoJSON(feature).getBounds(), { padding: [24, 24] }),
        () => {},
      )
    } else if (listings.length > 0) {
      map.fitBounds(L.latLngBounds(listings.map((listing) => toLatLng(listing.location))), {
        padding: [48, 48],
        maxZoom: 15,
      })
    } else if (focus) {
      map.setView(focus, 14)
    }
    return () => {
      live = false
    }
  }, [map, fitKey, visible, framedRegion])
  return null
}

// Highlighting toggles a class on the existing pin rather than swapping the icon: replacing the
// element under the cursor would fire mouseout/mouseover and make the hover flicker.
function PriceMarker({ listing, active, onHover, pinOf, Popup: PopupContent }) {
  const markerRef = useRef(null)
  const { color, label } = pinOf(listing)
  const icon = useMemo(() => priceIcon(color, label), [color, label])

  useEffect(() => {
    const marker = markerRef.current
    if (!marker) return
    marker.getElement()?.firstElementChild?.classList.toggle('is-active', active)
    marker.setZIndexOffset(active ? 1000 : 0)
  }, [active, icon])

  return (
    <Marker
      ref={markerRef}
      position={toLatLng(listing.location)}
      icon={icon}
      title={listing.title}
      eventHandlers={{ mouseover: () => onHover?.(listing.id), mouseout: () => onHover?.(null) }}
    >
      <Popup>
        <PopupContent listing={listing} />
      </Popup>
    </Marker>
  )
}

export default function RentalMap({
  listings,
  center,
  radiusKm,
  activeId,
  onHover,
  onPick,
  picking = false,
  focus = null,
  region = null,
  fitKey,
  visible = true,
  pinOf = rentalPin,
  popup = RentalPopup,
}) {
  const [mapStyle, setMapStyle] = useState('streets')
  // `region` is { id, fit }: the division, district or upazila being searched, outlined (and framed when `fit`).
  return (
    <div className="relative size-full">
      <MapContainer center={DHAKA_CENTER} zoom={12} className="size-full" scrollWheelZoom {...MAP_LIMITS}>
        <BaseTiles style={mapStyle} />
        <PlaceLabels />
        {region && <RegionOutline id={region.id} />}
        <MapClicks onPick={onPick} picking={picking} />
        <FrameResults
          center={center}
          radiusKm={radiusKm}
          listings={listings}
          focus={focus}
          framedRegion={region?.fit ? region.id : null}
          fitKey={fitKey}
          visible={visible}
        />

        {center && radiusKm && (
          <>
            <Circle
              center={[center.lat, center.lng]}
              radius={radiusKm * 1000}
              pathOptions={{ color: '#429a4a', weight: 1.5, fillColor: '#429a4a', fillOpacity: 0.06 }}
              interactive={false}
            />
            <Marker position={[center.lat, center.lng]} icon={centerPinIcon} keyboard={false}>
              <Tooltip direction="top" offset={[0, -12]} permanent>
                {center.label}
              </Tooltip>
            </Marker>
          </>
        )}

        {listings.map((listing) => (
          <PriceMarker
            key={listing.id}
            listing={listing}
            active={listing.id === activeId}
            onHover={onHover}
            pinOf={pinOf}
            Popup={popup}
          />
        ))}
      </MapContainer>
      {/* At the top on phones, where the map credits wrap onto several lines at the bottom. */}
      <MapStyleSwitch value={mapStyle} onChange={setMapStyle} className="right-3 top-3 lg:bottom-6 lg:top-auto" />
    </div>
  )
}
