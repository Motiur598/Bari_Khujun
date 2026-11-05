import { Radar } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { getAuditLog, resolveAlert, runRadar } from '../../api/governance.js'
import { decideKyc, kycCardImagePath } from '../../api/kyc.js'
import AuthImage from '../AuthImage.jsx'
import { formatDateTime } from '../../constants/marketplace.js'
import { ALERT_RULES } from '../../constants/governance.js'
import { Spinner } from '../dashboard/RentalPanels.jsx'
import { Alert, Button, EmptyState, Segmented, Stamp } from '../ui.jsx'

const VIEWS = [
  ['open', 'Open alerts'],
  ['resolved', 'Resolved alerts'],
  ['actions', 'Admin actions'],
]
const QUERIES = { open: { kind: 'ALERT', status: 'OPEN' }, resolved: { kind: 'ALERT', status: 'RESOLVED' }, actions: { kind: 'ACTION' } }
const SEVERITY_TONES = { HIGH: 'border-tag-owner text-tag-owner', MEDIUM: 'border-brass text-[#8a6410]', LOW: 'border-ink-soft text-ink-soft', INFO: 'border-ink-soft text-ink-soft' }

const KYC_RULES = ['KYC_DUPLICATE_ID', 'KYC_POSSIBLE_DUPLICATE']

// One card on file: its front and back photos.
function KycCardPhotos({ record, title }) {
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink-soft">{title}</figcaption>
      <div className="grid grid-cols-2 gap-1.5">
        {['front', 'back'].map((side) => (
          <AuthImage key={side} path={kycCardImagePath(record, side)} alt={`${title}, ${side}`} className="aspect-[1.586] w-full rounded" />
        ))}
      </div>
    </figure>
  )
}

// The flagged card next to each card it was matched with, so an admin can compare them by eye.
function KycEvidence({ entry, onDecided }) {
  const { record_id: recordId, matches = [] } = entry.evidence ?? {}
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const revoked = entry.rule === 'KYC_DUPLICATE_ID'
  const actions = revoked
    ? [['restore', 'Restore account', 'bg-gate text-white hover:bg-gate-dark']]
    : [
        ['approve', 'Approve ID', 'bg-gate text-white hover:bg-gate-dark'],
        ['revoke', 'Revoke (−30 trust)', 'bg-tag-owner text-white hover:bg-tag-owner/90'],
      ]

  async function decide(decision) {
    setBusy(decision)
    setError('')
    try {
      await decideKyc(entry.subject.id, decision, note.trim())
      onDecided()
    } catch (err) {
      setError(getErrorMessage(err))
      setBusy('')
    }
  }

  return (
    <div className="mt-4 space-y-4 border-t border-rule pt-4">
      {matches.map((match) => (
        <div key={match.record_id} className="space-y-2">
          <p className="text-sm">
            <span className="font-semibold">{match.reasons.join(' · ')}</span>
            <span className="text-ink-soft">
              {' '}
              with {match.full_name}'s card · ID number {Math.round(match.id_similarity)}% alike · name{' '}
              {Math.round(match.name_similarity)}%{match.face_similarity != null && ` · face ${Math.round(match.face_similarity * 100)}%`}
              {` · card picture distance ${match.front_phash_distance}`}
            </span>
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            {recordId && <KycCardPhotos record={recordId} title={`${entry.subject.full_name} (this account)`} />}
            <KycCardPhotos record={match.record_id} title={`${match.full_name} (matched)`} />
          </div>
        </div>
      ))}
      {entry.status === 'OPEN' && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-0 flex-1 text-sm">
            <span className="mb-1 block font-medium">
              {revoked ? 'Why restore (e.g. the owner sent a video with the card)' : 'Your decision, for the record'}
            </span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} className="w-full rounded-md border border-rule bg-white px-3 py-2" />
          </label>
          {actions.map(([decision, label, tone]) => (
            <button
              key={decision}
              type="button"
              disabled={note.trim().length < 3 || Boolean(busy)}
              onClick={() => decide(decision)}
              className={`rounded-md px-3 py-2 text-sm font-semibold disabled:opacity-50 ${tone}`}
            >
              {busy === decision ? 'Saving…' : label}
            </button>
          ))}
        </div>
      )}
      <Alert>{error}</Alert>
    </div>
  )
}

