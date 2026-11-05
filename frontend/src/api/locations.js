import api from './client.js'

// Bangladesh's 8 divisions, 64 districts and 544 upazilas/thanas (no outlines). Loaded once and shared.
let unitsRequest
export function getLocations() {
  unitsRequest ??= api.get('/locations').then(({ data }) => data)
  unitsRequest.catch(() => (unitsRequest = undefined))
  return unitsRequest
}

// About 7,600 towns, unions, neighbourhoods and villages as [name, lng, lat, rank] rows, rank 1 (towns) to 4 (hamlets),
// for the map's labels below the upazilas. Loaded once, the first time a map is zoomed in far enough to need them.
let localPlacesRequest
export function getLocalPlaces() {
  localPlacesRequest ??= api.get('/locations/places').then(({ data }) => data.places)
  localPlacesRequest.catch(() => (localPlacesRequest = undefined))
  return localPlacesRequest
}

// Listing counts by place id ("rajshahi", "rajshahi/rajshahi", "rajshahi/rajshahi/paba") for rent or sale.
export const getLocationCounts = async (mode) => (await api.get('/locations/counts', { params: { mode } })).data

const boundaries = new Map()
export function getBoundary(id) {
  if (!boundaries.has(id)) {
    const request = api.get(`/locations/boundary/${id}`).then(({ data }) => data)
    request.catch(() => boundaries.delete(id))
    boundaries.set(id, request)
  }
  return boundaries.get(id)
}

// { division, district, upazila, id } for a point, or null outside Bangladesh.
export async function locatePoint(lat, lng) {
  try {
    return (await api.get('/locations/at', { params: { lat, lng } })).data
  } catch (err) {
    if (err.response?.status === 404) return null
    throw err
  }
}

// The same ids the API uses: "Chapai Nawabganj" -> "chapai-nawabganj".
const slug = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
export const placeId = (...names) => names.filter(Boolean).map(slug).join('/')

// Divisions, the districts of one division, the upazilas of one district.
export const divisionsOf = (units) => units.filter((unit) => unit.level === 'division')
export const districtsOf = (units, division) => units.filter((unit) => unit.level === 'district' && unit.division === division)
export const upazilasOf = (units, division, district) =>
  units.filter((unit) => unit.level === 'upazila' && unit.division === division && unit.district === district)

// Bangladesh, padded a little: maps can't be dragged far outside it.
export const BANGLADESH_BOUNDS = [
  [20.3, 87.8],
  [26.9, 93.0],
]
