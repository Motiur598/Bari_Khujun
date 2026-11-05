// The search target lives in the URL, so a search can be shared or bookmarked:
//   ?division=Rajshahi&district=Rajshahi&upazila=Paba
//                                           a division, district or upazila/thana (each needs the one above it)
//   ?area=Dhanmondi                         an area, matched by name (&division=...&district=... narrows it)
//   ?near=pin&lat=23.81&lng=90.42&radius=2  a point on the map and a radius (&place=Dhanmondi 27 when it was searched)
//   ?near=nsu&radius=2                      a campus or office (landmark id) and a radius
export const RADIUS = { min: 1, max: 5, step: 0.5, initial: 2 }
const REGION_KEYS = ['division', 'district', 'upazila']
const TARGET_KEYS = ['area', ...REGION_KEYS, 'near', 'lat', 'lng', 'radius', 'place']

const clampRadius = (km) => Math.min(RADIUS.max, Math.max(RADIUS.min, km))

// { division, district, upazila }, each null when unset or when the level above it is missing.
function readRegion(params) {
  const region = {}
  let parent = true
  for (const key of REGION_KEYS) {
    region[key] = (parent && params.get(key)?.trim()) || null
    parent = Boolean(region[key])
  }
  return region
}

export function readTarget(params) {
  const region = readRegion(params)
  const area = params.get('area')?.trim()
  if (area) return { kind: 'area', name: area, ...region }
  if (region.division) return { kind: 'region', ...region }
  const near = params.get('near')
  const radius = clampRadius(Number(params.get('radius')) || RADIUS.initial)
  if (near === 'pin') {
    const lat = Number(params.get('lat'))
    const lng = Number(params.get('lng'))
    return params.get('lat') && params.get('lng') && Number.isFinite(lat) && Number.isFinite(lng)
      ? { kind: 'point', lat, lng, radius, label: params.get('place')?.trim() || null }
      : null
  }
  return near ? { kind: 'landmark', id: near, radius } : null
}

const regionOf = (target) => Object.fromEntries(REGION_KEYS.map((key) => [key, target[key] ?? '']))

// URL changes for useUrlFilters().update: sets this target's keys and clears the rest (all of them for null).
export function targetParams(target) {
  const cleared = Object.fromEntries(TARGET_KEYS.map((key) => [key, '']))
  if (!target) return cleared
  if (target.kind === 'region') return { ...cleared, ...regionOf(target) }
  if (target.kind === 'area') return { ...cleared, ...regionOf(target), area: target.name }
  if (target.kind === 'point') {
    return { ...cleared, near: 'pin', lat: target.lat.toFixed(5), lng: target.lng.toFixed(5), radius: target.radius, place: target.label ?? '' }
  }
  return { ...cleared, near: target.id, radius: target.radius }
}

// The target's keys from the current URL, to carry over when other filters are cleared.
export const keepTarget = (params) => Object.fromEntries(TARGET_KEYS.filter((key) => params.has(key)).map((key) => [key, params.get(key)]))

export function targetApiParams(target) {
  if (target.kind === 'region' || target.kind === 'area') {
    const params = Object.fromEntries(REGION_KEYS.filter((key) => target[key]).map((key) => [key, target[key]]))
    return target.kind === 'area' ? { ...params, area_name: target.name } : params
  }
  if (target.kind === 'point') return { lat: target.lat, lng: target.lng, radius_km: target.radius }
  return { landmark: target.id, radius_km: target.radius }
}

export const hasCenter = (target) => target?.kind === 'point' || target?.kind === 'landmark'

// The division, district and upazila a target is narrowed to (all null for a point or landmark).
export const targetRegion = (target) =>
  Object.fromEntries(REGION_KEYS.map((key) => [key, target?.kind === 'region' || target?.kind === 'area' ? (target[key] ?? null) : null]))

// "Paba, Rajshahi": the most precise place in a region target, with its district when that adds anything.
export function regionLabel({ division, district, upazila }) {
  if (upazila) return upazila === district ? upazila : `${upazila}, ${district}`
  if (district) return district === division ? `${district} district` : `${district}, ${division}`
  return `${division} division`
}

// What a region or area target is called in "12 places in …": "Paba, Rajshahi", "Binodpur, Matihar", "Uttara".
export function targetLabel(target) {
  if (target.kind === 'region') return regionLabel(target)
  const within = target.upazila ?? target.district ?? target.division
  return within && within.toLowerCase() !== target.name.toLowerCase() ? `${target.name}, ${within}` : target.name
}

// A search result, or a known area, landmark or division / district / upazila, from PlaceSearch, as a target.
export function placeTarget(place, radius) {
  if (place.kind === 'area') return { kind: 'area', name: place.name }
  if (place.kind === 'region') {
    const { level, division, district, name } = place.unit
    if (level === 'division') return { kind: 'region', division: name, district: null, upazila: null }
    if (level === 'district') return { kind: 'region', division, district: name, upazila: null }
    return { kind: 'region', division, district, upazila: name }
  }
  if (place.kind === 'landmark') return { kind: 'landmark', id: place.id, radius }
  return { kind: 'point', lat: place.lat, lng: place.lng, radius, label: place.name }
}