function AlertCard({ entry, onResolved, onBan }) {
  const [note, setNote] = useState('')
  const [resolving, setResolving] = useState(false)
  const [error, setError] = useState('')
  const evidence = entry.evidence ?? {}

  async function resolve() {
    try {
      onResolved(await resolveAlert(entry.id, note.trim()))
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  return (
    <article className="rounded-xl border border-rule bg-sheet p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
            {ALERT_RULES[entry.rule] ?? entry.rule}
            {entry.subject && ` · ${entry.subject.full_name}${entry.subject.role ? ` (${entry.subject.role.replace('_', ' ').toLowerCase()})` : ''}`}
          </p>
          <p className="mt-1 font-medium">{entry.message}</p>
          <p className="mt-1 font-mono text-xs text-ink-soft">
            {formatDateTime(entry.created_at)}
            {entry.hits > 1 && ` · triggered ${entry.hits} times, last ${formatDateTime(entry.updated_at)}`}
            {entry.actor && ` · ${entry.kind === 'ACTION' ? 'by' : 'resolved by'} ${entry.actor.full_name}`}
          </p>
        </div>
        <Stamp tone={SEVERITY_TONES[entry.severity]}>{entry.severity}</Stamp>
      </div>
      {(evidence.booking_ids?.length > 0 || evidence.tenants?.length > 0) && (
        <p className="mt-2 text-sm text-ink-soft">
          {evidence.tenants?.length > 0 && <>Tenants: {evidence.tenants.join(', ')}. </>}
          {evidence.booking_ids?.length > 0 && (
            <>
              Bookings: <span className="font-mono text-xs">{evidence.booking_ids.map((id) => id.slice(-6)).join(', ')}</span>
            </>
          )}
        </p>
      )}
      {KYC_RULES.includes(entry.rule) && entry.subject && <KycEvidence entry={entry} onDecided={() => onResolved()} />}
      {entry.resolution_note && <p className="mt-2 text-sm">“{entry.resolution_note}”</p>}
      {entry.kind === 'ALERT' && entry.status === 'OPEN' && (
        <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-rule pt-4">
          {resolving ? (
            <>
              <label className="min-w-0 flex-1 text-sm">
                <span className="mb-1 block font-medium">Why it's fine (or what you did)</span>
                <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} className="w-full rounded-md border border-rule bg-white px-3 py-2" />
              </label>
              <button
                type="button"
                disabled={note.trim().length < 3}
                onClick={resolve}
                className="rounded-md border border-rule bg-white px-3 py-2 text-sm font-semibold hover:border-ink disabled:opacity-50"
              >
                Resolve
              </button>
            </>
          ) : (
            <button type="button" onClick={() => setResolving(true)} className="rounded-md border border-rule bg-white px-3 py-2 text-sm font-semibold hover:border-ink">
              Mark as resolved
            </button>
          )}
          {entry.subject && (
            <button
              type="button"
              onClick={() => onBan(entry)}
              className="rounded-md bg-tag-owner px-3 py-2 text-sm font-semibold text-white hover:bg-tag-owner/90"
            >
              Ban {entry.subject.full_name.split(' ')[0]}
            </button>
          )}
          <div className="w-full">
            <Alert>{error}</Alert>
          </div>
        </div>
      )}
    </article>
  )
}

export default function RadarTab({ onBan, refreshKey, onChanged }) {
  const [view, setView] = useState('open')
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [running, setRunning] = useState(false)

  const load = useCallback(() => {
    setEntries(null)
    getAuditLog(QUERIES[view]).then(setEntries, (err) => setError(getErrorMessage(err)))
  }, [view])
  useEffect(load, [load, refreshKey])

  async function scan() {
    setRunning(true)
    setNotice('')
    try {
      const { new_alerts: created } = await runRadar()
      setNotice(created ? `${created} new alert${created === 1 ? '' : 's'}.` : 'No new suspicious activity.')
      load()
      onChanged()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Segmented legend="Show" name="radar-view" value={view} options={VIEWS} onChange={setView} className="min-w-0 sm:w-[28rem]" />
        <Button type="button" busy={running} onClick={scan}>
          <Radar className="size-4" aria-hidden="true" /> Run radar now
        </Button>
      </div>
      <p className="text-sm text-ink-soft">
        The radar flags owners who issue 3 or more handshake QR codes in 48 hours with none confirmed, and owners who put a
        place back on the market within 48 hours of a confirmed handshake. It checks after every QR issue and every 15
        minutes. ID checks add an alert when a card's number belongs to another account (revoked at once) or its face or
        front looks like another account's card (held for you to decide).
      </p>
      {notice && <Alert tone="success">{notice}</Alert>}
      {error && <Alert>{error}</Alert>}
      {entries === null ? (
        <Spinner />
      ) : entries.length === 0 ? (
        <EmptyState title={view === 'open' ? 'No open alerts.' : 'Nothing here yet.'} />
      ) : (
        entries.map((entry) => (
          <AlertCard
            key={entry.id}
            entry={entry}
            onBan={(alert) => onBan(alert.subject, `${ALERT_RULES[alert.rule]}: ${alert.message}`)}
            onResolved={() => {
              load()
              onChanged()
            }}
          />
        ))
      )}
    </div>
  )
}
