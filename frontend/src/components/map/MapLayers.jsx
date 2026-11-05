import L from 'leaflet'
import { useEffect, useMemo, useState } from 'react'
import { GeoJSON, Marker, Pane, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import { BANGLADESH_BOUNDS, getBoundary, getLocalPlaces, getLocations } from '../../api/locations.js'

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services'
const STREETS_URL = import.meta.env.VITE_MAP_TILE_URL ?? `${ESRI}/World_Street_Map/MapServer/tile/{z}/{y}/{x}`
const STREETS_ATTRIBUTION =
  import.meta.env.VITE_MAP_TILE_ATTRIBUTION ??
  'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Sources: Esri, HERE, Garmin, USGS, &copy; OpenStreetMap contributors'
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const SATELLITE_ATTRIBUTION = 'Imagery &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Sources: Esri, Maxar, Earthstar Geographics'
const PLACES_ATTRIBUTION =
  'Place names: <a href="https://www.geoboundaries.org/">geoBoundaries</a> (BBS, OCHA), &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

// Props every map in the app shares: kept to Bangladesh, from the whole country (zoom 6) down to a building.
export const MAP_LIMITS = { maxBounds: BANGLADESH_BOUNDS, maxBoundsViscosity: 1, minZoom: 6, maxZoom: 20 }

export const MAP_STYLES = [
  ['streets', 'Map'],
  ['detailed', 'Detailed'],
  ['satellite', 'Satellite'],
]

// The base map. "streets" (Esri) has English road names; "detailed" (OpenStreetMap) has far more roads, shops and
// landmarks, mostly named in Bengali; "satellite" shows rooftops, for pinning the exact building.
export function BaseTiles({ style = 'streets' }) {
  if (style === 'satellite') {
    return (
      <>
        <TileLayer key="imagery" url={`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`} attribution={SATELLITE_ATTRIBUTION} maxNativeZoom={19} maxZoom={20} />
        <TileLayer key="roads" url={`${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}`} maxNativeZoom={19} maxZoom={20} />
      </>
    )
  }
  if (style === 'detailed') {
    return <TileLayer key="osm" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" attribution={OSM_ATTRIBUTION} maxNativeZoom={19} maxZoom={20} />
  }
  return <TileLayer key="streets" url={STREETS_URL} attribution={STREETS_ATTRIBUTION} maxNativeZoom={18} maxZoom={20} />
}

// Map / Detailed / Satellite, like a maps app. Sits over the map's top-right corner.
export function MapStyleSwitch({ value, onChange, className = 'right-3 top-3' }) {
  return (
    <div role="group" aria-label="Map style" className={`absolute z-[500] grid grid-cols-3 gap-0.5 rounded-md bg-sheet/95 p-1 shadow-sm ${className}`}>
      {MAP_STYLES.map(([key, label]) => (
        <button
          key={key}
          type="button"
          aria-pressed={value === key}
          onClick={() => onChange(key)}
          className={`rounded px-2 py-1 text-xs font-semibold ${value === key ? 'bg-ink text-white' : 'text-ink-soft hover:text-ink'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

const escapeHtml = (text) => text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`)
const labelIcons = new Map()
function labelIcon({ key, level, name }) {
  if (!labelIcons.has(key)) {
    labelIcons.set(
      key,
      L.divIcon({ className: '', iconSize: [0, 0], html: `<span class="place-label place-label--${level}">${escapeHtml(name)}</span>` }),
    )
  }
  return labelIcons.get(key)
}

// Which places are named at a zoom level: divisions for the country, districts for a region, upazilas and thanas
// from the city scale down to the street.
function levelAt(zoom) {
  if (zoom <= 7) return 'division'
  if (zoom <= 9) return 'district'
  if (zoom <= 16) return 'upazila'
  return null
}

// The smallest local places named at a zoom level (the `rank` of getLocalPlaces): towns from zoom 10, unions and
// suburbs from 11 (where a chosen upazila is framed), neighbourhoods and villages from 12, hamlets from 14.
function localRankAt(zoom) {
  if (zoom >= 14) return 4
  if (zoom >= 12) return 3
  if (zoom >= 11) return 2
  return zoom >= 10 ? 1 : 0
}

// The label fonts in index.css, to measure how much room a name takes.
const LABEL_FONTS = { upazila: '600 11.5px "Public Sans"', town: '700 12px "Public Sans"', local: '500 11px "Public Sans"' }
const LABEL_HEIGHT = 15
const LABEL_GAP = 4
let measurer
const labelWidths = new Map()
function labelWidth(name, level) {
  const key = `${level}|${name}`
  if (!labelWidths.has(key)) {
    measurer ??= document.createElement('canvas').getContext('2d')
    measurer.font = LABEL_FONTS[level] ?? LABEL_FONTS.upazila
    labelWidths.set(key, measurer.measureText(name).width)
  }
  return labelWidths.get(key)
}

// The part of the screen a label covers (labels are centred on their point), with a small gap around it.
function labelBox(map, { position, name, level }) {
  const { x, y } = map.latLngToContainerPoint(position)
  const halfWidth = labelWidth(name, level) / 2 + LABEL_GAP
  const halfHeight = LABEL_HEIGHT / 2 + LABEL_GAP
  return [x - halfWidth, y - halfHeight, x + halfWidth, y + halfHeight]
}
const overlaps = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]

// English names drawn over any base map, which name much of Bangladesh sparsely or in Bengali: every division,
// district and upazila/thana, then towns, unions, neighbourhoods and villages as the map zooms in. Only the places in
// view are drawn, under the listing pins.
export function PlaceLabels() {
  const map = useMap()
  const [units, setUnits] = useState([])
  const [localPlaces, setLocalPlaces] = useState([])
  const [view, setView] = useState(() => ({ zoom: map.getZoom(), bounds: map.getBounds() }))
  useEffect(() => {
    getLocations().then(setUnits, () => setUnits([]))
  }, [])
  useMapEvents({ moveend: () => setView({ zoom: map.getZoom(), bounds: map.getBounds() }) })

  const level = levelAt(view.zoom)
  const localRank = localRankAt(view.zoom)
  const wantsLocal = localRank > 0
  useEffect(() => {
    if (wantsLocal) getLocalPlaces().then(setLocalPlaces, () => {})
  }, [wantsLocal])

  const visible = useMemo(() => {
    const area = view.bounds.pad(0.15)
    const labels = units
      .filter((unit) => unit.level === level && area.contains([unit.center[1], unit.center[0]]))
      .map((unit) => ({ key: unit.id, level: unit.level, name: unit.name, position: [unit.center[1], unit.center[0]] }))
    // Local names fill the room the upazilas leave: bigger places first (the rows come sorted by rank), and none
    // drawn over another label.
    const taken = labels.map((label) => labelBox(map, label))
    for (const [name, lng, lat, rank] of localPlaces) {
      if (rank > localRank) break
      if (!area.contains([lat, lng])) continue
      const label = { key: `${name}@${lng},${lat}`, level: rank === 1 ? 'town' : 'local', name, position: [lat, lng] }
      const box = labelBox(map, label)
      if (taken.some((other) => overlaps(box, other))) continue
      taken.push(box)
      labels.push(label)
    }
    return labels
  }, [map, units, localPlaces, level, localRank, view])

  useEffect(() => {
    map.attributionControl?.addAttribution(PLACES_ATTRIBUTION)
    return () => map.attributionControl?.removeAttribution(PLACES_ATTRIBUTION)
  }, [map])

  return (
    <Pane name="place-labels" style={{ zIndex: 450, pointerEvents: 'none' }}>
      {visible.map((label) => (
        <Marker key={label.key} position={label.position} icon={labelIcon(label)} interactive={false} keyboard={false} pane="place-labels" />
      ))}
    </Pane>
  )
}

// The outline of a division, district or upazila (by place id). With `fit`, the map frames it.
export function RegionOutline({ id, fit = false }) {
  const map = useMap()
  const [shape, setShape] = useState(null)
  useEffect(() => {
    let live = true
    setShape(null)
    if (!id) return undefined
    getBoundary(id).then(
      (feature) => {
        if (!live) return
        setShape(feature)
        if (fit) map.fitBounds(L.geoJSON(feature).getBounds(), { padding: [24, 24] })
      },
      () => {},
    )
    return () => {
      live = false
    }
  }, [id, fit, map])
  if (!shape) return null
  return (
    <GeoJSON
      key={id}
      data={shape}
      interactive={false}
      style={{ color: '#429a4a', weight: 2.5, dashArray: '6 4', fillColor: '#429a4a', fillOpacity: 0.05 }}
    />
  )
}
