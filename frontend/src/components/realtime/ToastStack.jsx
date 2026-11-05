import { BellRing, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { notificationKind } from '../../constants/realtime.js'
import { useRealtime } from '../../context/RealtimeContext.jsx'

const TOAST_MS = 6_000

function Toast({ toast, onDismiss }) {
  const timer = useRef(null)
  const { icon: Icon, accent } = toast.kind === 'SUMMARY' ? { icon: BellRing, accent: 'text-gate' } : notificationKind(toast.kind)

  // Six seconds on screen; hovering or focusing it holds it there.
  const start = () => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => onDismiss(toast.id), TOAST_MS)
  }
  const hold = () => clearTimeout(timer.current)
  useEffect(() => {
    start()
    return hold
  }, [])

  return (
    <li
      onMouseEnter={hold}
      onMouseLeave={start}
      onFocus={hold}
      onBlur={start}
      className="pointer-events-auto flex gap-3 rounded-lg border border-rule bg-sheet p-3 pr-2 shadow-lg motion-safe:animate-[toast-in_220ms_ease-out]"
    >
      <Icon className={`mt-0.5 size-5 shrink-0 ${accent}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{toast.title}</p>
        {toast.body && <p className="mt-0.5 line-clamp-3 text-sm text-ink-soft">{toast.body}</p>}
        {toast.actions?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {toast.actions.map((action) => (
              <button
                key={action.label}
                type="button"
                onClick={() => {
                  action.run()
                  onDismiss(toast.id)
                }}
                className="rounded-md bg-gate px-2.5 py-1 text-xs font-semibold text-white hover:bg-gate-dark"
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss"
        className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-ink-soft hover:text-ink"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </li>
  )
}

// Live alerts, stacked in the top-right corner under the header, newest at the bottom.
export default function ToastStack() {
  const { toasts, dismissToast } = useRealtime()
  return (
    <ol
      aria-live="polite"
      aria-label="Notifications"
      className="pointer-events-none fixed right-4 top-20 z-[1300] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
    >
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={dismissToast} />
      ))}
    </ol>
  )
}
