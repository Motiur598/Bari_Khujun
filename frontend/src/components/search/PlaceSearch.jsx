import { Building2, GraduationCap, LoaderCircle, Map as MapIcon, MapPin, Search } from 'lucide-react'
import { useEffect, useId, useMemo, useState } from 'react'
import { searchPlaces } from '../../api/geocode.js'
import { getLocations } from '../../api/locations.js'

const normalize = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
const MAX_KNOWN = 8

// How well a name matches what was typed: 0 exactly, 1 from the start, 2 from the start of a later word, 3 anywhere
// inside; null for no match.
function matchScore(name, q) {
  const text = normalize(name)
  if (text === q) return 0
  if (text.startsWith(q)) return 1
  if (text.includes(` ${q}`)) return 2
  return text.includes(q) ? 3 : null
}
const bestScore = (names, q) => Math.min(...names.map((name) => matchScore(name, q) ?? Infinity))

const REGION_DETAIL = {
  division: () => 'Division',
  district: (unit) => `District · ${unit.division} division`,
  upazila: (unit) => `Upazila / thana · ${unit.district} district`,
}
const LEVEL_ORDER = { division: 0, district: 1, upazila: 2 }

// Areas, campuses/offices and Bangladesh's divisions, districts and upazilas/thanas, matched as you type ("nsu",
// "mirpur", "rajshahi", older spellings like "chittagong" too). Closest matches first.
function knownPlaces(query, areas, landmarks, regions) {
  const q = normalize(query)
  if (!q) return []
  const hits = []
  for (const area of areas) {
    const score = matchScore(area.name, q)
    if (score !== null) hits.push({ score, order: 0, kind: 'area', key: `area:${area.name}`, name: area.name, detail: 'Area', lat: area.lat, lng: area.lng })
  }
  for (const item of landmarks) {
    const score = item.id === q.replace(/ /g, '-') ? 0 : bestScore([item.name, item.area], q)
    if (score === Infinity) continue
    hits.push({
      score,
      order: 1,
      kind: 'landmark',
      key: `landmark:${item.id}`,
      id: item.id,
      name: item.name,
      detail: `${item.kind === 'UNIVERSITY' ? 'University' : 'Office hub'} · ${item.area}`,
      lat: item.lat,
      lng: item.lng,
    })
  }
  for (const unit of regions) {
    const score = bestScore([unit.name, ...unit.aliases], q)
    if (score === Infinity) continue
    hits.push({
      score,
      order: 2 + LEVEL_ORDER[unit.level],
      kind: 'region',
      key: `region:${unit.id}`,
      unit,
      name: unit.name,
      detail: REGION_DETAIL[unit.level](unit),
      lat: unit.center[1],
      lng: unit.center[0],
    })
  }
  return hits.sort((a, b) => a.score - b.score || a.order - b.order).slice(0, MAX_KNOWN)
}

const ICONS = { area: MapPin, landmark: GraduationCap, place: Building2, region: MapIcon }

function Option({ place, onChoose }) {
  const Icon = ICONS[place.kind]
  return (
    <li>
      <button
        type="button"
        onClick={() => onChoose(place)}
        className="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-plaster focus-visible:bg-plaster focus-visible:outline-none"
      >
        <Icon className="mt-0.5 size-4 shrink-0 text-gate" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">{place.name}</span>
          {place.detail && <span className="block truncate text-xs text-ink-soft">{place.detail}</span>}
        </span>
      </button>
    </li>
  )
}

