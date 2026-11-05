import { Phone, Video, Footprints } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { cancelVisit, getMyVisits } from '../../api/marketplace.js'
import { VISIT_MODES, formatTime } from '../../constants/marketplace.js'
import { VISIT_CARD_STATUS } from '../../constants/realtime.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { Alert, EmptyState, Stamp } from '../ui.jsx'
import { Spinner } from './RentalPanels.jsx'

const dayHeading = (iso) =>
  new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Dhaka' }).format(new Date(iso))

export default function VisitsPanel() {
  const { user } = useAuth()
  const [visits, setVisits] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getMyVisits().then(setVisits, (err) => setError(getErrorMessage(err)))
  }, [])

  async function cancel(visit) {
    if (!window.confirm('Cancel this visit? The time becomes free for others.')) return
    try {
      const next = await cancelVisit(visit.id)
      setVisits((list) => list.map((v) => (v.id === next.id ? next : v)))
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  if (!visits) return error ? <Alert>{error}</Alert> : <Spinner />
  if (visits.length === 0) {
    return <EmptyState title="No upcoming visits.">Book a 30-minute visit or video walkthrough from any listing page.</EmptyState>
  }

  const days = Object.entries(Object.groupBy(visits, (visit) => dayHeading(visit.starts_at)))
  return (
    <div className="space-y-6">
      <Alert>{error}</Alert>
      {days.map(([day, list]) => (
        <section key={day}>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-soft">{day}</h3>
          <ul className="mt-2 space-y-2">
            {list.map((visit) => {
              const hosting = visit.host.id === user.id
              const other = hosting ? visit.visitor : visit.host
              const Icon = visit.mode === 'VIDEO' ? Video : Footprints
              return (
                <li key={visit.id} className={`flex flex-wrap items-center gap-4 rounded-lg border border-rule bg-sheet p-4 ${visit.status === 'CANCELLED' ? 'opacity-60' : ''}`}>
                  <p className="w-20 shrink-0 font-mono text-sm font-medium">{formatTime(visit.starts_at)}</p>
                  <div className="min-w-0 flex-1">
                    <Link to={`/${visit.listing_mode === 'SALE' ? 'sale' : 'rentals'}/${visit.listing_id}`} className="font-semibold hover:underline">
                      {visit.listing_title}
                    </Link>
                    <p className="flex flex-wrap items-center gap-x-3 text-sm text-ink-soft">
                      <span className="inline-flex items-center gap-1">
                        <Icon className="size-3.5" aria-hidden="true" /> {VISIT_MODES[visit.mode]}
                      </span>
                      <span>
                        {hosting ? 'Visitor' : 'Host'}: {other.full_name}
                      </span>
                      <a href={`tel:${other.phone}`} className="inline-flex items-center gap-1 hover:text-ink">
                        <Phone className="size-3.5" aria-hidden="true" /> {other.phone}
                      </a>
                    </p>
                  </div>
                  {visit.status === 'CANCELLED' ? (
                    <Stamp tone="border-ink-soft text-ink-soft">
                      {visit.approval === 'DECLINED' ? 'Declined by host' : `Cancelled by ${visit.cancelled_by.toLowerCase()}`}
                    </Stamp>
                  ) : (
                    <>
                      {/* Approving, rescheduling and declining happen on the visit card in the chat. */}
                      <Stamp tone={VISIT_CARD_STATUS[visit.approval].tone}>{VISIT_CARD_STATUS[visit.approval].label}</Stamp>
                      <button type="button" onClick={() => cancel(visit)} className="text-sm font-semibold text-tag-owner hover:underline">
                        Cancel
                      </button>
                    </>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
