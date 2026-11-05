import { ChevronRight, Crosshair, MapPinned } from 'lucide-react'
import { Fragment, useEffect, useId, useState } from 'react'
import { districtsOf, divisionsOf, getLocationCounts, getLocations, placeId, upazilasOf } from '../../api/locations.js'
import { getAreas } from '../../api/rentals.js'
import { QUICK_AREAS } from '../../constants/rentals.js'
import PlaceSearch from './PlaceSearch.jsx'
import { RADIUS, hasCenter, placeTarget, regionLabel, targetRegion } from './target.js'

const COUNT_KEY = { rent: 'rentals', sale: 'sales' }
const MAX_REGION_AREAS = 12
const sameName = (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase()

// A quick-pick area as a key tag: green eyelet, name and how many listings it has.
function AreaPill({ name, count, selected, onSelect }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`inline-flex shrink-0 items-center gap-2 rounded-md border-2 px-3 py-1.5 text-sm font-semibold transition-colors ${
        selected ? 'border-gate bg-gate text-white' : 'border-transparent bg-sheet text-ink hover:border-leaf'
      }`}
    >
      <span aria-hidden="true" className={`size-2 shrink-0 rounded-full border-[1.5px] ${selected ? 'border-white bg-gate' : 'border-leaf bg-plaster'}`} />
      {name}
      {count !== undefined && (
        <span className={`font-mono text-xs font-medium ${selected ? 'text-white/80' : count ? 'text-gate-dark' : 'text-ink-soft/60'}`}>{count}</span>
      )}
    </button>
  )
}

