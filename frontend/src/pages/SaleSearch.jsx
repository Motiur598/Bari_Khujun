import { BadgeCheck, List, LoaderCircle, Map as MapIcon, SlidersHorizontal } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { placeId } from '../api/locations.js'
import { searchSales } from '../api/marketplace.js'
import { getAreas, getLandmarks } from '../api/rentals.js'
import { AmountInput, Field, ToggleChip, fieldClass } from '../components/rentals/FilterBar.jsx'
import RentalMap from '../components/rentals/RentalMap.jsx'
import { CoverPhoto } from '../components/photos/ListingPhotos.jsx'
import SaleCard from '../components/sale/SaleCard.jsx'
import ShiftingBar, { ChooseAreaPrompt, PickingHint } from '../components/search/ShiftingBar.jsx'
import { hasCenter, keepTarget, readTarget, targetApiParams, targetLabel, targetRegion } from '../components/search/target.js'
import useShiftingTarget from '../components/search/useShiftingTarget.js'
import TitleBadge from '../components/sale/TitleBadge.jsx'
import { Alert } from '../components/ui.jsx'
import { HANDOVER, PROPERTY_TYPES, SALE_PIN, formatPrice } from '../constants/marketplace.js'
import { areaLabel, formatTaka, shortTaka } from '../constants/rentals.js'
import useMediaQuery from '../hooks/useMediaQuery.js'
import useUrlFilters from '../hooks/useUrlFilters.js'

const LAKH = 100000
const FILTER_KEYS = ['min_lakh', 'max_lakh', 'beds', 'handover', 'verified']

// Prices are entered in lakh (the way they are quoted) and sent to the API in taka. Only called with a target area.
function toApiParams(params, target) {
  const api = { limit: 100, ...targetApiParams(target) }
  if (params.get('type')) api.property_type = [params.get('type')]
  if (params.get('min_lakh')) api.min_price = Number(params.get('min_lakh')) * LAKH
  if (params.get('max_lakh')) api.max_price = Number(params.get('max_lakh')) * LAKH
  if (params.get('beds')) api.min_bedrooms = params.get('beds')
  if (params.get('handover')) api.handover_status = params.get('handover')
  if (params.has('verified')) api.verified_title = true
  const sort = params.get('sort')
  if (sort && (sort !== 'distance' || hasCenter(target))) api.sort = sort
  return api
}

const salePin = (listing) => ({ color: SALE_PIN, label: shortTaka(listing.sale.asking_price) })

function SalePopup({ listing }) {
  return (
    <div className="w-56 font-sans">
      <CoverPhoto listing={listing} className="mb-2 h-28 w-full rounded" />
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-soft">
        {PROPERTY_TYPES[listing.property_type]} · {areaLabel(listing.location)}
      </p>
      <Link to={`/sale/${listing.id}`} className="mt-1 block font-semibold leading-snug !text-ink hover:underline">
        {listing.title}
      </Link>
      <p className="mt-1 font-mono text-sm">
        {formatPrice(listing.sale.asking_price)} <span className="font-sans text-xs text-ink-soft">· {formatTaka(listing.price_per_sqft)}/sq ft</span>
      </p>
      <div className="mt-2">
        <TitleBadge status={listing.title_status} compact />
      </div>
    </div>
  )
}

