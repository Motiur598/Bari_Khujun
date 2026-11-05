// Tailwind needs complete class names, so each category spells out its own colour classes.
export const CATEGORIES = {
  FAMILY_FLAT: {
    label: 'Family flat',
    short: 'Family',
    pin: '#357a43',
    badge: 'bg-tag-family text-white',
    edge: 'border-l-tag-family',
  },
  BACHELOR_FLAT: {
    label: 'Bachelor flat',
    short: 'Bachelor',
    pin: '#2f6fb5',
    badge: 'bg-tag-bachelor text-white',
    edge: 'border-l-tag-bachelor',
  },
  BACHELOR_SEAT: {
    label: 'Bachelor seat',
    short: 'Seat',
    pin: '#6b4fa0',
    badge: 'bg-tag-seat text-white',
    edge: 'border-l-tag-seat',
  },
}

export const GUEST_POLICIES = {
  NOT_ALLOWED: 'No guests',
  DAYTIME_ONLY: 'Daytime guests only',
  ALLOWED: 'Guests allowed',
}

export const METER_TYPES = {
  PREPAID: 'Prepaid meter',
  POSTPAID: 'Postpaid meter',
}

export const OCCUPATIONS = {
  STUDENT: 'Student',
  PROFESSIONAL: 'Professional',
}

export const HABITS = {
  EARLY_RISER: 'Early riser',
  NIGHT_OWL: 'Night owl',
  NON_SMOKER: 'Non-smoker',
  SMOKER: 'Smoker',
  QUIET: 'Quiet',
  SOCIAL: 'Social',
  TIDY: 'Tidy',
  COOKS: 'Cooks',
  WORKS_FROM_HOME: 'Works from home',
}

export const DHAKA_CENTER = [23.8103, 90.4125]

export const MAX_COMPARE = 4

const takaFormat = new Intl.NumberFormat('en-IN')

export function formatTaka(amount) {
  return `৳${takaFormat.format(amount)}`
}

// Compact form for map pins: 4400 -> "4.4k", 120000 -> "1.2L" (lakh), 26000000 -> "2.6Cr" (crore).
export function shortTaka(amount) {
  if (amount >= 10000000) return `৳${+(amount / 10000000).toFixed(2)}Cr`
  if (amount >= 100000) return `৳${+(amount / 100000).toFixed(1)}L`
  if (amount >= 1000) return `৳${+(amount / 1000).toFixed(1)}k`
  return `৳${amount}`
}

// "2026-11-01" is a calendar day, so parse it as local midnight rather than UTC.
export function formatDay(isoDate) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(`${isoDate}T00:00`))
}

export function floorLabel(level) {
  if (level === 0) return 'Ground floor'
  const suffix = level % 100 >= 11 && level % 100 <= 13 ? 'th' : { 1: 'st', 2: 'nd', 3: 'rd' }[level % 10] ?? 'th'
  return `${level}${suffix} floor`
}

// "23:00" -> "11 PM", "22:30" -> "10:30 PM"
export function clockLabel(time) {
  const [hours, minutes] = time.split(':').map(Number)
  const suffix = hours >= 12 ? 'PM' : 'AM'
  const hour12 = hours % 12 === 0 ? 12 : hours % 12
  return minutes ? `${hour12}:${String(minutes).padStart(2, '0')} ${suffix}` : `${hour12} ${suffix}`
}

export function gateLabel(time) {
  return time ? `Gate closes ${clockLabel(time)}` : 'Gate open all night'
}

// A bachelor tenant's sublet lets one seat or rooms, each priced on its own; its search price is the cheapest free
// one, so a single room shows per room and anything else per seat.
export function rentUnit(listing) {
  if (listing.sublet) return defaultUnit(listing)?.whole_room ? '/room/month' : '/seat/month'
  return listing.category === 'BACHELOR_SEAT' ? '/seat/month' : '/month'
}

// "from " when a sublet's rooms are priced differently.
export function rentPrefix(listing) {
  return new Set((listing.sublet?.rooms ?? []).map((room) => room.seat_rent)).size > 1 ? 'from ' : ''
}

// Mirrors compute_seat_split in backend/app/schemas/rental.py, for the live preview while editing.
export function seatSplit(pricing, totalSeats) {
  const share = (amount) => Math.ceil((Number(amount) || 0) / totalSeats)
  const parts = {
    per_seat_rent: share(pricing.base_rent),
    per_seat_service_charge: share(pricing.service_charge),
    per_seat_utility: share(pricing.utility_estimate),
    per_seat_maid: share(pricing.maid_estimate),
  }
  return { ...parts, per_seat_total: Object.values(parts).reduce((sum, value) => sum + value, 0) }
}

// ---------------------------------------------------------------- what a tenant can ask for on a sublet
// A sublet's `rooms` are its one seat (SEAT), single rooms (SINGLE: taken whole) and shared rooms (SHARED: one seat,
// or the whole room while every seat is free). A "unit" is one of those choices, as the API takes and returns it.

