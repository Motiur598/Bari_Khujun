import { Trash2, X } from 'lucide-react'
import { CATEGORIES, MAX_COMPARE } from '../../constants/rentals.js'
import { useCompare } from '../../context/CompareContext.jsx'

export default function CompareTray() {
  const { items, remove, clear, open } = useCompare()
  if (items.length === 0) return null

  const slots = Array.from({ length: MAX_COMPARE }, (_, index) => items[index])

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1200] flex justify-center px-4">
      <section
        aria-label="Comparison tray"
        className="pointer-events-auto flex w-full max-w-3xl items-center gap-3 rounded-xl bg-ink py-2.5 pl-4 pr-2.5 text-white shadow-2xl"
      >
        <p className="shrink-0 text-sm font-medium sm:hidden">
          {items.length} of {MAX_COMPARE} picked
        </p>
        <ul className="hidden min-w-0 flex-1 gap-2 sm:flex">
          {slots.map((item, index) =>
            item ? (
              <li key={item.id} className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md bg-white/10 py-1.5 pl-2 pr-1">
                <span
                  aria-hidden="true"
                  className="size-2.5 shrink-0 rounded-full"
                  style={{ background: CATEGORIES[item.category].pin }}
                />
                <span className="truncate text-xs font-medium" title={item.title}>
                  {item.title}
                </span>
                <button
                  type="button"
                  onClick={() => remove(item.id)}
                  aria-label={`Remove ${item.title} from comparison`}
                  className="ml-auto shrink-0 rounded p-0.5 text-white/70 hover:bg-white/20 hover:text-white"
                >
                  <X className="size-3.5" aria-hidden="true" />
                </button>
              </li>
            ) : (
              <li
                key={`slot-${index}`}
                className="flex flex-1 items-center justify-center rounded-md border border-dashed border-white/25 py-1.5 text-xs text-white/50"
              >
                Empty
              </li>
            ),
          )}
        </ul>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={open}
            disabled={items.length < 2}
            title={items.length < 2 ? 'Pick at least 2 places' : undefined}
            className="rounded-md bg-gate px-3 py-2 text-sm font-semibold text-white transition-opacity hover:bg-gate-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            {items.length < 2 ? 'Pick 1 more' : `Compare ${items.length}`}
          </button>
          <button
            type="button"
            onClick={clear}
            aria-label="Clear comparison"
            title="Clear comparison"
            className="rounded-md p-2 text-white/70 hover:bg-white/10 hover:text-white"
          >
            <Trash2 className="size-4" aria-hidden="true" />
          </button>
        </div>
      </section>
    </div>
  )
}