// One step of Division > District > Upazila / thana: the places at that level, each with how many listings it has.
function RegionSelect({ label, anyLabel, value, places, counts, disabled, onChange, className = '' }) {
  const id = useId()
  const selected = value ? places.find((place) => sameName(place.name, value)) : null
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <label htmlFor={id} className="text-[11px] font-semibold uppercase tracking-wider text-white/60">
        {label}
      </label>
      <select
        id={id}
        value={selected?.name ?? ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value || null)}
        className="h-9 w-full min-w-0 rounded-md border border-white/25 bg-ink px-2 text-sm text-white focus:border-leaf focus:outline-none disabled:opacity-40 md:w-48"
      >
        <option value="">{anyLabel}</option>
        {places.map((place) => (
          <option key={place.id} value={place.name}>
            {place.name}
            {counts[place.id] ? ` · ${counts[place.id]}` : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

// Before an area is chosen: what to do, instead of a feed of random listings.
export function ChooseAreaPrompt({ what }) {
  return (
    <div className="rounded-xl border border-dashed border-rule p-6 text-center">
      <MapPinned className="mx-auto size-8 text-leaf" aria-hidden="true" />
      <p className="mt-3 font-semibold">Choose where you're shifting first</p>
      <p className="mt-1 text-sm text-ink-soft">
        Pick a division, district and upazila or thana above, tap an area, search a place by name, or turn on “Pick
        shifting spot on map” and click the map. You'll only see {what} there.
      </p>
    </div>
  )
}

export function PickingHint() {
  return (
    <p className="pointer-events-none absolute left-1/2 top-3 z-[500] inline-flex w-max max-w-[calc(100%-1.5rem)] -translate-x-1/2 items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-sm text-white shadow">
      <Crosshair className="size-4 shrink-0 text-leaf" aria-hidden="true" />
      Click the map where you're shifting to
    </p>
  )
}

// "Where are you planning to shift?": the bar on top of the rent and buy feeds. Nothing is listed until the searcher
// narrows Bangladesh down (division > district > upazila/thana > area), picks a quick area, searches a place by name,
// or turns on map picking and clicks a spot (with a 1-5 km radius). `shifting` comes from useShiftingTarget.
export default function ShiftingBar({ mode, areas, landmarks, shifting }) {
  const id = useId()
  const { target, picking, setPicking, radius, setRadius, select } = shifting
  const [places, setPlaces] = useState([])
  const [placeCounts, setPlaceCounts] = useState({})
  const [regionAreas, setRegionAreas] = useState({ key: null, items: [] })
  const countKey = COUNT_KEY[mode]
  const { division, district, upazila } = targetRegion(target)
  const regionKey = division ? placeId(division, district, upazila) : null

  useEffect(() => {
    getLocations().then(setPlaces, () => setPlaces([]))
  }, [])
  useEffect(() => {
    getLocationCounts(mode).then(setPlaceCounts, () => setPlaceCounts({}))
  }, [mode])
  // The area names listed inside the chosen division / district / upazila, for the last step.
  useEffect(() => {
    if (!regionKey) return undefined
    let live = true
    const loaded = (items) => live && setRegionAreas({ key: regionKey, items })
    getAreas({ division, district, upazila }).then(loaded, () => loaded([]))
    return () => {
      live = false
    }
  }, [regionKey, division, district, upazila])

  // A searched place, area or campus becomes the target; map picking switches off, the target is set.
  const choosePlace = (place) => {
    setPicking(false)
    select(placeTarget(place, radius))
  }
  // Choosing a level clears the levels under it; "All of Bangladesh" clears the search.
  const chooseRegion = (region) => {
    setPicking(false)
    select(region.division ? { kind: 'region', district: null, upazila: null, ...region } : null)
  }

  const region = { division, district, upazila }
  const counts = new Map(areas.map((area) => [area.name.toLowerCase(), area[countKey]]))
  const pills = regionKey
    ? (regionAreas.key === regionKey ? regionAreas.items : [])
        .filter((area) => area[countKey] > 0)
        .sort((a, b) => b[countKey] - a[countKey] || a.name.localeCompare(b.name))
        .slice(0, MAX_REGION_AREAS)
        .map((area) => ({ name: area.name, count: area[countKey] }))
    : QUICK_AREAS.map((name) => ({ name, count: counts.get(name.toLowerCase()) }))
  const regionAreasLoaded = regionAreas.key === regionKey
  const searchNear = places.find((place) => place.id === regionKey)?.bbox ?? null
  const showRadius = picking || hasCenter(target)

  const steps = [
    {
      label: 'Division',
      anyLabel: 'All of Bangladesh',
      value: division,
      places: divisionsOf(places),
      onChange: (name) => chooseRegion({ division: name }),
    },
    {
      label: 'District',
      anyLabel: division ? `All of ${division} division` : 'Choose a division first',
      value: district,
      places: division ? districtsOf(places, division) : [],
      onChange: (name) => chooseRegion({ division, district: name }),
    },
    {
      label: 'Upazila / thana',
      anyLabel: district ? `All of ${district} district` : 'Choose a district first',
      value: upazila,
      places: district ? upazilasOf(places, division, district) : [],
      onChange: (name) => chooseRegion({ division, district, upazila: name }),
    },
  ]

  return (
    <section aria-labelledby={`${id}-heading`} className="bg-ink px-4 pb-3 pt-4 text-white sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <h1 id={`${id}-heading`} className="font-display text-2xl font-extrabold uppercase leading-none tracking-wide sm:text-3xl">
          Where are you planning to shift?
        </h1>
        <PlaceSearch
          areas={areas}
          landmarks={landmarks}
          onPick={choosePlace}
          near={searchNear}
          placeholder="Search: Rajshahi, Paba, Dhanmondi 27, NSU…"
          dark
        />
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-x-5 gap-y-3">
        {/* Phones: division and district side by side, the upazila under them. Tablets: three columns. Wide: a row. */}
        <div role="group" aria-label="Narrow down by place" className="grid w-full grid-cols-2 items-end gap-2 sm:grid-cols-3 md:flex md:w-auto">
          {steps.map((step, index) => (
            <Fragment key={step.label}>
              {index > 0 && <ChevronRight className="mb-2.5 hidden size-4 shrink-0 text-leaf md:block" aria-hidden="true" />}
              <RegionSelect
                {...step}
                counts={placeCounts}
                disabled={index > 0 && step.places.length === 0}
                className={index === 2 ? 'col-span-2 sm:col-span-1' : ''}
              />
            </Fragment>
          ))}
        </div>

        <button
          type="button"
          role="switch"
          aria-checked={picking}
          onClick={() => setPicking(!picking)}
          className="inline-flex h-9 items-center gap-2.5 text-sm font-semibold"
        >
          <span aria-hidden="true" className={`relative h-5 w-9 rounded-full transition-colors ${picking ? 'bg-leaf' : 'bg-white/25'}`}>
            <span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-[left] ${picking ? 'left-[1.125rem]' : 'left-0.5'}`} />
          </span>
          <Crosshair className="size-4 text-leaf" aria-hidden="true" />
          Pick shifting spot on map
        </button>
        {showRadius && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <label className="flex h-9 items-center gap-2 text-sm">
              <span className="text-white/70">Within</span>
              <input
                type="range"
                min={RADIUS.min}
                max={RADIUS.max}
                step={RADIUS.step}
                value={radius}
                onChange={(event) => setRadius(Number(event.target.value))}
                className="w-32 accent-[var(--color-leaf)]"
              />
              <output className="w-12 font-mono">{radius} km</output>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-white/70">or near</span>
              <select
                value={target?.kind === 'landmark' ? target.id : ''}
                onChange={(event) => event.target.value && select({ kind: 'landmark', id: event.target.value, radius })}
                className="h-8 max-w-56 rounded-md border border-white/25 bg-ink px-2 text-sm text-white"
              >
                <option value="">a campus or office</option>
                {['UNIVERSITY', 'OFFICE_HUB'].map((kind) => (
                  <optgroup key={kind} label={kind === 'UNIVERSITY' ? 'Universities' : 'Office hubs'}>
                    {landmarks
                      .filter((item) => item.kind === kind)
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </label>
          </div>
        )}
      </div>

      {/* The label lines up with the first row of pills when they wrap. */}
      <div className="mt-3 flex items-center gap-3 sm:items-start">
        <p id={`${id}-areas`} className="hidden shrink-0 text-[11px] font-semibold uppercase tracking-wider text-white/60 sm:mt-2.5 sm:block">
          {regionKey ? `Areas in ${regionLabel(region)}` : 'Popular in Dhaka'}
        </p>
        {pills.length > 0 ? (
          <ul aria-labelledby={`${id}-areas`} className="-mx-4 flex min-w-0 gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0">
            {pills.map(({ name, count }) => {
              const selected = target?.kind === 'area' && sameName(target.name, name)
              return (
                <li key={name} className="shrink-0">
                  <AreaPill
                    name={name}
                    count={count}
                    selected={selected}
                    onSelect={() => {
                      setPicking(false)
                      // Tapping the chosen area again goes back to the whole division / district / upazila.
                      if (selected) select(regionKey ? { kind: 'region', ...region } : null)
                      else select({ kind: 'area', name, ...region })
                    }}
                  />
                </li>
              )
            })}
          </ul>
        ) : (
          regionAreasLoaded && (
            <p className="text-sm text-white/70 sm:mt-2">
              Nothing listed in {regionLabel(region)} yet. Try a neighbouring {upazila ? 'upazila' : district ? 'district' : 'division'}, or
              search a place by name.
            </p>
          )
        )}
      </div>
    </section>
  )
}
