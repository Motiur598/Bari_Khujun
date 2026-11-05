import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { getDeedVault } from '../../api/governance.js'
import { TITLE_STATUS, formatPrice } from '../../constants/marketplace.js'
import { areaLabel } from '../../constants/rentals.js'
import { Spinner } from '../dashboard/RentalPanels.jsx'
import TitleVault from '../sale/TitleVault.jsx'
import { Alert, EmptyState, Segmented, Stamp } from '../ui.jsx'

const FILTERS = [
  ['PENDING', 'Waiting'],
  ['VERIFIED', 'Verified'],
  ['REJECTED', 'Rejected'],
  ['ALL', 'All'],
]

export default function DeedVaultTab({ onChanged }) {
  const [status, setStatus] = useState('PENDING')
  const [listings, setListings] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setListings(null)
    getDeedVault(status).then(setListings, (err) => setError(getErrorMessage(err)))
  }, [status])

  return (
    <div className="space-y-4">
      <Segmented legend="Titles" name="deed-filter" value={status} options={FILTERS} onChange={setStatus} className="sm:w-[28rem]" />
      <p className="text-sm text-ink-soft">
        Check the mutation record, deed summary and tax receipt against each other. Approving shows the public Verified title
        badge on the listing; rejecting sends your note to the seller.
      </p>
      {error && <Alert>{error}</Alert>}
      {listings === null ? (
        <Spinner />
      ) : listings.length === 0 ? (
        <EmptyState title={status === 'PENDING' ? 'No titles waiting for review.' : 'Nothing here.'} />
      ) : (
        <ul className="space-y-3">
          {listings.map((listing) => (
            <li key={listing.id} className="rounded-xl border border-rule bg-sheet">
              <details open={status === 'PENDING'}>
                <summary className="flex cursor-pointer flex-wrap items-center gap-3 p-4 marker:content-none">
                  <div className="min-w-0 flex-1">
                    <Link to={`/sale/${listing.id}`} className="font-semibold hover:underline" onClick={(e) => e.stopPropagation()}>
                      {listing.title}
                    </Link>
                    <p className="text-sm text-ink-soft">
                      {areaLabel(listing.location)} · {formatPrice(listing.sale.asking_price)} · {listing.lister?.full_name} ·{' '}
                      {listing.title_documents_on_file.length} of 3 documents
                    </p>
                  </div>
                  <Stamp tone={TITLE_STATUS[listing.title_status].stamp}>{TITLE_STATUS[listing.title_status].label}</Stamp>
                </summary>
                <div className="border-t border-rule p-4">
                  <TitleVault listingId={listing.id} mode="admin" onReviewed={onChanged} />
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
