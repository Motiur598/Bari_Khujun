import { Check, FileText, LoaderCircle, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { downloadFile, getErrorMessage } from '../../api/client.js'
import { getTitleVault, reviewTitle, titleDocumentPath, uploadTitleDocument } from '../../api/marketplace.js'
import { TITLE_DOCS, TITLE_STATUS, formatDateTime } from '../../constants/marketplace.js'
import { Alert, Button } from '../ui.jsx'

function DocumentRow({ listingId, docType, document, canUpload, onUploaded, onError }) {
  const input = useRef(null)
  const [busy, setBusy] = useState(false)
  const { label, help } = TITLE_DOCS[docType]

  async function handleFile(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setBusy(true)
    try {
      onUploaded(await uploadTitleDocument(listingId, docType, file))
    } catch (err) {
      onError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="flex flex-wrap items-start gap-3 py-3">
      <span
        className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-full ${document ? 'bg-gate text-white' : 'border-2 border-dashed border-rule'}`}
        aria-hidden="true"
      >
        {document && <Check className="size-3.5" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{label}</p>
        <p className="text-xs text-ink-soft">{help}</p>
        {document && (
          <button
            type="button"
            onClick={() => downloadFile(titleDocumentPath(listingId, docType), document.original_filename).catch(() => onError('Could not open that file.'))}
            className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-gate hover:underline"
          >
            <FileText className="size-3.5" aria-hidden="true" />
            {document.original_filename} · {formatDateTime(document.uploaded_at)}
          </button>
        )}
      </div>
      {canUpload && (
        <>
          <button
            type="button"
            onClick={() => input.current.click()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-2.5 py-1.5 text-xs font-semibold hover:border-ink disabled:opacity-60"
          >
            {busy ? <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" /> : <Upload className="size-3.5" aria-hidden="true" />}
            {document ? 'Replace' : 'Upload'}
          </button>
          <input ref={input} type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={handleFile} className="sr-only" tabIndex={-1} />
        </>
      )}
    </li>
  )
}

// mode "seller" uploads documents; "admin" reads them and approves or rejects the title; "viewer" (a buyer with an
// open offer) only reads them.
export default function TitleVault({ listingId, mode = 'seller', onReviewed }) {
  const [vault, setVault] = useState(null)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [reviewing, setReviewing] = useState(false)

  useEffect(() => {
    getTitleVault(listingId).then(setVault, (err) => setError(getErrorMessage(err)))
  }, [listingId])

  async function review(status) {
    setReviewing(true)
    setError('')
    try {
      setVault(await reviewTitle(listingId, status, note))
      onReviewed?.(status)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setReviewing(false)
    }
  }

  if (!vault) {
    if (error && mode === 'viewer') {
      return <p className="text-sm text-ink-soft">Make an offer to see the seller's title documents.</p>
    }
    return error ? <Alert>{error}</Alert> : <LoaderCircle className="size-5 animate-spin text-ink-soft" aria-label="Loading title vault" />
  }
  const status = TITLE_STATUS[vault.title_status]
  const byType = Object.fromEntries(vault.documents.map((doc) => [doc.doc_type, doc]))

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className={`-rotate-2 rounded border-2 px-2 py-1 font-mono text-xs font-medium uppercase tracking-widest ${status.stamp}`}>
          {status.label}
        </span>
        {mode === 'seller' && (
          <p className="text-xs text-ink-soft">
            {vault.title_status === 'VERIFIED'
              ? 'Buyers see the Verified title badge. Replacing a document sends it back for review.'
              : 'The Verified title badge appears once an admin approves these documents.'}
          </p>
        )}
      </div>
      {vault.title_review_note && (
        <p className="mt-2 text-sm">
          <span className="font-medium">Reviewer's note:</span> {vault.title_review_note}
        </p>
      )}
      <ul className="mt-2 divide-y divide-rule">
        {Object.keys(TITLE_DOCS).map((docType) => (
          <DocumentRow
            key={docType}
            listingId={listingId}
            docType={docType}
            document={byType[docType]}
            canUpload={mode === 'seller'}
            onUploaded={(next) => {
              setError('')
              setVault(next)
            }}
            onError={setError}
          />
        ))}
      </ul>
      <Alert>{error}</Alert>
      {mode === 'admin' && vault.title_status === 'PENDING' && (
        <div className="mt-3 space-y-3 border-t border-rule pt-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Note to the seller (optional)</span>
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={500}
              placeholder="e.g. Mutation record name doesn't match the deed"
              className="w-full rounded-md border border-rule bg-white px-3 py-2 text-sm"
            />
          </label>
          <div className="flex gap-2">
            <Button type="button" busy={reviewing} onClick={() => review('VERIFIED')}>
              Verify title
            </Button>
            <button
              type="button"
              disabled={reviewing}
              onClick={() => review('REJECTED')}
              className="rounded-md border border-tag-owner/40 px-4 py-2.5 text-sm font-semibold text-tag-owner hover:bg-tag-owner/8 disabled:opacity-60"
            >
              Reject
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
