import { Fingerprint, Gavel, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { baselinePhotoPath, disputePhotoPath, ruleDispute } from '../../api/governance.js'
import { formatDateTime } from '../../constants/marketplace.js'
import { DISPUTE_STATUS, DISPUTE_TYPES, SIDE_LABELS } from '../../constants/governance.js'
import { formatTaka } from '../../constants/rentals.js'
import AuthImage from '../AuthImage.jsx'
import { Alert, Button, Segmented, Stamp } from '../ui.jsx'

function PhotoGrid({ photos, pathFor, empty }) {
  if (!photos.length) return <p className="text-sm text-ink-soft">{empty}</p>
  return (
    <ul className="grid grid-cols-2 gap-2">
      {photos.map((photo) => (
        <li key={photo.id} className="overflow-hidden rounded-lg border border-rule bg-white">
          <AuthImage path={pathFor(photo.id)} alt={photo.caption || photo.room || 'Evidence photo'} className="aspect-[4/3] w-full" />
          <div className="space-y-0.5 p-2 text-xs">
            {(photo.room || photo.caption) && <p className="font-medium">{[photo.room, photo.caption].filter(Boolean).join(' · ')}</p>}
            <p className="font-mono text-ink-soft">{formatDateTime(photo.uploaded_at)}</p>
            <p className="flex items-center gap-1 font-mono text-ink-soft" title={`SHA-256 ${photo.sha256}`}>
              <Fingerprint className="size-3" aria-hidden="true" /> {photo.sha256.slice(0, 10)}…
            </p>
          </div>
        </li>
      ))}
    </ul>
  )
}

function RulingForm({ dispute, onRuled }) {
  const escrow = dispute.escrow_amount
  const claimantSide = SIDE_LABELS[dispute.claimant.side]
  const respondentSide = SIDE_LABELS[dispute.respondent.side]
  const [outcome, setOutcome] = useState('CUSTOM_SPLIT')
  const [claimantShare, setClaimantShare] = useState(Math.max(0, escrow - (dispute.response?.claimed_deduction ?? 0)))
  const [fault, setFault] = useState('NONE')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const shares =
    outcome === 'REFUND_TENANT' ? [escrow, 0] : outcome === 'PAY_OWNER' ? [0, escrow] : [claimantShare, escrow - claimantShare]

  async function handleRule() {
    const penalised = fault === 'NONE' ? '' : ` ${fault === 'CLAIMANT' ? dispute.claimant.full_name : dispute.respondent.full_name} loses 15 trust points.`
    if (!window.confirm(`Pay ${formatTaka(shares[0])} to the ${claimantSide} and ${formatTaka(shares[1])} to the ${respondentSide}?${penalised}`)) return
    setBusy(true)
    setError('')
    try {
      onRuled(
        await ruleDispute(dispute.id, {
          outcome,
          fault,
          note: note.trim(),
          ...(outcome === 'CUSTOM_SPLIT' ? { claimant_amount: shares[0], respondent_amount: shares[1] } : {}),
        }),
      )
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Segmented
        legend="Escrow"
        name="ruling-outcome"
        value={outcome}
        options={[
          ['REFUND_TENANT', `Refund ${claimantSide}`],
          ['PAY_OWNER', `Pay ${respondentSide}`],
          ['CUSTOM_SPLIT', 'Split'],
        ]}
        onChange={setOutcome}
      />
      {outcome === 'CUSTOM_SPLIT' && (
        <div>
          <input
            type="range"
            min={0}
            max={escrow}
            step={Math.max(1, Math.round(escrow / 200))}
            value={claimantShare}
            onChange={(e) => setClaimantShare(Number(e.target.value))}
            aria-label={`Amount to the ${claimantSide}`}
            className="w-full accent-gate"
          />
          <div className="mt-1 grid grid-cols-2 gap-3 text-sm">
            <label className="block">
              <span className="mb-1 block text-ink-soft">To the {claimantSide} (৳)</span>
              <input
                type="number"
                min={0}
                max={escrow}
                value={claimantShare}
                onChange={(e) => setClaimantShare(Math.min(escrow, Math.max(0, Number(e.target.value) || 0)))}
                className="w-full rounded-md border border-rule bg-white px-3 py-2 font-mono"
              />
            </label>
            <div>
              <span className="mb-1 block text-ink-soft">To the {respondentSide}</span>
              <p className="rounded-md border border-rule bg-plaster px-3 py-2 font-mono">{formatTaka(escrow - claimantShare)}</p>
            </div>
          </div>
        </div>
      )}
      <div className="flex h-3 overflow-hidden rounded-full bg-plaster" aria-hidden="true">
        <div className="bg-tag-bachelor transition-all" style={{ width: `${(shares[0] / escrow) * 100}%` }} />
        <div className="bg-tag-owner transition-all" style={{ width: `${(shares[1] / escrow) * 100}%` }} />
      </div>
      <p className="text-sm">
        <span className="font-mono">{formatTaka(shares[0])}</span> to {dispute.claimant.full_name} ·{' '}
        <span className="font-mono">{formatTaka(shares[1])}</span> to {dispute.respondent.full_name}
      </p>
      <Segmented
        legend="Who's at fault?"
        name="ruling-fault"
        value={fault}
        options={[
          ['CLAIMANT', dispute.claimant.full_name.split(' ')[0]],
          ['RESPONDENT', dispute.respondent.full_name.split(' ')[0]],
          ['NONE', 'Nobody'],
        ]}
        onChange={setFault}
      />
      <p className="text-xs text-ink-soft">The party at fault loses 15 trust points, which stay off their score even after new reviews.</p>
      <label className="block text-sm">
        <span className="mb-1 block font-medium">Reasons (both parties see this)</span>
        <textarea rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} className="w-full rounded-md border border-rule bg-white px-3 py-2" />
      </label>
      <Alert>{error}</Alert>
      <Button type="button" busy={busy} disabled={note.trim().length < 3} onClick={handleRule}>
        <Gavel className="size-4" aria-hidden="true" /> Issue ruling
      </Button>
    </div>
  )
}

export function RulingSummary({ dispute }) {
  const { ruling } = dispute
  return (
    <div className="rounded-lg border border-gate/40 bg-gate/5 p-4 text-sm">
      <p className="font-semibold">
        Ruled {formatDateTime(ruling.ruled_at)} by {ruling.ruled_by.full_name}
      </p>
      <p className="mt-1">
        <span className="font-mono">{formatTaka(ruling.claimant_amount)}</span> to {dispute.claimant.full_name} ·{' '}
        <span className="font-mono">{formatTaka(ruling.respondent_amount)}</span> to {dispute.respondent.full_name}
      </p>
      {ruling.penalized && (
        <p className="mt-1 text-tag-owner">
          {ruling.penalized.full_name} found at fault: −{ruling.penalty_points} trust points.
        </p>
      )}
      <p className="mt-2 text-ink-soft">“{ruling.note}”</p>
    </div>
  )
}

// Full-screen case file: the two sides' evidence next to each other, with the ruling underneath.
export default function CaseFile({ dispute, onClose, onRuled }) {
  const dialogRef = useRef(null)
  useEffect(() => {
    const dialog = dialogRef.current
    if (dispute && !dialog.open) dialog.showModal()
    if (!dispute && dialog.open) dialog.close()
  }, [dispute])

  const isLease = dispute?.type === 'DEPOSIT_DEDUCTION'
  return (
    <dialog ref={dialogRef} onClose={onClose} aria-labelledby="case-heading" className="m-auto max-h-[94dvh] w-[calc(100%-2rem)] max-w-6xl overflow-hidden rounded-xl bg-sheet p-0 text-ink shadow-2xl">
      {dispute && (
        <div className="flex max-h-[94dvh] flex-col">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-rule px-5 py-4">
            <div>
              <p className="font-mono text-xs text-ink-soft">{dispute.case_number}</p>
              <h2 id="case-heading" className="font-display text-2xl font-extrabold uppercase tracking-wide">
                {DISPUTE_TYPES[dispute.type].label} · {dispute.listing_title}
              </h2>
              <p className="text-sm text-ink-soft">
                {formatTaka(dispute.escrow_amount)} in escrow · {dispute.claimant.full_name} wants {formatTaka(dispute.claimed_amount)} back
                {dispute.response?.claimed_deduction != null && ` · ${dispute.respondent.full_name} claims ${formatTaka(dispute.response.claimed_deduction)}`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Stamp tone={DISPUTE_STATUS[dispute.status].tone}>{DISPUTE_STATUS[dispute.status].label}</Stamp>
              <button type="button" onClick={onClose} aria-label="Close case file" className="rounded p-1 text-ink-soft hover:bg-plaster hover:text-ink">
                <X className="size-5" aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="grid divide-y divide-rule lg:grid-cols-2 lg:divide-x lg:divide-y-0">
              <section className="space-y-3 p-5">
                <p className="text-xs font-semibold uppercase tracking-widest text-tag-bachelor">
                  {isLease ? 'Before · tenant’s move-in baseline' : `${SIDE_LABELS[dispute.claimant.side]}’s evidence`}
                </p>
                <p className="font-semibold">
                  {dispute.claimant.full_name} <span className="font-normal text-ink-soft">({SIDE_LABELS[dispute.claimant.side]}, raised the dispute)</span>
                </p>
                <p className="whitespace-pre-line text-sm">“{dispute.description}”</p>
                {isLease && (
                  <PhotoGrid
                    photos={dispute.baseline_photos}
                    pathFor={(id) => baselinePhotoPath(dispute.id, id)}
                    empty="The tenant didn't log any move-in photos."
                  />
                )}
                {(dispute.claimant_photos.length > 0 || !isLease) && (
                  <PhotoGrid photos={dispute.claimant_photos} pathFor={(id) => disputePhotoPath(dispute.id, id)} empty="No photos attached." />
                )}
              </section>
              <section className="space-y-3 p-5">
                <p className="text-xs font-semibold uppercase tracking-widest text-tag-owner">
                  {isLease ? 'After · owner’s claim' : `${SIDE_LABELS[dispute.respondent.side]}’s evidence`}
                </p>
                <p className="font-semibold">
                  {dispute.respondent.full_name} <span className="font-normal text-ink-soft">({SIDE_LABELS[dispute.respondent.side]})</span>
                </p>
                {dispute.response ? (
                  <>
                    <p className="whitespace-pre-line text-sm">“{dispute.response.statement}”</p>
                    <PhotoGrid
                      photos={dispute.response.photos}
                      pathFor={(id) => disputePhotoPath(dispute.id, id)}
                      empty="No photos attached to the reply."
                    />
                  </>
                ) : (
                  <p className="text-sm text-ink-soft">No reply yet. You can still rule without one.</p>
                )}
              </section>
            </div>
            <div className="border-t border-rule p-5">
              <h3 className="mb-3 font-display text-xl font-extrabold uppercase tracking-wide">Ruling</h3>
              {dispute.ruling ? <RulingSummary dispute={dispute} /> : <RulingForm dispute={dispute} onRuled={onRuled} />}
            </div>
          </div>
        </div>
      )}
    </dialog>
  )
}
