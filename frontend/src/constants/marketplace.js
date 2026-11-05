export const PROPERTY_TYPES = { APARTMENT: 'Apartment', HOUSE: 'House' }

export const HANDOVER = { READY_FLAT: 'Ready to move in', UNDER_CONSTRUCTION: 'Under construction' }

export const SALE_PIN = '#c2412d'

export const TITLE_DOCS = {
  MUTATION_RECORD: { label: 'Mutation record', help: 'Namjari / khatian showing the seller as the recorded owner.' },
  DEED_SUMMARY: { label: 'Deed summary', help: 'The registered sale or gift deed, or a certified summary of it.' },
  TAX_RECEIPT: { label: 'Tax receipt', help: 'Latest land development tax (khajna) or holding tax receipt.' },
}

export const TITLE_STATUS = {
  NOT_SUBMITTED: { label: 'Title not submitted', stamp: 'border-ink-soft text-ink-soft' },
  PENDING: { label: 'Title under review', stamp: 'border-brass text-[#8a6410]' },
  VERIFIED: { label: 'Verified title', stamp: 'border-gate text-gate' },
  REJECTED: { label: 'Title rejected', stamp: 'border-tag-owner text-tag-owner' },
}

export const OFFER_TYPES = { PURCHASE: 'Purchase offer', TOKEN_MONEY: 'Token money (bayna)' }

export const OFFER_STATUS = {
  AWAITING_SELLER: { label: 'Waiting for seller', tone: 'text-[#8a6410] border-brass' },
  AWAITING_BUYER: { label: 'Waiting for buyer', tone: 'text-[#8a6410] border-brass' },
  ACCEPTED: { label: 'Accepted', tone: 'text-gate border-gate' },
  REJECTED: { label: 'Rejected', tone: 'text-tag-owner border-tag-owner' },
  WITHDRAWN: { label: 'Withdrawn', tone: 'text-ink-soft border-ink-soft' },
  CLOSED: { label: 'Closed', tone: 'text-ink-soft border-ink-soft' },
}

export const OFFER_EVENTS = {
  OFFERED: 'made an offer',
  COUNTERED: 'countered',
  ACCEPTED: 'accepted',
  REJECTED: 'rejected',
  WITHDRAWN: 'withdrew',
  CLOSED: 'closed the offer',
}

export const VISIT_MODES = { IN_PERSON: 'In person', VIDEO: 'Video walkthrough' }

export const DEPOSIT_METHODS = {
  BKASH: 'bKash',
  NAGAD: 'Nagad',
  ROCKET: 'Rocket',
  BANK_TRANSFER: 'Bank transfer',
  CASH: 'Cash',
}

export const BOOKING_STATUS = {
  PENDING_OWNER: { label: 'Waiting for owner', tone: 'text-[#8a6410] border-brass' },
  APPROVED: { label: 'Approved · handshake due', tone: 'text-gate border-gate' },
  CONFIRMED: { label: 'Confirmed', tone: 'text-gate border-gate' },
  REJECTED: { label: 'Declined', tone: 'text-tag-owner border-tag-owner' },
  CANCELLED: { label: 'Cancelled', tone: 'text-ink-soft border-ink-soft' },
  ENDED: { label: 'Lease ended', tone: 'text-ink-soft border-ink-soft' },
}

export const ESCROW_STATUS = {
  PENDING_OWNER: 'Deposit logged, waiting for owner',
  HELD: 'Deposit held in escrow',
  RELEASED: 'Deposit released to owner',
  REFUNDED: 'Deposit to be refunded',
  SPLIT: 'Deposit split by arbitration',
}

// "৳2.6 crore", "৳85 lakh", "৳4,400": how people quote property prices in Bangladesh.
export function formatPrice(amount) {
  if (amount >= 10000000) return `৳${+(amount / 10000000).toFixed(2)} crore`
  if (amount >= 100000) return `৳${+(amount / 100000).toFixed(1)} lakh`
  return `৳${new Intl.NumberFormat('en-IN').format(amount)}`
}

// Standard reducing-balance EMI: P·r·(1+r)^n / ((1+r)^n − 1), with r the monthly rate.
export function emi(principal, annualRatePct, years) {
  const months = Math.round(years * 12)
  if (principal <= 0 || months <= 0) return { monthly: 0, totalInterest: 0, totalPayment: 0 }
  const rate = annualRatePct / 12 / 100
  const monthly = rate === 0 ? principal / months : (principal * rate * (1 + rate) ** months) / ((1 + rate) ** months - 1)
  const totalPayment = monthly * months
  return { monthly, totalInterest: totalPayment - principal, totalPayment }
}

export function formatDateTime(iso) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))
}

export function formatTime(iso) {
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Dhaka' }).format(new Date(iso))
}
