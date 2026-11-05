import { ArrowUpDown, List, Map as MapIcon, SlidersHorizontal, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { CATEGORIES } from '../../constants/rentals.js'

export const FLOOR_RANGES = {
  low: { label: 'Ground to 3rd', min_floor: 0, max_floor: 3 },
  mid: { label: '4th to 8th', min_floor: 4, max_floor: 8 },
  high: { label: '9th and up', min_floor: 9 },
}

export const fieldClass =
  'h-9 rounded-md border border-rule bg-white px-2 text-sm text-ink focus:border-gate focus:outline-none focus-visible:outline-2 focus-visible:outline-gate'

export function Field({ label, children, className = '' }) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      <span className="text-xs font-medium text-ink-soft">{label}</span>
      {children}
    </label>
  )
}

// Commits on blur or Enter so every keystroke doesn't trigger a search.
export function AmountInput({ value, onCommit, placeholder, label, step = 500 }) {
  const [draft, setDraft] = useState(value ?? '')
  useEffect(() => setDraft(value ?? ''), [value])
  const commit = () => {
    const clean = draft === '' ? '' : String(Math.max(0, Math.round(Number(draft)) || 0))
    if (clean !== (value ?? '')) onCommit(clean)
  }
  return (
    <input
      type="number"
      inputMode="numeric"
      min={0}
      step={step}
      aria-label={label}
      placeholder={placeholder}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => event.key === 'Enter' && commit()}
      className={`${fieldClass} w-24`}
    />
  )
}

export function ToggleChip({ pressed, onChange, icon: Icon, children }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onChange(!pressed)}
      className={`inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm font-medium transition-colors ${
        pressed ? 'border-ink bg-ink text-white' : 'border-rule bg-white text-ink hover:border-ink'
      }`}
    >
      <Icon className="size-4" aria-hidden="true" />
      {children}
    </button>
  )
}

function CategorySwitch({ value, onChange }) {
  const options = [['', 'All', 'All', null], ...Object.entries(CATEGORIES).map(([key, c]) => [key, c.label, c.short, c.pin])]
  return (
    <fieldset className="flex w-full flex-col gap-1 sm:w-auto">
      <legend className="mb-1 text-xs font-medium text-ink-soft">Looking for</legend>
      <div className="grid grid-cols-4 gap-1 rounded-md border border-rule bg-plaster p-1">
        {options.map(([key, label, short, pin]) => (
          <label key={key || 'all'} className="cursor-pointer">
            <input
              type="radio"
              name="category"
              value={key}
              checked={value === key}
              onChange={() => onChange(key)}
              className="peer sr-only"
            />
            <span className="flex h-7 items-center justify-center gap-1.5 whitespace-nowrap rounded px-2 text-sm font-medium text-ink-soft peer-checked:bg-white peer-checked:text-ink peer-checked:shadow-sm peer-focus-visible:outline-2 peer-focus-visible:outline-leaf">
              {pin && <span aria-hidden="true" className="size-2 shrink-0 rounded-full" style={{ background: pin }} />}
              <span className="sm:hidden">{short}</span>
              <span className="hidden sm:inline">{label}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

// Filters within the target area (the area itself is picked with ShiftingAreaPicker).
export default function FilterBar({ params, update, reset, activeCount, view, onViewChange }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border-b border-rule bg-sheet">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3 px-4 py-3 sm:px-6">
        <CategorySwitch value={params.get('category') ?? ''} onChange={(category) => update({ category })} />

        <div className="flex w-full items-center justify-between gap-2 lg:hidden">
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
            aria-controls="more-filters"
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-rule bg-white px-3 text-sm font-medium"
          >
            <SlidersHorizontal className="size-4" aria-hidden="true" />
            Filters{activeCount > 0 && ` (${activeCount})`}
          </button>
          <div className="grid grid-cols-2 gap-1 rounded-md border border-rule bg-plaster p-1" role="group" aria-label="View">
            {[
              ['list', 'List', List],
              ['map', 'Map', MapIcon],
            ].map(([key, label, Icon]) => (
              <button
                key={key}
                type="button"
                aria-pressed={view === key}
                onClick={() => onViewChange(key)}
                className={`inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-sm font-medium ${
                  view === key ? 'bg-white text-ink shadow-sm' : 'text-ink-soft'
                }`}
              >
                <Icon className="size-4" aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>
        </div>

        <div id="more-filters" className={`${expanded ? 'flex' : 'hidden'} w-full flex-wrap items-end gap-x-4 gap-y-3 lg:flex lg:w-auto`}>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-ink-soft">Rent budget (৳ per month)</span>
            <div className="flex items-center gap-1.5">
              <AmountInput
                label="Minimum rent"
                placeholder="Min"
                value={params.get('min_rent')}
                onCommit={(min_rent) => update({ min_rent })}
              />
              <span className="text-ink-soft">–</span>
              <AmountInput
                label="Maximum rent"
                placeholder="Max"
                value={params.get('max_rent')}
                onCommit={(max_rent) => update({ max_rent })}
              />
            </div>
          </div>

          <Field label="Floor">
            <select
              value={params.get('floor') ?? ''}
              onChange={(event) => update({ floor: event.target.value })}
              className={`${fieldClass} w-36`}
            >
              <option value="">Any floor</option>
              {Object.entries(FLOOR_RANGES).map(([key, range]) => (
                <option key={key} value={key}>
                  {range.label}
                </option>
              ))}
            </select>
          </Field>

          <div className="flex gap-2">
            <ToggleChip pressed={params.has('elevator')} onChange={(on) => update({ elevator: on })} icon={ArrowUpDown}>
              Lift
            </ToggleChip>
            <ToggleChip pressed={params.has('generator')} onChange={(on) => update({ generator: on })} icon={Zap}>
              Generator
            </ToggleChip>
          </div>

          <Field label="Meter">
            <select
              value={params.get('meter_type') ?? ''}
              onChange={(event) => update({ meter_type: event.target.value })}
              className={`${fieldClass} w-32`}
            >
              <option value="">Any meter</option>
              <option value="PREPAID">Prepaid</option>
              <option value="POSTPAID">Postpaid</option>
            </select>
          </Field>

          <Field label="Smoking">
            <select
              value={params.get('smoking_allowed') ?? ''}
              onChange={(event) => update({ smoking_allowed: event.target.value })}
              className={`${fieldClass} w-32`}
            >
              <option value="">No preference</option>
              <option value="true">Allowed</option>
              <option value="false">Not allowed</option>
            </select>
          </Field>

          {activeCount > 0 && (
            <button type="button" onClick={reset} className="h-9 px-1 text-sm font-semibold text-gate hover:underline">
              Clear filters
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
