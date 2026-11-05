import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { downloadFile, getErrorMessage } from '../../api/client.js'
import { getPendingKyc, getPendingTitleReviews, reviewKyc } from '../../api/marketplace.js'
import { formatPrice } from '../../constants/marketplace.js'
import { areaLabel } from '../../constants/rentals.js'
import { ROLES } from '../../constants/roles.js'
import TitleVault from '../sale/TitleVault.jsx'
import { Alert, EmptyState } from '../ui.jsx'
import { Spinner } from './RentalPanels.jsx'

export function TitleReviewsPanel() {
  const [queue, setQueue] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getPendingTitleReviews().then(setQueue, (err) => setError(getErrorMessage(err)))
  }, [])

  if (!queue) return error ? <Alert>{error}</Alert> : <Spinner />
  if (queue.length === 0) return <EmptyState title="No titles waiting for review." />
  return (
    <div className="space-y-3">
      {queue.map((listing) => (
        <article key={listing.id} className="rounded-xl border border-rule bg-sheet p-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">
            {areaLabel(listing.location)} · {formatPrice(listing.sale.asking_price)} · listed by {listing.lister?.full_name}
          </p>
          <Link to={`/sale/${listing.id}`} className="mt-0.5 block font-semibold hover:underline">
            {listing.title}
          </Link>
          <div className="mt-3">
            <TitleVault listingId={listing.id} mode="admin" />
          </div>
        </article>
      ))}
    </div>
  )
}

function KycRow({ person, onDone }) {
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function review(status) {
    setBusy(true)
    try {
      await reviewKyc(person.id, status, note)
      onDone(person.id)
    } catch (err) {
      setError(getErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <article className="rounded-xl border border-rule bg-sheet p-5">
      <p className="font-semibold">{person.full_name}</p>
      <p className="text-sm text-ink-soft">
        {ROLES[person.role].title} · {person.email} · {person.phone}
      </p>
      <ul className="mt-2 text-sm">
        {person.kyc_documents.map((doc) => (
          <li key={doc.doc_type}>
            {doc.doc_type.replace('_', ' ')} <span className="font-mono">{doc.doc_number}</span>{' '}
            <button
              type="button"
              onClick={() => downloadFile(`/auth/kyc/${person.id}/documents/${doc.doc_type}`, doc.original_filename).catch(() => setError('That file is no longer available.'))}
              className="text-gate hover:underline"
            >
              {doc.has_back ? 'Front' : doc.original_filename}
            </button>
            {doc.has_back && (
              <>
                {' · '}
                <button
                  type="button"
                  onClick={() => downloadFile(`/auth/kyc/${person.id}/documents/${doc.doc_type}?side=back`, `${doc.doc_type}-back.jpg`).catch(() => setError('That file is no longer available.'))}
                  className="text-gate hover:underline"
                >
                  Back
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note (optional)"
          maxLength={500}
          className="min-w-0 flex-1 rounded-md border border-rule bg-white px-3 py-2 text-sm"
        />
        <button type="button" disabled={busy} onClick={() => review('VERIFIED')} className="rounded-md bg-gate px-3 py-2 text-sm font-semibold text-white hover:bg-gate-dark disabled:opacity-60">
          Verify
        </button>
        <button type="button" disabled={busy} onClick={() => review('REJECTED')} className="rounded-md border border-tag-owner/40 px-3 py-2 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8 disabled:opacity-60">
          Reject
        </button>
      </div>
      <Alert>{error}</Alert>
    </article>
  )
}

export function KycReviewsPanel() {
  const [queue, setQueue] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getPendingKyc().then(setQueue, (err) => setError(getErrorMessage(err)))
  }, [])

  if (!queue) return error ? <Alert>{error}</Alert> : <Spinner />
  if (queue.length === 0) return <EmptyState title="No identity documents waiting for review." />
  return (
    <div className="space-y-3">
      {queue.map((person) => (
        <KycRow key={person.id} person={person} onDone={(id) => setQueue((list) => list.filter((p) => p.id !== id))} />
      ))}
    </div>
  )
}