// Search for a place by its English name: a division, district or upazila/thana, an area, a campus or office, a road or
// a building. Known places appear as you type; pressing Search (or Enter) also looks the text up on OpenStreetMap,
// preferring places inside `near` ([west, south, east, north], e.g. the chosen district). `onPick` receives
// { kind: 'area' | 'landmark' | 'region' | 'place', name, lat, lng, id?, unit? } (`unit` is the division, district or
// upazila from /api/locations).
export default function PlaceSearch({ areas, landmarks, onPick, placeholder, near = null, dark = false }) {
  const id = useId()
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState(null)
  const [status, setStatus] = useState('')
  const [regions, setRegions] = useState([])
  useEffect(() => {
    getLocations().then(setRegions, () => setRegions([]))
  }, [])
  const known = useMemo(() => knownPlaces(text, areas, landmarks, regions), [text, areas, landmarks, regions])

  function choose(place) {
    onPick(place)
    setText('')
    setResults(null)
    setStatus('')
    setOpen(false)
  }

  async function search() {
    const query = text.trim()
    if (query.length < 2) return
    // Exactly the name of an area (or a known place): no need to ask the map.
    const exact = known.find((place) => normalize(place.name) === normalize(query))
    if (exact) return choose(exact)
    setOpen(true)
    setResults(null)
    setStatus('searching')
    try {
      const places = await searchPlaces(query, { near })
      setResults(places.map((place, index) => ({ ...place, kind: 'place', key: `place:${index}` })))
      setStatus('')
    } catch {
      setStatus("Couldn't search the map just now. Try again in a moment.")
    }
  }

  const showPanel = open && (known.length > 0 || results || status || text.trim().length >= 2)
  const inputClass = dark
    ? 'border-white/25 bg-white/10 text-white placeholder:text-white/50 focus:border-leaf'
    : 'border-rule bg-white text-ink placeholder:text-ink-soft/60 focus:border-gate'

  return (
    <div
      className="relative w-full sm:w-80"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
      }}
      onKeyDown={(event) => event.key === 'Escape' && setOpen(false)}
    >
      {/* Not a <form>: this sits inside the listing editor's form, and a nested form would submit the listing. */}
      <div role="search" className="flex gap-2">
        <label htmlFor={`${id}-q`} className="sr-only">
          Search a place
        </label>
        <input
          id={`${id}-q`}
          type="search"
          value={text}
          maxLength={120}
          autoComplete="off"
          onChange={(event) => {
            setText(event.target.value)
            setResults(null)
            setStatus('')
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              search()
            }
          }}
          placeholder={placeholder}
          className={`h-9 min-w-0 flex-1 rounded-md border px-3 text-sm focus:outline-none ${inputClass}`}
        />
        <button
          type="button"
          onClick={search}
          disabled={text.trim().length < 2}
          aria-label="Search"
          className={`inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-semibold disabled:opacity-50 ${
            dark ? 'border border-white/30 hover:border-white hover:bg-white/10' : 'bg-ink text-white hover:bg-ink/85'
          }`}
        >
          <Search className="size-4" aria-hidden="true" />
          <span className="hidden sm:inline">Search</span>
        </button>
      </div>
      {showPanel && (
        <div className="absolute left-0 right-0 top-full z-[1100] mt-1 max-h-80 overflow-y-auto rounded-md border border-rule bg-sheet py-1 text-ink shadow-lg">
          {known.length > 0 && (
            <>
              <p className="px-3 pb-1 pt-1.5 text-xs font-semibold uppercase tracking-wider text-ink-soft">Places in Bangladesh</p>
              <ul>
                {known.map((place) => (
                  <Option key={place.key} place={place} onChoose={choose} />
                ))}
              </ul>
            </>
          )}
          {status === 'searching' && (
            <p className="flex items-center gap-2 px-3 py-2 text-sm text-ink-soft">
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> Searching the map…
            </p>
          )}
          {status && status !== 'searching' && <p className="px-3 py-2 text-sm text-tag-owner">{status}</p>}
          {results &&
            (results.length > 0 ? (
              <>
                <p className="px-3 pb-1 pt-1.5 text-xs font-semibold uppercase tracking-wider text-ink-soft">On the map</p>
                <ul>
                  {results.map((place) => (
                    <Option key={place.key} place={place} onChoose={choose} />
                  ))}
                </ul>
              </>
            ) : (
              <p className="px-3 py-2 text-sm text-ink-soft">Nothing called “{text.trim()}” on the map. Try a road, area or landmark name.</p>
            ))}
          {!results && !status && text.trim().length >= 2 && (
            <p className="px-3 py-2 text-xs text-ink-soft">Press Enter to search the map for “{text.trim()}”.</p>
          )}
        </div>
      )}
    </div>
  )
}
