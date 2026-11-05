import { LoaderCircle } from 'lucide-react'
import { useId } from 'react'
import logo from '../assets/bari-khujun-logo.png'

export function TextField({ label, hint, className = '', ...inputProps }) {
  const id = useId()
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        className="w-full rounded-md border border-rule bg-white px-3 py-2.5 text-ink placeholder:text-ink-soft/60 focus:border-gate focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-gate"
        {...inputProps}
      />
      {hint && <p className="mt-1 text-xs text-ink-soft">{hint}</p>}
    </div>
  )
}

export function Button({ busy = false, disabled = false, children, className = '', ...props }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-md bg-gate px-4 py-2.5 font-semibold text-white transition-colors hover:bg-gate-dark disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      disabled={busy || disabled}
      {...props}
    >
      {busy && <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />}
      {children}
    </button>
  )
}

export function Alert({ tone = 'error', children }) {
  if (!children) return null
  const tones = {
    error: 'border-tag-owner/40 bg-tag-owner/8 text-tag-owner',
    success: 'border-gate/40 bg-gate/8 text-gate-dark',
    info: 'border-rule bg-sheet text-ink',
  }
  return (
    <p role={tone === 'error' ? 'alert' : 'status'} className={`rounded-md border px-3 py-2 text-sm ${tones[tone]}`}>
      {children}
    </p>
  )
}

// Radio group drawn as a segmented control. `options` is a list of [value, label] pairs.
export function Segmented({ legend, name, value, options, onChange, className = '' }) {
  return (
    <fieldset className={className}>
      <legend className="mb-1.5 text-sm font-medium">{legend}</legend>
      <div
        className="grid gap-1 rounded-md border border-rule bg-plaster p-1"
        style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
      >
        {options.map(([optionValue, label]) => (
          <label key={String(optionValue)} className="cursor-pointer">
            <input
              type="radio"
              name={name}
              checked={value === optionValue}
              onChange={() => onChange(optionValue)}
              className="peer sr-only"
            />
            <span className="block rounded px-2 py-1.5 text-center text-sm font-medium text-ink-soft peer-checked:bg-white peer-checked:text-ink peer-checked:shadow-sm peer-focus-visible:outline-2 peer-focus-visible:outline-leaf">
              {label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export function Checkbox({ label, checked, onChange }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-medium">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 accent-gate"
      />
      {label}
    </label>
  )
}

// Rubber-stamp status label, the same device the KYC card uses.
export function Stamp({ tone, children }) {
  return (
    <span className={`inline-block shrink-0 -rotate-2 rounded border-2 px-1.5 py-0.5 font-mono text-[11px] font-medium uppercase tracking-widest ${tone}`}>
      {children}
    </span>
  )
}

export function EmptyState({ title, children }) {
  return (
    <div className="rounded-xl border border-dashed border-rule p-8 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 text-sm text-ink-soft">{children}</div>}
    </div>
  )
}

export function FormSection({ title, description, children }) {
  return (
    <section className="rounded-xl border border-rule bg-sheet p-5 sm:p-7">
      <h2 className="font-display text-2xl font-extrabold uppercase tracking-wide">{title}</h2>
      {description && <p className="mt-1 text-sm text-ink-soft">{description}</p>}
      <div className="mt-5 space-y-5">{children}</div>
    </section>
  )
}

// The Bari Khujun logo. Its background is transparent, but the navy half needs a light backdrop.
export function Wordmark({ className = 'h-10 sm:h-12' }) {
  return <img src={logo} alt="Bari Khujun" width="480" height="176" className={`${className} w-auto`} />
}