export default function SaleSearch() {
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
  const [expanded, setExpanded] = useState(false)
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
    // Nothing is shown until the buyer picks an area.
    if (!currentTarget) {
      setResult(null)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError('')
    searchSales(toApiParams(current, currentTarget), controller.signal)
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

  const activeCount = FILTER_KEYS.filter((key) => params.has(key)).length
  const listings = target ? (result?.items ?? []) : []
  // A searched place shows its own name ("Dhanmondi 27") rather than the API's "Dropped pin".
  const center = target && result?.center ? { ...result.center, label: target.label ?? result.center.label } : null
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
      <ShiftingBar mode="sale" areas={areas} landmarks={landmarks} shifting={shifting} />
      <div className="border-b border-rule bg-sheet">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-3 px-4 py-3 sm:px-6">
          <fieldset className="flex w-full flex-col gap-1 sm:w-auto">
            <legend className="mb-1 text-xs font-medium text-ink-soft">Buying</legend>
            <div className="grid grid-cols-3 gap-1 rounded-md border border-rule bg-plaster p-1">
              {[['', 'Any'], ...Object.entries(PROPERTY_TYPES)].map(([key, label]) => (
                <label key={key || 'any'} className="cursor-pointer">
                  <input type="radio" name="type" checked={(params.get('type') ?? '') === key} onChange={() => update({ type: key })} className="peer sr-only" />
                  <span className="flex h-7 items-center justify-center rounded px-3 text-sm font-medium text-ink-soft peer-checked:bg-white peer-checked:text-ink peer-checked:shadow-sm peer-focus-visible:outline-2 peer-focus-visible:outline-leaf">
                    {label}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="flex w-full items-center justify-between gap-2 lg:hidden">
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              aria-expanded={expanded}
              aria-controls="more-sale-filters"
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-rule bg-white px-3 text-sm font-medium"
            >
              <SlidersHorizontal className="size-4" aria-hidden="true" />
              Filters{activeCount > 0 && ` (${activeCount})`}
            </button>
            <div className="grid grid-cols-2 gap-1 rounded-md border border-rule bg-plaster p-1" role="group" aria-label="View">
              {[['list', 'List', List], ['map', 'Map', MapIcon]].map(([key, label, Icon]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={view === key}
                  onClick={() => setView(key)}
                  className={`inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-sm font-medium ${view === key ? 'bg-white text-ink shadow-sm' : 'text-ink-soft'}`}
                >
                  <Icon className="size-4" aria-hidden="true" /> {label}
                </button>
              ))}
            </div>
          </div>

          <div id="more-sale-filters" className={`${expanded ? 'flex' : 'hidden'} w-full flex-wrap items-end gap-x-4 gap-y-3 lg:flex lg:w-auto`}>
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-ink-soft">Budget (lakh ৳)</span>
              <div className="flex items-center gap-1.5">
                <AmountInput label="Minimum price in lakh" step={5} placeholder="Min" value={params.get('min_lakh')} onCommit={(v) => update({ min_lakh: v })} />
                <span className="text-ink-soft">–</span>
                <AmountInput label="Maximum price in lakh" step={5} placeholder="Max" value={params.get('max_lakh')} onCommit={(v) => update({ max_lakh: v })} />
              </div>
            </div>
            <Field label="Bedrooms">
              <select value={params.get('beds') ?? ''} onChange={(e) => update({ beds: e.target.value })} className={`${fieldClass} w-24`}>
                <option value="">Any</option>
                {[2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n}+
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Handover">
              <select value={params.get('handover') ?? ''} onChange={(e) => update({ handover: e.target.value })} className={`${fieldClass} w-44`}>
                <option value="">Ready or not</option>
                {Object.entries(HANDOVER).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <ToggleChip pressed={params.has('verified')} onChange={(on) => update({ verified: on })} icon={BadgeCheck}>
              Verified title
            </ToggleChip>
            {activeCount > 0 && (
              <button
                type="button"
                onClick={() => setParams({ ...(params.get('type') ? { type: params.get('type') } : {}), ...keepTarget(params) }, { replace: true })}
                className="h-9 px-1 text-sm font-semibold text-gate hover:underline"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex lg:min-h-0 lg:flex-1">
        <section
          aria-label="Results"
          className={`w-full lg:block lg:min-h-0 lg:w-[28rem] lg:shrink-0 lg:overflow-y-auto lg:border-r lg:border-rule xl:w-[32rem] ${view === 'map' ? 'hidden' : ''}`}
        >
          {!target ? (
            <div className="p-4 sm:p-6">
              <ChooseAreaPrompt what="the properties for sale" />
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
                        {result.total} {result.total === 1 ? 'property' : 'properties'}
                      </span>
                      <span className="text-ink-soft"> {center ? `within ${result.radius_km} km of ${center.label}` : `in ${targetLabel(target)}`}</span>
                    </>
                  )}
                </p>
                <label className="flex shrink-0 items-center gap-1.5 text-sm">
                  <span className="text-ink-soft">Sort</span>
                  <select
                    value={params.get('sort') ?? (center ? 'distance' : 'newest')}
                    onChange={(e) => update({ sort: e.target.value })}
                    className="h-8 rounded-md border border-rule bg-white px-1.5 text-sm"
                  >
                    {center && <option value="distance">Nearest</option>}
                    <option value="price_asc">Price: low to high</option>
                    <option value="price_desc">Price: high to low</option>
                    <option value="ppsf_asc">Cheapest per sq ft</option>
                    <option value="newest">Newest</option>
                  </select>
                </label>
              </div>
              <div className="space-y-3 px-4 pb-10 sm:px-6">
                {error && <Alert>{error}</Alert>}
                {!loading && result && !error && listings.length === 0 && (
                  <div className="rounded-lg border border-dashed border-rule p-6 text-center">
                    <p className="font-medium">
                      {activeCount > 0 ? 'No properties here match these filters.' : `No properties for sale ${center ? 'in this circle' : `in ${targetLabel(target)}`} yet.`}
                    </p>
                    <p className="mt-1 text-sm text-ink-soft">Try a nearby area, a wider radius or a bigger budget.</p>
                  </div>
                )}
                {listings.map((listing) => (
                  <SaleCard key={listing.id} listing={listing} center={center} active={listing.id === activeId} onHover={setActiveId} />
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
            pinOf={salePin}
            popup={SalePopup}
          />
          {picking && <PickingHint />}
        </div>
      </div>
    </div>
  )
}
