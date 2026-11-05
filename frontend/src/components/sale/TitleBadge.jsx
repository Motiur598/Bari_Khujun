import { ShieldCheck } from 'lucide-react'
import { TITLE_STATUS } from '../../constants/marketplace.js'

// The public "Verified Title" stamp. Anything short of an admin approval reads as plain grey text.
export default function TitleBadge({ status, compact = false }) {
  if (status !== 'VERIFIED') {
    return compact ? null : <span className="text-sm text-ink-soft">Title not verified yet</span>
  }
  return (
    <span
      className={`inline-flex shrink-0 -rotate-2 items-center gap-1 rounded border-2 font-mono font-medium uppercase tracking-widest ${
        TITLE_STATUS.VERIFIED.stamp
      } ${compact ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-1 text-xs'}`}
    >
      <ShieldCheck className={compact ? 'size-3' : 'size-3.5'} aria-hidden="true" />
      Verified title
    </span>
  )
}
