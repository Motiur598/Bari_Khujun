import { useEffect, useRef, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { disputePhotoPath, getEligibleSubjects, getMyDisputes, raiseDispute, respondToDispute } from '../../api/governance.js'
import { formatDateTime } from '../../constants/marketplace.js'
import { DISPUTE_STATUS, DISPUTE_TYPES, SIDE_LABELS } from '../../constants/governance.js'
import { formatTaka } from '../../constants/rentals.js'
import { useAuth } from '../../context/AuthContext.jsx'
import AuthImage from '../AuthImage.jsx'
import { RulingSummary } from '../governance/CaseFile.jsx'
import { Alert, Button, EmptyState, Stamp, TextField } from '../ui.jsx'
import { Spinner } from './RentalPanels.jsx'

const CLAIMANT_ROLES = ['BACHELOR_TENANT', 'FAMILY_TENANT', 'BUYER']

function PhotoPicker({ inputRef, onChange, label = 'Photos (up to 10)' }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium">{label}</span>
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        onChange={(e) => onChange([...e.target.files].slice(0, 10))}
        className="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-rule file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-semibold"
      />
    </label>
  )
}

function RaiseForm({ subjects, onRaised }) {
  const photoInput = useRef(null)
  const [subjectKey, setSubjectKey] = useState(`${subjects[0].kind}:${subjects[0].id}`)
  const subject = subjects.find((s) => `${s.kind}:${s.id}` === subjectKey)
  const [type, setType] = useState(subject.types[0])
  const [amount, setAmount] = useState(String(subject.escrow_amount))
  const [description, setDescription] = useState('')
  const [photos, setPhotos] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function pickSubject(key) {
    const next = subjects.find((s) => `${s.kind}:${s.id}` === key)
    setSubjectKey(key)
    setType(next.types[0])
    setAmount(String(next.escrow_amount))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      onRaised(await raiseDispute({ type, subject, claimedAmount: Number(amount), description: description.trim(), photos }))
      setDescription('')
      setPhotos([])
      photoInput.current.value = ''
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-rule bg-sheet p-5">
      <div>
        <h3 className="font-semibold">Raise a dispute</h3>
        <p className="text-sm text-ink-soft">
          A Bari Khujun arbitrator reads both sides and decides how the money held for the deal is paid out. Whoever is found
          at fault loses 15 trust points.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">About</span>
          <select value={subjectKey} onChange={(e) => pickSubject(e.target.value)} className="w-full rounded-md border border-rule bg-white px-3 py-2.5">
            {subjects.map((s) => (
              <option key={`${s.kind}:${s.id}`} value={`${s.kind}:${s.id}`}>
                {s.label} · with {s.counterpart}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">What happened</span>
          <select value={type} onChange={(e) => setType(e.target.value)} className="w-full rounded-md border border-rule bg-white px-3 py-2.5">
            {subject.types.map((t) => (
              <option key={t} value={t}>
                {DISPUTE_TYPES[t].label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="-mt-2 text-xs text-ink-soft">{DISPUTE_TYPES[type].help}</p>
      <TextField
        label="Amount you want back (৳)"
        type="number"
        required
        min={1}
        max={subject.escrow_amount}
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        hint={`${formatTaka(subject.escrow_amount)} is held for this deal.`}
        className="sm:w-72"
      />
      <div>
        <label htmlFor="dispute-description" className="mb-1.5 block text-sm font-medium">
          Tell the arbitrator what happened
        </label>
        <textarea
          id="dispute-description"
          rows={4}
          required
          minLength={10}
          maxLength={2000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full rounded-md border border-rule bg-white px-3 py-2.5"
        />
      </div>
      <PhotoPicker inputRef={photoInput} onChange={setPhotos} />
      <Alert>{error}</Alert>
      <Button type="submit" busy={busy}>
        Raise dispute
      </Button>
    </form>
  )
}

function ResponseForm({ dispute, onResponded }) {
  const photoInput = useRef(null)
  const [statement, setStatement] = useState('')
  const [deduction, setDeduction] = useState('')
  const [photos, setPhotos] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      onResponded(await respondToDispute(dispute.id, { statement: statement.trim(), claimedDeduction: deduction, photos }))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 space-y-3 border-t border-rule pt-4">
      <p className="text-sm font-semibold">Your side of the story</p>
      <textarea
        rows={4}
        required
        minLength={10}
        maxLength={2000}
        value={statement}
        onChange={(e) => setStatement(e.target.value)}
        aria-label="Your statement"
        className="w-full rounded-md border border-rule bg-white px-3 py-2.5"
      />
      <TextField
        label="Amount you believe you're owed (৳, optional)"
        type="number"
        min={0}
        max={dispute.escrow_amount}
        value={deduction}
        onChange={(e) => setDeduction(e.target.value)}
        className="sm:w-80"
      />
      <PhotoPicker inputRef={photoInput} onChange={setPhotos} label="Claim photos (up to 10)" />
      <Alert>{error}</Alert>
      <Button type="submit" busy={busy}>
        Send reply
      </Button>
    </form>
  )
}

function DisputeCard({ dispute, me, onChange }) {
  const iAmClaimant = dispute.claimant.id === me
  const other = iAmClaimant ? dispute.respondent : dispute.claimant
  const myPhotos = iAmClaimant ? dispute.claimant_photos : dispute.response?.photos ?? []
  return (
    <article className="rounded-xl border border-rule bg-sheet p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
            {DISPUTE_TYPES[dispute.type].label} · <span className="font-mono normal-case">{dispute.case_number}</span>
          </p>
          <p className="mt-0.5 font-semibold">{dispute.listing_title}</p>
          <p className="text-sm text-ink-soft">
            {iAmClaimant ? 'You raised this against' : 'Raised against you by'} {other.full_name} ({SIDE_LABELS[other.side]}) ·{' '}
            {formatTaka(dispute.escrow_amount)} held · {formatTaka(dispute.claimed_amount)} claimed
          </p>
        </div>
        <Stamp tone={DISPUTE_STATUS[dispute.status].tone}>{DISPUTE_STATUS[dispute.status].label}</Stamp>
      </div>
      <p className="mt-3 whitespace-pre-line text-sm">“{dispute.description}”</p>
      {dispute.response && (
        <p className="mt-2 whitespace-pre-line text-sm text-ink-soft">
          {dispute.respondent.full_name} replied {formatDateTime(dispute.response.responded_at)}: “{dispute.response.statement}”
        </p>
      )}
      {myPhotos.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {myPhotos.map((photo) => (
            <li key={photo.id} className="w-24 overflow-hidden rounded-md border border-rule">
              <AuthImage path={disputePhotoPath(dispute.id, photo.id)} alt="Evidence photo" className="aspect-square w-full" />
            </li>
          ))}
        </ul>
      )}
      {!iAmClaimant && dispute.status === 'OPEN' && !dispute.response && <ResponseForm dispute={dispute} onResponded={onChange} />}
      {dispute.ruling && (
        <div className="mt-4">
          <RulingSummary dispute={dispute} />
        </div>
      )}
    </article>
  )
}

export default function DisputesPanel() {
  const { user } = useAuth()
  const [disputes, setDisputes] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [error, setError] = useState('')
  const canRaise = CLAIMANT_ROLES.includes(user.role)

  useEffect(() => {
    getMyDisputes().then(setDisputes, (err) => setError(getErrorMessage(err)))
    if (canRaise) getEligibleSubjects().then(setSubjects, () => setSubjects([]))
  }, [canRaise])

  const upsert = (next) => setDisputes((list) => [next, ...(list ?? []).filter((d) => d.id !== next.id)])

  return (
    <div className="space-y-4">
      {canRaise && subjects.length > 0 && <RaiseForm subjects={subjects} onRaised={upsert} />}
      {error && <Alert>{error}</Alert>}
      {disputes === null ? (
        <Spinner />
      ) : disputes.length === 0 ? (
        <EmptyState title="No disputes.">
          {canRaise ? 'If a deposit, listing or bayna deal goes wrong, raise it here and an arbitrator will decide.' : 'Disputes tenants or buyers raise with you appear here.'}
        </EmptyState>
      ) : (
        disputes.map((dispute) => <DisputeCard key={dispute.id} dispute={dispute} me={user.id} onChange={upsert} />)
      )}
    </div>
  )
}
