import { LoaderCircle } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { getErrorMessage } from '../api/client.js'
import { placeId } from '../api/locations.js'
import { getAreas, getLandmarks, searchRentals } from '../api/rentals.js'
import FilterBar, { FLOOR_RANGES } from '../components/rentals/FilterBar.jsx'
import ListingCard from '../components/rentals/ListingCard.jsx'
import RentalMap from '../components/rentals/RentalMap.jsx'
import ShiftingBar, { ChooseAreaPrompt, PickingHint } from '../components/search/ShiftingBar.jsx'
import { hasCenter, keepTarget, readTarget, targetApiParams, targetLabel, targetRegion } from '../components/search/target.js'
import useShiftingTarget from '../components/search/useShiftingTarget.js'
import { Alert } from '../components/ui.jsx'
import useMediaQuery from '../hooks/useMediaQuery.js'
import useUrlFilters from '../hooks/useUrlFilters.js'

// URL keys that count as an active filter (category has its own control and is not counted).
const FILTER_KEYS = ['min_rent', 'max_rent', 'floor', 'elevator', 'generator', 'meter_type', 'smoking_allowed']

// Translate the page's URL state into /api/rentals query params; only called once a target area is set.
function toApiParams(params, target) {
  const api = { limit: 100, ...targetApiParams(target) }
  const category = params.get('category')
  if (category) api.category = [category]

  for (const key of ['min_rent', 'max_rent', 'meter_type', 'smoking_allowed']) {
    if (params.get(key)) api[key] = params.get(key)
  }
  const sort = params.get('sort')
  if (sort && (sort !== 'distance' || hasCenter(target))) api.sort = sort

  const { min_floor, max_floor } = FLOOR_RANGES[params.get('floor')] ?? {}
  if (min_floor !== undefined) api.min_floor = min_floor
  if (max_floor !== undefined) api.max_floor = max_floor
  if (params.has('elevator')) api.elevator = true
  if (params.has('generator')) api.generator = true
  return api
}

