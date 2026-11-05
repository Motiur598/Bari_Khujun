import { LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/client.js'
import { getPriceAnalysis } from '../../api/marketplace.js'
import { PROPERTY_TYPES } from '../../constants/marketplace.js'
import { formatTaka } from '../../constants/rentals.js'
import { Alert } from '../ui.jsx'

const VERDICTS = {
  BELOW_MARKET: { label: 'Below market', tone: 'bg-gate text-white' },
  AT_MARKET: { label: 'In line with market', tone: 'bg-ink text-white' },
  ABOVE_MARKET: { label: 'Above market', tone: 'bg-tag-owner text-white' },
  NOT_ENOUGH_DATA: { label: 'Not enough nearby sales', tone: 'bg-plaster text-ink-soft' },
}

// A strip from the cheapest to the dearest comparable, with the neighbourhood average and this listing marked.
function PriceStrip({ ppsf, stats }) {
  const low = Math.min(stats.min_ppsf, ppsf)
  const high = Math.max(stats.max_ppsf, ppsf)
  const at = (value) => `${high === low ? 50 : ((value - low) / (high - low)) * 100}%`
  return (
    <div className="mt-6 px-2">
      <div className="relative h-2 rounded-full bg-plaster">
        <div
          className="absolute inset-y-0 rounded-full bg-ink/15"
          style={{ left: at(stats.min_ppsf), right: `calc(100% - ${at(stats.max_ppsf)})` }}
        />
        <div className="absolute -top-2 h-6 w-0.5 -translate-x-1/2 bg-leaf" style={{ left: at(stats.average_ppsf) }} />
        <div
          className="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-tag-owner shadow"
          style={{ left: at(ppsf) }}
        />
      </div>
      <div className="mt-2 flex justify-between font-mono text-xs text-ink-soft">
        <span>{formatTaka(low)}</span>
        <span>{formatTaka(high)}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-tag-owner" aria-hidden="true" /> This listing
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-0.5 bg-leaf" aria-hidden="true" /> Neighbourhood average
        </span>
      </div>
    </div>
  )
}

export default function PriceAnalyzer({ listing }) {
  const [analysis, setAnalysis] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    getPriceAnalysis(listing.id)
      .then((data) => !cancelled && setAnalysis(data))
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [listing.id, listing.updated_at])

  if (error) return <Alert>{error}</Alert>
  if (!analysis) {
    return (
      <div className="grid h-32 place-items-center text-ink-soft" role="status">
        <LoaderCircle className="size-5 animate-spin" aria-label="Loading price analysis" />
      </div>
    )
  }

  const { neighborhood: stats, verdict, difference_pct: difference } = analysis
  const kind = PROPERTY_TYPES[listing.property_type].toLowerCase()
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p>
          <span className="font-mono text-2xl font-medium">{formatTaka(analysis.price_per_sqft)}</span>
          <span className="text-ink-soft"> per sq ft</span>
        </p>
        <span className={`rounded px-2 py-1 text-xs font-semibold uppercase tracking-wide ${VERDICTS[verdict].tone}`}>
          {VERDICTS[verdict].label}
        </span>
      </div>
      {stats ? (
        <>
          <p className="mt-2 text-sm text-ink-soft">
            {difference === 0 ? 'Exactly' : `${Math.abs(difference)}% ${difference > 0 ? 'above' : 'below'}`} the{' '}
            {formatTaka(stats.average_ppsf)}/sq ft average of {stats.count} {kind}
            {stats.count === 1 ? '' : 's'} listed within {stats.radius_km} km (median {formatTaka(stats.median_ppsf)}).
          </p>
          <PriceStrip ppsf={analysis.price_per_sqft} stats={stats} />
          <h3 className="mt-6 text-sm font-semibold">Nearest comparable listings</h3>
          <ul className="mt-2 divide-y divide-rule text-sm">
            {analysis.comparables.map((comp) => (
              <li key={comp.id} className="flex items-center justify-between gap-3 py-2">
                <Link to={`/sale/${comp.id}`} className="min-w-0 truncate hover:underline">
                  {comp.title}
                </Link>
                <span className="shrink-0 text-right">
                  <span className="font-mono">{formatTaka(comp.price_per_sqft)}</span>
                  <span className="text-ink-soft"> · {comp.distance_km} km</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-2 text-sm text-ink-soft">No other {kind}s are listed within 10 km yet, so there's nothing to compare against.</p>
      )}
    </div>
  )
}
