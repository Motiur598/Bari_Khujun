import { Check, Columns3 } from 'lucide-react'
import { MAX_COMPARE } from '../../constants/rentals.js'
import { useCompare } from '../../context/CompareContext.jsx'

export default function CompareToggle({ listing, className = '' }) {
  const { has, toggle, isFull } = useCompare()
  const picked = has(listing.id)
  const blocked = !picked && isFull

  return (
    <button
      type="button"
      onClick={() => toggle(listing)}
      disabled={blocked}
      aria-pressed={picked}
      title={blocked ? `You can compare up to ${MAX_COMPARE} places` : undefined}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        picked ? 'border-ink bg-ink text-white' : 'border-rule bg-white text-ink hover:border-ink'
      } ${className}`}
    >
      {picked ? <Check className="size-3.5" aria-hidden="true" /> : <Columns3 className="size-3.5" aria-hidden="true" />}
      {picked ? 'In comparison' : blocked ? 'Comparison full' : 'Compare'}
    </button>
  )
}