export function makeUnit(room, wholeRoom = false) {
  const whole = room.room_type === 'SINGLE' || (room.room_type === 'SHARED' && wholeRoom)
  return { room_id: room.id, room_name: room.name, seats: whole ? room.seats : 1, whole_room: whole }
}

// The cheapest free seat or room, which is what the sublet's search price shows.
export function defaultUnit(listing) {
  const rooms = listing.sublet?.rooms ?? []
  const free = rooms.filter((room) => room.available_seats > 0)
  const cheapest = [...(free.length ? free : rooms)].sort((a, b) => a.seat_rent - b.seat_rent)[0]
  return cheapest ? makeUnit(cheapest) : null
}

// Every seat or room a tenant can ask for right now.
export function unitChoices(listing) {
  return (listing.sublet?.rooms ?? []).flatMap((room) => {
    if (room.available_seats === 0) return []
    if (room.room_type !== 'SHARED') return [makeUnit(room)]
    return room.available_seats === room.seats ? [makeUnit(room), makeUnit(room, true)] : [makeUnit(room)]
  })
}

export const unitKey = (unit) => (unit ? `${unit.room_id}:${unit.whole_room ? 'room' : 'seat'}` : '')

// Matches unit_label in backend/app/schemas/booking.py.
export function unitLabel(unit) {
  if (!unit) return ''
  if (!unit.whole_room) return `1 seat in ${unit.room_name}`
  return unit.seats > 1 ? `Whole room: ${unit.room_name} (${unit.seats} seats)` : `Single room: ${unit.room_name}`
}

// What one tenant pays per month, broken down. Seats use their split; flats use the whole-flat figures. On a sublet,
// the given seat or room (by default the cheapest free one), whose charges are per seat.
export function tenantCosts(listing, unit = defaultUnit(listing)) {
  const { pricing, seats } = listing
  const room = unit && listing.sublet?.rooms.find((item) => item.id === unit.room_id)
  const costs = room
    ? {
        rent: room.seat_rent * unit.seats,
        service: room.service_charge * unit.seats,
        utility: room.utility_estimate * unit.seats,
        maid: room.maid_estimate * unit.seats,
      }
    : seats?.split
      ? {
          rent: seats.split.per_seat_rent,
          service: seats.split.per_seat_service_charge,
          utility: seats.split.per_seat_utility,
          maid: seats.split.per_seat_maid,
        }
      : { rent: pricing.base_rent, service: pricing.service_charge, utility: pricing.utility_estimate, maid: pricing.maid_estimate }
  return {
    ...costs,
    deposit: costs.rent * pricing.deposit_months,
    total: costs.rent + costs.service + costs.utility + costs.maid,
  }
}

export function haversineKm([lat1, lng1], [lat2, lng2]) {
  const rad = (deg) => (deg * Math.PI) / 180
  const a =
    Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2
  return 6371 * 2 * Math.asin(Math.sqrt(a))
}

// Rough door-to-door estimate from straight-line distance: Dhaka roads add about 30%,
// and traffic keeps rickshaws near 8 km/h and buses or CNGs near 12 km/h.
export function commuteHint(km) {
  const road = km * 1.3
  if (road <= 1.5) return `~${Math.max(1, Math.round((road / 4.5) * 60))} min walk`
  if (road <= 4) return `~${Math.round((road / 8) * 60)} min by rickshaw`
  return `~${Math.round((road / 12) * 60)} min by bus or CNG`
}

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// The API's area rule: whole words, any case and spacing, so "Mirpur" matches "Mirpur 10" but "Mirpur 1" doesn't.
export function wholeWords(name) {
  return new RegExp(`(?<!\\w)${name.trim().split(/\s+/).map(escapeRegExp).join('\\s+')}(?!\\w)`, 'i')
}

// The full address, adding the sub-area, area or city when `formatted_address` doesn't already name it.
export function formatAddress({ formatted_address, sub_area, area_name, city, district }) {
  return [sub_area, area_name, city, district]
    .filter(Boolean)
    .reduce((text, part) => (wholeWords(part).test(text) ? text : `${text}, ${part}`), formatted_address)
}

// "Sector 7, Uttara", or just "Gulshan 1" when the sub-area already names its area. Outside Dhaka the district follows
// ("Binodpur, Rajshahi"), so same-named places in different towns can be told apart.
export function areaLabel({ area_name, sub_area, district }) {
  const parts = sub_area && !wholeWords(area_name).test(sub_area) ? [sub_area, area_name] : [sub_area || area_name]
  if (district && district !== 'Dhaka' && !parts.some((part) => wholeWords(district).test(part))) parts.push(district)
  return parts.join(', ')
}

// The quick picks on the "Where are you planning to shift?" bar, in this order.
export const QUICK_AREAS = ['Uttara', 'Mirpur', 'Dhanmondi', 'Bashundhara R/A', 'Mohammadpur', 'Banani', 'Badda', 'Khilgaon', 'Motijheel']