export default function RentalSearch() {
  const { params, setParams, update } = useUrlFilters()
  const shifting = useShiftingTarget(params, update)
  const { target, picking } = shifting
  const [areas, setAreas] = useState([])
  const [landmarks, setLandmarks] = useState([])
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeId, setActiveId] = useState(null)
  const [view, setView] = useState('list')
  const isWide = useMediaQuery('(min-width: 1024px)')
  const mapBox = useRef(null)
  const query = params.toString()

  useEffect(() => {
    getAreas().then(setAreas, () => setAreas([]))
    getLandmarks().then(setLandmarks, () => setLandmarks([]))
  }, [])

  // On a phone, picking a spot needs the map in view.
  useEffect(() => {
    if (picking) setView('map')
  }, [picking])
  // On a phone the map sits under the search bars: scroll all of it into view when it is switched on.
  useEffect(() => {
    if (view === 'map' && !isWide) mapBox.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [view, isWide])

  useEffect(() => {
    const current = new URLSearchParams(query)
    const currentTarget = readTarget(current)
    // Nothing is listed until the tenant says where they're shifting.
    if (!currentTarget) {
      setResult(null)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError('')
    searchRentals(toApiParams(current, currentTarget), controller.signal)
      .then((data) => {
        setResult(data)
        setLoading(false)
      })
      .catch((err) => {
        if (err.code === 'ERR_CANCELED') return
        setError(getErrorMessage(err))
        setLoading(false)
      })
    return () => controller.abort()
  }, [query])

  const reset = () => {
    const category = params.get('category')
    setParams({ ...(category ? { category } : {}), ...keepTarget(params) }, { replace: true })
  }

  const activeCount = useMemo(() => FILTER_KEYS.filter((key) => params.has(key)).length, [params])
  const listings = target ? (result?.items ?? []) : []
  // A searched place shows its own name ("Dhanmondi 27") rather than the API's "Dropped pin".
  const center = target && result?.center ? { ...result.center, label: target.label ?? result.center.label } : null
  const sortValue = params.get('sort') ?? (center ? 'distance' : 'newest')
  const region = targetRegion(target)
  // The division / district / upazila searched is outlined; the map frames it unless there are results to frame.
  const mapRegion = region.division
    ? { id: placeId(region.division, region.district, region.upazila), fit: target.kind === 'region' || listings.length === 0 }
    : null
  const areaFocus =
    target?.kind === 'area' && !mapRegion ? areas.find((area) => area.name.toLowerCase() === target.name.toLowerCase()) : null

  return (
    // Wide screens get a fixed-height app: the results scroll beside the map. On phones the page scrolls as one.
    <div className="flex flex-col lg:h-[calc(100dvh-4rem)]">
      <ShiftingBar mode="rent" areas={areas} landmarks={landmarks} shifting={shifting} />
      <FilterBar params={params} update={update} reset={reset} activeCount={activeCount} view={view} onViewChange={setView} />

      <div className="flex lg:min-h-0 lg:flex-1">
        <section
          aria-label="Results"
          className={`w-full lg:block lg:min-h-0 lg:w-[28rem] lg:shrink-0 lg:overflow-y-auto lg:border-r lg:border-rule xl:w-[32rem] ${
            view === 'map' ? 'hidden' : ''
          }`}
        >
          {!target ? (
            <div className="p-4 sm:p-6">
              <ChooseAreaPrompt what="the flats and seats" />
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-3 px-4 pb-2 pt-4 sm:px-6">
                <p className="text-sm" aria-live="polite">
                  {loading || !result ? (
                    <span className="inline-flex items-center gap-1.5 text-ink-soft">
                      <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> Searching…
                    </span>
                  ) : (
                    <>
                      <span className="font-semibold">
                        {result.total} {result.total === 1 ? 'place' : 'places'}
                      </span>
                      <span className="text-ink-soft">
                        {' '}
                        {center ? `within ${result.radius_km} km of ${center.label}` : `in ${targetLabel(target)}`}
                      </span>
                    </>
                  )}
                </p>
                <label className="flex shrink-0 items-center gap-1.5 text-sm">
                  <span className="text-ink-soft">Sort</span>
                  <select
                    value={sortValue}
                    onChange={(event) => update({ sort: event.target.value })}
                    className="h-8 rounded-md border border-rule bg-white px-1.5 text-sm"
                  >
                    {center && <option value="distance">Nearest</option>}
                    <option value="rent_asc">Rent: low to high</option>
                    <option value="rent_desc">Rent: high to low</option>
                    <option value="newest">Newest</option>
                  </select>
                </label>
              </div>

              <div className="space-y-3 px-4 pb-28 sm:px-6">
                {error && <Alert>{error}</Alert>}
                {!loading && result && !error && listings.length === 0 && (
                  <div className="rounded-lg border border-dashed border-rule p-6 text-center">
                    <p className="font-medium">
                      {activeCount > 0
                        ? 'No places here match these filters.'
                        : `No places ${center ? 'in this circle' : `in ${targetLabel(target)}`} yet.`}
                    </p>
                    <p className="mt-1 text-sm text-ink-soft">
                      Try a nearby area or a wider radius{activeCount > 0 && ', or clear a filter'}.
                    </p>
                    {activeCount > 0 && (
                      <button type="button" onClick={reset} className="mt-3 text-sm font-semibold text-gate hover:underline">
                        Clear filters
                      </button>
                    )}
                  </div>
                )}
                {listings.map((listing) => (
                  <ListingCard
                    key={listing.id}
                    listing={listing}
                    center={center}
                    active={listing.id === activeId}
                    onHover={setActiveId}
                  />
                ))}
              </div>
            </>
          )}
        </section>

        <div ref={mapBox} className={`relative h-[70dvh] min-h-96 min-w-0 flex-1 lg:block lg:h-auto ${view === 'list' ? 'hidden' : ''}`}>
          <RentalMap
            listings={listings}
            center={center}
            radiusKm={center ? result.radius_km : null}
            activeId={activeId}
            onHover={setActiveId}
            onPick={shifting.pickPoint}
            picking={picking}
            focus={areaFocus ? [areaFocus.lat, areaFocus.lng] : null}
            region={mapRegion}
            fitKey={result}
            visible={isWide || view === 'map'}
          />
          {picking && <PickingHint />}
        </div>
      </div>
    </div>
  )
}
