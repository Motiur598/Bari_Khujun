import axios from 'axios'

export const TOKEN_KEY = 'barikhujun_token'

// Vite proxies /api to the FastAPI server in dev (see vite.config.js).
const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? '/api' })

// Sign-in and sign-up answer 401/403 for a wrong password or a banned account. Those are form errors, so these
// requests never carry a stored token and never end a session.
const PUBLIC_AUTH_PATHS = ['/auth/login', '/auth/register']

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token && !PUBLIC_AUTH_PATHS.includes(config.url)) config.headers.Authorization = `Bearer ${token}`
  return config
})

// The server marks a banned account's 403 with this code. Any other 403 is an ordinary "not allowed" error.
export const ACCOUNT_BANNED = 'ACCOUNT_BANNED'

let endSession = null

// AuthContext registers how a session ends (clear the user, go to sign-in). Returns a function that unregisters it.
export function onSessionEnd(handler) {
  endSession = handler
  return () => {
    if (endSession === handler) endSession = null
  }
}

async function errorCode({ data }) {
  // File downloads ask for a blob, so their JSON error bodies arrive as one too.
  if (data instanceof Blob && data.type.includes('json')) {
    try {
      return JSON.parse(await data.text()).code
    } catch {
      return undefined
    }
  }
  return data?.code
}

// A 401 on a request that sent a token means the session is gone (expired, signed out everywhere, or revoked).
// A 403 marked ACCOUNT_BANNED means the account was suspended. Either way the stored token is dropped at once.
api.interceptors.response.use(undefined, async (error) => {
  const { response, config } = error
  if (response && config?.headers?.Authorization) {
    const banned = response.status === 403 && (await errorCode(response)) === ACCOUNT_BANNED
    if (response.status === 401 || banned) {
      localStorage.removeItem(TOKEN_KEY)
      endSession?.(banned ? 'banned' : 'expired')
    }
  }
  throw error
})

const FIELD_LABELS = {
  full_name: 'Full name',
  email: 'Email',
  phone: 'Phone',
  password: 'Password',
  role: 'Role',
  doc_type: 'Document type',
  doc_number: 'Document number',
  file: 'File',
  title: 'Title',
  line: 'Street address',
  area: 'Area',
  coordinates: 'Map pin',
  base_rent: 'Base rent',
  floor_level: 'Floor',
  total_floors: 'Floors in building',
  bedrooms: 'Bedrooms',
  bathrooms: 'Bathrooms',
  size_sqft: 'Size',
  gate_closing_time: 'Gate closing time',
  total_seats: 'Total seats',
  available_seats: 'Free seats',
  seats: 'Seats in the room',
  seat_rent: 'Rent per seat',
  rooms: 'Rooms',
  name: 'Room name',
  institution: 'University or workplace',
  display_name: 'Flatmate name',
}

// FastAPI returns `detail` as a string, or as a list of validation errors for 422s.
export function getErrorMessage(error, fallback = 'Something went wrong. Try again.') {
  if (!error.response) return 'Cannot reach the server. Check that the API is running.'
  const { detail } = error.response.data ?? {}
  // A malformed id in the URL only comes from a mistyped or truncated link.
  if (detail === 'Invalid ID format') return "This link doesn't lead anywhere. Check that it was copied in full."
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map(({ loc, msg }) => {
        const field = loc?.at(-1)
        const text = msg.replace(/^Value error, /, '')
        return FIELD_LABELS[field] ? `${FIELD_LABELS[field]}: ${text}` : text
      })
      .join(' · ')
  }
  return fallback
}

// Authenticated file download: fetch as a blob (so the bearer token is sent), then hand it to the browser.
export async function downloadFile(url, filename) {
  const { data } = await api.get(url, { responseType: 'blob' })
  const href = URL.createObjectURL(data)
  const link = Object.assign(document.createElement('a'), { href, download: filename })
  link.click()
  setTimeout(() => URL.revokeObjectURL(href), 10_000)
}

export default api
