import { LoaderCircle, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { verifyLease } from '../api/handshake.js'
import { Alert, Wordmark } from '../components/ui.jsx'
import { formatDateTime } from '../constants/marketplace.js'
import { formatDay, formatTaka } from '../constants/rentals.js'

// Public page behind the QR stamp printed on every lease PDF.
export default function VerifyLease() {
  const { bookingId } = useParams()
  const [params] = useSearchParams()
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    verifyLease(bookingId, params.get('sig') ?? '').then(setResult, (err) => setError(getErrorMessage(err)))
  }, [bookingId, params])

  return (
    <div className="mx-auto min-h-dvh w-full max-w-lg px-4 py-8">
      <Link to="/rentals" aria-label="Bari Khujun home">
        <Wordmark className="h-14" />
      </Link>
      <div className="mt-10">
        {error && <Alert>{error}</Alert>}
        {!result && !error && <LoaderCircle className="size-6 animate-spin text-ink-soft" aria-label="Checking lease" />}
        {result && !result.valid && (
          <div className="rounded-xl border-2 border-tag-owner bg-sheet p-6">
            <ShieldAlert className="size-8 text-tag-owner" aria-hidden="true" />
            <h1 className="mt-3 font-display text-3xl font-extrabold uppercase tracking-wide">Not a valid lease</h1>
            <p className="mt-2 text-ink-soft">
              This link doesn't match any lease confirmed through Bari Khujun. The document may have been altered.
            </p>
          </div>
        )}
        {result?.valid && (
          <div className="rounded-xl border-2 border-gate bg-sheet p-6">
            <ShieldCheck className="size-8 text-gate" aria-hidden="true" />
            <h1 className="mt-3 font-display text-3xl font-extrabold uppercase tracking-wide">Lease verified</h1>
            <p className="mt-1 font-mono text-sm">{result.lease_number}</p>
            <dl className="mt-5 space-y-2 text-sm">
              {[
                ['Property', `${result.property_title}, ${result.area}`],
                ['Owner', result.owner_name],
                ['Tenant', result.tenant_name],
                ['Monthly rent', formatTaka(result.agreed_rent)],
                ['Deposit', formatTaka(result.deposit_amount)],
                ['Move-in', formatDay(result.move_in_date)],
                ['Confirmed by QR handshake', formatDateTime(result.confirmed_at)],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-4 border-b border-rule pb-2">
                  <dt className="text-ink-soft">{label}</dt>
                  <dd className="text-right font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </div>
  )
}
