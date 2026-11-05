import { BedSingle } from 'lucide-react'
import { formatTaka } from '../../constants/rentals.js'

// One bed per seat: filled beds are taken, outlined violet beds are free.
export function SeatPlan({ total, available }) {
  const taken = total - available
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label={`${available} of ${total} seats free`}>
      {Array.from({ length: total }, (_, index) => {
        const free = index >= taken
        return (
          <li
            key={index}
            className={`grid size-10 place-items-center rounded-md border-2 ${
              free ? 'border-tag-seat bg-white text-tag-seat' : 'border-transparent bg-ink/10 text-ink-soft'
            }`}
            title={free ? 'Free seat' : 'Taken'}
          >
            <BedSingle className="size-5" aria-hidden="true" />
          </li>
        )
      })}
    </ol>
  )
}

// The flat's monthly costs divided across seats, as calculated by the server (or the editor's preview).
export default function SeatSplit({ pricing, totalSeats, split }) {
  const rows = [
    ['Rent', pricing.base_rent, split.per_seat_rent],
    ['Service charge', pricing.service_charge, split.per_seat_service_charge],
    ['Utilities (estimate)', pricing.utility_estimate, split.per_seat_utility],
    ['Maid (estimate)', pricing.maid_estimate, split.per_seat_maid],
  ]
  const flatTotal = rows.reduce((sum, [, flat]) => sum + Number(flat || 0), 0)

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-rule text-left text-xs uppercase tracking-wider text-ink-soft">
          <th scope="col" className="py-2 font-medium">
            Monthly
          </th>
          <th scope="col" className="py-2 text-right font-medium">
            Whole flat
          </th>
          <th scope="col" className="py-2 text-right font-medium">
            ÷ {totalSeats} seats
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, flat, perSeat]) => (
          <tr key={label} className="border-b border-rule">
            <th scope="row" className="py-2 text-left font-normal">
              {label}
            </th>
            <td className="py-2 text-right font-mono text-ink-soft">{formatTaka(Number(flat || 0))}</td>
            <td className="py-2 text-right font-mono">{formatTaka(perSeat)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row" className="pt-3 text-left font-semibold">
            Each tenant pays
          </th>
          <td className="pt-3 text-right font-mono text-ink-soft">{formatTaka(flatTotal)}</td>
          <td className="pt-3 text-right font-mono text-base font-semibold text-tag-seat">{formatTaka(split.per_seat_total)}</td>
        </tr>
      </tfoot>
    </table>
  )
}
