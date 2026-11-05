import { ArrowRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { getLeases } from '../../api/operations.js'
import { CATEGORIES, formatDay, formatTaka } from '../../constants/rentals.js'
import { Alert, EmptyState, Stamp } from '../ui.jsx'
import { Spinner } from './RentalPanels.jsx'

export default function LeasesPanel() {
  const [leases, setLeases] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getLeases().then(setLeases, (err) => setError(getErrorMessage(err)))
  }, [])

  if (!leases) return error ? <Alert>{error}</Alert> : <Spinner />
  if (leases.length === 0) {
    return (
      <EmptyState title="No leases yet.">
        A lease starts when the tenant scans the owner's handshake QR. Bills, repairs and move-out all happen here after that.
      </EmptyState>
    )
  }
  return (
    <ul className="space-y-3">
      {leases.map((lease) => {
        const tenantView = lease.viewer_side === 'TENANT'
        const state =
          lease.status === 'ENDED'
            ? ['Ended', 'border-ink-soft text-ink-soft']
            : lease.move_out
              ? [`Moving out ${formatDay(lease.move_out.move_out_date)}`, 'border-brass text-[#8a6410]']
              : ['Active', 'border-gate text-gate']
        return (
          <li key={lease.id}>
            <Link to={`/leases/${lease.id}`} className="group flex flex-wrap items-center gap-4 rounded-xl border border-rule bg-sheet p-5 hover:border-ink-soft">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
                  {CATEGORIES[lease.listing.category].label} · {lease.listing.area} · {tenantView ? 'you rent' : 'you let'}
                </p>
                <p className="mt-0.5 font-semibold group-hover:underline">{lease.listing.title}</p>
                <p className="text-sm text-ink-soft">
                  {tenantView ? `Owner ${lease.owner.full_name}` : `Tenant ${lease.tenant.full_name}`} · {formatTaka(lease.agreed_rent)}/month · since{' '}
                  {formatDay(lease.move_in_date)}
                </p>
              </div>
              <Stamp tone={state[1]}>{state[0]}</Stamp>
              <ArrowRight className="size-5 text-ink-soft group-hover:text-ink" aria-hidden="true" />
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
