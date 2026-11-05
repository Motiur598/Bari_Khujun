import { useId, useState } from 'react'
import { emi, formatPrice } from '../../constants/marketplace.js'
import { formatTaka } from '../../constants/rentals.js'

function Slider({ label, value, display, min, max, step, onChange }) {
  const id = useId()
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <span className="font-mono text-sm">{display}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1.5 w-full accent-gate"
      />
    </div>
  )
}

export default function EmiCalculator({ price }) {
  const [downPct, setDownPct] = useState(30)
  const [rate, setRate] = useState(9.5)
  const [years, setYears] = useState(20)

  const downPayment = Math.round((price * downPct) / 100)
  const loan = price - downPayment
  const { monthly, totalInterest, totalPayment } = emi(loan, rate, years)
  const interestShare = totalPayment ? (totalInterest / totalPayment) * 100 : 0

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div className="space-y-5">
        <Slider
          label="Down payment"
          value={downPct}
          display={`${downPct}% · ${formatPrice(downPayment)}`}
          min={10}
          max={90}
          step={5}
          onChange={setDownPct}
        />
        <Slider
          label="Interest rate"
          value={rate}
          display={`${rate.toFixed(2)}% a year`}
          min={5}
          max={16}
          step={0.25}
          onChange={setRate}
        />
        <Slider
          label="Loan tenure"
          value={years}
          display={`${years} year${years === 1 ? '' : 's'}`}
          min={1}
          max={25}
          step={1}
          onChange={setYears}
        />
      </div>

      <div className="rounded-lg bg-ink p-5 text-white">
        <p className="text-xs font-medium uppercase tracking-widest text-white/60">Monthly instalment</p>
        <p className="mt-1 font-mono text-3xl font-medium" aria-live="polite">
          {formatTaka(Math.round(monthly))}
        </p>
        <div className="mt-4 flex h-2 overflow-hidden rounded-full" aria-hidden="true">
          <div className="bg-white/80" style={{ width: `${100 - interestShare}%` }} />
          <div className="bg-leaf" style={{ width: `${interestShare}%` }} />
        </div>
        <dl className="mt-4 space-y-1.5 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="flex items-center gap-1.5 text-white/70">
              <span className="size-2 rounded-full bg-white/80" aria-hidden="true" /> Loan amount
            </dt>
            <dd className="font-mono">{formatTaka(loan)}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="flex items-center gap-1.5 text-white/70">
              <span className="size-2 rounded-full bg-leaf" aria-hidden="true" /> Total interest
            </dt>
            <dd className="font-mono">{formatTaka(Math.round(totalInterest))}</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-white/15 pt-1.5">
            <dt className="text-white/70">Paid to the bank</dt>
            <dd className="font-mono">{formatTaka(Math.round(totalPayment))}</dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-white/60">An estimate on a reducing balance. Your bank's rate and fees decide the real figure.</p>
      </div>
    </div>
  )
}
