import { haversineKm, wholeWords } from '../constants/rentals.js'

// Place search and reverse geocoding with OpenStreetMap's Nominatim, called straight from the browser with fetch (never
// the API client, so the Bari Khujun session token is never sent to a third party). Nominatim's usage policy allows at
// most one request a second and asks for caching, so callers debounce, results are cached and requests are spaced.
// VITE_NOMINATIM_URL points at another Nominatim server (its base URL).
const NOMINATIM = (import.meta.env.VITE_NOMINATIM_URL ?? 'https://nominatim.openstreetmap.org').replace(/\/(reverse|search)\/?$/, '')
// Dhaka as [west, south, east, north]: by default search prefers places inside it, without leaving out the rest of
// Bangladesh.
const DHAKA_BOX = [90.3, 23.65, 90.55, 23.95]
const MIN_GAP_MS = 1100
const cache = new Map()
let nextSlot = 0

function waitForSlot(signal) {
  const wait = Math.max(0, nextSlot - Date.now())
  nextSlot = Date.now() + wait + MIN_GAP_MS
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, wait)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(signal.reason)
    })
  })
}

// Nominatim's `address` object for a point ({ road, suburb, quarter, city, ... }); {} where it knows nothing.
export async function reverseGeocode(lat, lng, signal) {
  const key = `${lat.toFixed(5)},${lng.toFixed(5)}`
  if (cache.has(key)) return cache.get(key)
  await waitForSlot(signal)
  const params = new URLSearchParams({ format: 'jsonv2', lat, lon: lng, zoom: 18, addressdetails: 1, 'accept-language': 'en' })
  const response = await fetch(`${NOMINATIM}/reverse?${params}`, { signal })
  if (!response.ok) throw new Error(`Address lookup failed (${response.status})`)
  const address = (await response.json()).address ?? {}
  cache.set(key, address)
  return address
}

// Places matching a name or address, in English where OpenStreetMap has an English name: [{ name, detail, lat, lng }].
// Places inside `near` ([west, south, east, north]; Dhaka by default) come first. Nominatim's policy forbids
// search-as-you-type, so this runs only when someone submits a search.
export async function searchPlaces(query, { near, signal } = {}) {
  const q = query.trim()
  const [west, south, east, north] = near ?? DHAKA_BOX
  const viewbox = [west, north, east, south].join(',')
  const key = `search:${viewbox}:${q.toLowerCase()}`
  if (cache.has(key)) return cache.get(key)
  await waitForSlot(signal)
  const params = new URLSearchParams({ format: 'jsonv2', q, countrycodes: 'bd', viewbox, limit: 6, 'accept-language': 'en' })
  const response = await fetch(`${NOMINATIM}/search?${params}`, { signal })
  if (!response.ok) throw new Error(`Place search failed (${response.status})`)
  const places = (await response.json()).map((place) => {
    const parts = place.display_name.split(', ')
    return {
      name: place.name || parts[0],
      // "Dhanmondi, Dhaka" rather than the full chain down to the division, postcode and country.
      detail: parts.slice(place.name ? 1 : 0, 4).filter((part) => !/^\d+$/.test(part) && part !== 'Bangladesh').slice(0, 2).join(', '),
      lat: Number(place.lat),
      lng: Number(place.lon),
    }
  })
  cache.set(key, places)
  return places
}

// The popular area whose circle the point is deepest inside, or null.
export function popularAreaAt([lat, lng], areas) {
  let best = null
  for (const area of areas) {
    if (!area.popular) continue
    const depth = haversineKm([lat, lng], [area.lat, area.lng]) / area.radius_km
    if (depth <= 1 && (!best || depth < best.depth)) best = { area, depth }
  }
  return best?.area ?? null
}

// { area_name, sub_area } for a pinned point. Nominatim's names for Dhaka neighbourhoods vary (parts of Dhanmondi come
// back as suburb "Lalmatia", Bashundhara as "Bashundhara Residential Area"), so inside a popular area its name wins,
// keeping owners and tenants on the same names. Elsewhere the area is Nominatim's suburb, neighbourhood or city
// district, else the village or small town, else `fallbackArea` (the upazila, for spots OpenStreetMap barely knows).
// The sub-area is the finer quarter or neighbourhood inside it ("Sector 7", "Block M").
export function areaFor(position, address, areas, fallbackArea = '') {
  const nominatimArea = (
    address.suburb ??
    address.neighbourhood ??
    address.city_district ??
    address.village ??
    address.town ??
    fallbackArea ??
    ''
  ).replace(/ Residential Area$/i, ' R/A')
  const area_name = popularAreaAt(position, areas)?.name ?? nominatimArea
  const sub_area = [address.quarter, address.neighbourhood].find((name) => name && !(area_name && wholeWords(area_name).test(name))) ?? ''
  return { area_name, sub_area }
}

// "House 12, Road 4, Sector 7, Uttara, Dhaka": the street from Nominatim, then the sub-area, area and city.
export function fullAddressFrom(address, { area_name, sub_area, city }) {
  const parts = [address.house_number && `House ${address.house_number}`, address.road, sub_area, area_name, city]
  return [...new Set(parts.filter(Boolean))].join(', ')
}
