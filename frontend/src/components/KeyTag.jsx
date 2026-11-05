import { ROLES } from '../constants/roles.js'

// A key tag with a green eyelet: the visual stand-in for a role throughout the app.
export default function KeyTag({ role, active = true, className = '' }) {
  const { label, icon: Icon, tagIdle, tagActive } = ROLES[role]
  return (
    <span
      className={`relative flex origin-top flex-col items-center gap-1.5 rounded-lg border-2 px-1 pb-3 pt-5 ${active ? tagActive : `${tagIdle} bg-sheet`} ${className}`}
    >
      <span aria-hidden="true" className="absolute top-1.5 size-2.5 rounded-full border-2 border-leaf bg-plaster" />
      <Icon className="size-5" aria-hidden="true" />
      <span className="font-display text-base font-semibold uppercase sm:text-lg sm:tracking-wide">{label}</span>
    </span>
  )
}
