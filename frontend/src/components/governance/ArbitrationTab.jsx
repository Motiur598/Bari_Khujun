import { useCallback, useEffect, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { getAdminDisputes } from '../../api/governance.js'
import { formatDateTime } from '../../constants/marketplace.js'
import { DISPUTE_STATUS, DISPUTE_TYPES, SIDE_LABELS } from '../../constants/governance.js'
import { formatTaka } from '../../constants/rentals.js'
import { Spinner } from '../dashboard/RentalPanels.jsx'
import { Alert, EmptyState, Segmented, Stamp } from '../ui.jsx'
import CaseFile from './CaseFile.jsx'

const FILTERS = [
  ['UNDER_REVIEW', 'Ready to rule'],
  ['OPEN', 'Waiting for reply'],
  ['RESOLVED', 'Ruled'],
  ['', 'All'],
]

export default function ArbitrationTab({ refreshKey, onChanged }) {
  const [status, setStatus] = useState('UNDER_REVIEW')
  const [disputes, setDisputes] = useState(null)
  const [open, setOpen] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setDisputes(null)
    getAdminDisputes(status).then(setDisputes, (err) => setError(getErrorMessage(err)))
  }, [status])
  useEffect(load, [load, refreshKey])

  return (
    <div className="space-y-4">
      <Segmented legend="Cases" name="dispute-filter" value={status} options={FILTERS} onChange={setStatus} className="sm:w-[32rem]" />
      {error && <Alert>{error}</Alert>}
      {disputes === null ? (
        <Spinner />
      ) : disputes.length === 0 ? (
        <EmptyState title="No cases here." />
      ) : (
        <ul className="space-y-2">
          {disputes.map((dispute) => (
            <li key={dispute.id}>
              <button
                type="button"
                onClick={() => setOpen(dispute)}
                className="flex w-full flex-wrap items-center gap-4 rounded-xl border border-rule bg-sheet p-4 text-left hover:border-ink-soft"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
                    {DISPUTE_TYPES[dispute.type].label} · <span className="font-mono normal-case">{dispute.case_number}</span>
                  </p>
                  <p className="mt-0.5 font-semibold">{dispute.listing_title}</p>
                  <p className="text-sm text-ink-soft">
                    {dispute.claimant.full_name} ({SIDE_LABELS[dispute.claimant.side]}) vs {dispute.respondent.full_name} (
                    {SIDE_LABELS[dispute.respondent.side]}) · {formatTaka(dispute.escrow_amount)} in escrow · raised{' '}
                    {formatDateTime(dispute.created_at)}
                  </p>
                </div>
                <Stamp tone={DISPUTE_STATUS[dispute.status].tone}>{DISPUTE_STATUS[dispute.status].label}</Stamp>
                <span className="text-sm font-semibold text-gate">Open case file</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <CaseFile
        dispute={open}
        onClose={() => setOpen(null)}
        onRuled={(ruled) => {
          setOpen(ruled)
          load()
          onChanged()
        }}
      />
    </div>
  )
}
