import { ArrowLeft, Download, LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { downloadFile, getErrorMessage } from '../api/client.js'
import { leasePath } from '../api/handshake.js'
import { getLease } from '../api/operations.js'
import InvoicesSection from '../components/lease/InvoicesSection.jsx'
import MaintenanceSection from '../components/lease/MaintenanceSection.jsx'
import MoveOutSection from '../components/lease/MoveOutSection.jsx'
import PhotoLogSection from '../components/lease/PhotoLogSection.jsx'
import ReviewSection from '../components/lease/ReviewSection.jsx'
import { Alert, Stamp } from '../components/ui.jsx'
import { CATEGORIES, formatDay, formatTaka } from '../constants/rentals.js'

const TABS = [
  ['bills', 'Bills', InvoicesSection],
  ['photos', 'Move-in log', PhotoLogSection],
  ['repairs', 'Repairs', MaintenanceSection],
  ['move-out', 'Move-out', MoveOutSection],
  ['review', 'Review', ReviewSection],
]

function leaseState(lease) {
  if (lease.status === 'ENDED') return { label: 'Ended', tone: 'border-ink-soft text-ink-soft' }
  if (lease.move_out) return { label: `Moving out ${formatDay(lease.move_out.move_out_date)}`, tone: 'border-brass text-[#8a6410]' }
  return { label: 'Active lease', tone: 'border-gate text-gate' }
}

export default function LeaseWorkspace() {
  const { bookingId } = useParams()
  const [params, setParams] = useSearchParams()
  const [lease, setLease] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getLease(bookingId).then(setLease, (err) => setError(getErrorMessage(err)))
  }, [bookingId])

  if (error) {
    return (
      <div className="mx-auto w-full max-w-4xl px-4 py-12 sm:px-6">
        <Alert>{error}</Alert>
        <Link to="/dashboard" className="mt-4 inline-block text-sm font-semibold text-gate hover:underline">
          Back to dashboard
        </Link>
      </div>
    )
  }
  if (!lease) {
    return (
      <div className="grid flex-1 place-items-center text-ink-soft" role="status">
        <LoaderCircle className="size-6 animate-spin" aria-label="Loading lease" />
      </div>
    )
  }

  const [activeKey, , Section] = TABS.find(([key]) => key === params.get('tab')) ?? TABS[0]
  const state = leaseState(lease)
  const counterpart = lease.viewer_side === 'TENANT' ? lease.owner : lease.tenant

  return (
    <div className="mx-auto w-full max-w-4xl px-4 pb-28 pt-6 sm:px-6">
      <Link to="/dashboard?tab=leases" className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-soft hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden="true" /> Dashboard
      </Link>

      <header className="mt-4 rounded-xl border border-rule bg-sheet p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
              {CATEGORIES[lease.listing.category].label} · {lease.listing.area}
            </p>
            <h1 className="mt-1 font-display text-3xl font-extrabold uppercase leading-none tracking-wide sm:text-4xl">
              <Link to={`/rentals/${lease.listing_id}`} className="hover:underline">
                {lease.listing.title}
              </Link>
            </h1>
          </div>
          <Stamp tone={state.tone}>{state.label}</Stamp>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs uppercase tracking-wider text-ink-soft">{lease.viewer_side === 'TENANT' ? 'Owner' : 'Tenant'}</dt>
            <dd className="font-medium">
              <Link to={`/users/${counterpart.id}`} className="hover:underline">
                {counterpart.full_name}
              </Link>
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wider text-ink-soft">Rent</dt>
            <dd className="font-mono font-medium">{formatTaka(lease.agreed_rent)}/month</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wider text-ink-soft">Moved in</dt>
            <dd className="font-medium">{formatDay(lease.move_in_date)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wider text-ink-soft">Lease</dt>
            <dd>
              <button
                type="button"
                onClick={() => downloadFile(leasePath(lease.id), `${lease.lease_number}.pdf`)}
                className="inline-flex items-center gap-1 font-mono text-xs font-medium text-gate hover:underline"
              >
                <Download className="size-3.5" aria-hidden="true" /> {lease.lease_number}
              </button>
            </dd>
          </div>
        </dl>
      </header>

      <div role="tablist" aria-label="Lease sections" className="mt-6 flex gap-1 overflow-x-auto shadow-[inset_0_-1px_0_var(--color-rule)]">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === activeKey}
            onClick={() => setParams({ tab: key }, { replace: true })}
            className={`shrink-0 border-b-2 px-3 py-2 text-sm font-semibold transition-colors ${
              key === activeKey ? 'border-ink text-ink' : 'border-transparent text-ink-soft hover:text-ink'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="mt-6">
        <Section key={activeKey} lease={lease} onLeaseChange={setLease} />
      </div>
    </div>
  )
}
