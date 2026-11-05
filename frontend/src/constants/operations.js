export const INVOICE_STATUS = {
  UNPAID: { label: 'Unpaid', tone: 'border-ink-soft text-ink-soft' },
  OVERDUE: { label: 'Overdue', tone: 'border-tag-owner text-tag-owner' },
  PAYMENT_SUBMITTED: { label: 'Payment sent', tone: 'border-brass text-[#8a6410]' },
  PAID: { label: 'Paid', tone: 'border-gate text-gate' },
}

export const INVOICE_EVENTS = {
  ISSUED: 'issued the invoice',
  PAYMENT_SUBMITTED: 'sent a payment',
  PAYMENT_REJECTED: "couldn't find the payment",
  PAID: 'confirmed the payment',
}

export const TICKET_CATEGORIES = {
  PLUMBING: 'Plumbing',
  ELECTRICAL: 'Electrical',
  GAS: 'Gas line',
  APPLIANCE: 'Appliance',
  OTHER: 'Something else',
}

export const TICKET_PRIORITIES = { LOW: 'Can wait', NORMAL: 'Soon', URGENT: 'Urgent' }

export const TICKET_STEPS = [
  ['OPEN', 'Reported'],
  ['IN_PROGRESS', 'Being fixed'],
  ['RESOLVED', 'Resolved'],
]

export const ROOMS = ['Bedroom', 'Living room', 'Kitchen', 'Bathroom', 'Balcony', 'Hallway', 'Main door', 'Meter board']

// "2026-11" -> "November 2026"
export function monthLabel(period) {
  const [year, month] = period.split('-').map(Number)
  return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, 1)))
}

export function currentPeriod() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Dhaka' }).slice(0, 7)
}
