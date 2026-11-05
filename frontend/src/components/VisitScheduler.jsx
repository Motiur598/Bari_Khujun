import { LoaderCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { bookVisit, getDaySlots } from '../api/marketplace.js'
import { VISIT_MODES, formatTime } from '../constants/marketplace.js'
import { useAuth } from '../context/AuthContext.jsx'
import { Alert, Button, Segmented } from './ui.jsx'

const VISITOR_ROLES = ['BACHELOR_TENANT', 'FAMILY_TENANT', 'BUYER']
const DAYS_SHOWN = 14

// Calendar days in Dhaka, as YYYY-MM-DD, starting today.
export function upcomingDays() {
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Dhaka' })
  const [y, m, d] = today.split('-').map(Number)
  return Array.from({ length: DAYS_SHOWN }, (_, i) => new Date(Date.UTC(y, m - 1, d + i)).toISOString().slice(0, 10))
}

export const dayLabel = (iso, options) => new Intl.DateTimeFormat(undefined, { ...options, timeZone: 'UTC' }).format(new Date(`${iso}T00:00Z`))

export default function VisitScheduler({ listing }) {
  const { user } = useAuth()
  const days = useMemo(upcomingDays, [])
  const [day, setDay] = useState(days[0])
  const [slots, setSlots] = useState(null)
  const [picked, setPicked] = useState(null)
  const [mode, setMode] = useState('IN_PERSON')
  const [error, setError] = useState('')
  const [booked, setBooked] = useState(null)
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let cancelled = false
    setSlots(null)
    setPicked(null)
    getDaySlots(listing.id, day)
      .then((data) => !cancelled && setSlots(data.slots))
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [listing.id, day, reload])

  const canBook = user && VISITOR_ROLES.includes(user.role) && user.id !== listing.lister_id

  async function handleBook() {
    setError('')
    setBusy(true)
    try {
      setBooked(await bookVisit({ listing_id: listing.id, starts_at: picked, mode }))
    } catch (err) {
      setError(getErrorMessage(err))
      setReload((n) => n + 1) // someone may have just taken the slot
    } finally {
      setBusy(false)
    }
  }

  if (booked) {
    return (
      <Alert tone="success">
        Visit booked for {dayLabel(day, { weekday: 'short', day: 'numeric', month: 'short' })} at {formatTime(booked.starts_at)} (
        {VISIT_MODES[booked.mode].toLowerCase()}). It's on your{' '}
        <Link to="/dashboard" className="font-semibold underline">
          dashboard
        </Link>
        .
      </Alert>
    )
  }

  return (
    <div>
      <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-2" role="group" aria-label="Day">
        {days.map((iso) => (
          <button
            key={iso}
            type="button"
            aria-pressed={iso === day}
            onClick={() => setDay(iso)}
            className={`flex w-14 shrink-0 flex-col items-center rounded-md border py-1.5 text-xs ${
              iso === day ? 'border-ink bg-ink text-white' : 'border-rule bg-white text-ink hover:border-ink'
            }`}
          >
            <span className="uppercase tracking-wide opacity-70">{dayLabel(iso, { weekday: 'short' })}</span>
            <span className="text-base font-semibold">{dayLabel(iso, { day: 'numeric' })}</span>
            <span className="opacity-70">{dayLabel(iso, { month: 'short' })}</span>
          </button>
        ))}
      </div>

      {slots === null ? (
        <div className="grid h-24 place-items-center text-ink-soft" role="status">
          <LoaderCircle className="size-5 animate-spin" aria-label="Loading times" />
        </div>
      ) : (
        <div className="mt-2 grid grid-cols-4 gap-1.5 sm:grid-cols-6" role="group" aria-label="Time">
          {slots.map((slot) => {
            const chosen = picked === slot.starts_at
            return (
              <button
                key={slot.starts_at}
                type="button"
                disabled={!slot.available || !canBook}
                aria-pressed={chosen}
                title={slot.reason === 'TAKEN' ? 'Already booked' : slot.reason === 'YOURS' ? 'You have a visit at this time' : undefined}
                onClick={() => setPicked(slot.starts_at)}
                className={`rounded-md border px-1 py-1.5 font-mono text-xs transition-colors ${
                  chosen
                    ? 'border-gate bg-gate text-white'
                    : slot.available
                      ? 'border-rule bg-white hover:border-gate disabled:hover:border-rule'
                      : slot.reason === 'YOURS'
                        ? 'border-brass bg-brass/10 text-[#8a6410]'
                        : 'border-transparent bg-plaster text-ink-soft/50 line-through'
                }`}
              >
                {formatTime(slot.starts_at)}
              </button>
            )
          })}
        </div>
      )}

      <div className="mt-4 space-y-3">
        {canBook ? (
          <>
            <Segmented legend="How" name={`visit-mode-${listing.id}`} value={mode} options={Object.entries(VISIT_MODES)} onChange={setMode} />
            <Alert>{error}</Alert>
            <Button type="button" busy={busy} disabled={!picked} onClick={handleBook} className="w-full">
              {picked ? `Book ${formatTime(picked)}` : 'Pick a time'}
            </Button>
          </>
        ) : (
          <p className="text-sm text-ink-soft">
            {!user ? (
              <>
                <Link to="/login" className="font-semibold text-gate hover:underline">
                  Sign in
                </Link>{' '}
                as a tenant or buyer to book a 30-minute visit.
              </>
            ) : user.id === listing.lister_id ? (
              'This is your listing. Visits people book show up on your dashboard.'
            ) : (
              'Visits are booked by tenant and buyer accounts.'
            )}
          </p>
        )}
      </div>
    </div>
  )
}
