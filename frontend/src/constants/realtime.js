import { Bell, CalendarClock, HandCoins, MessageCircle, QrCode } from 'lucide-react'

// One icon and accent per notification type, used by the bell, the toasts and the chat.
export const NOTIFICATION_KINDS = {
  NEW_MESSAGE: { icon: MessageCircle, accent: 'text-tag-bachelor' },
  VISIT_SCHEDULED: { icon: CalendarClock, accent: 'text-gate' },
  VISIT_STATUS_CHANGED: { icon: CalendarClock, accent: 'text-gate' },
  OFFER_UPDATE: { icon: HandCoins, accent: 'text-[#8a6410]' },
  QR_UPDATE: { icon: QrCode, accent: 'text-ink' },
}
export const notificationKind = (type) => NOTIFICATION_KINDS[type] ?? { icon: Bell, accent: 'text-ink' }

export const VISIT_CARD_STATUS = {
  PENDING: { label: 'Waiting for owner', tone: 'border-brass text-[#8a6410]' },
  APPROVED: { label: 'Approved', tone: 'border-gate text-gate' },
  RESCHEDULE_PROPOSED: { label: 'New time proposed', tone: 'border-tag-bachelor text-tag-bachelor' },
  DECLINED: { label: 'Declined', tone: 'border-tag-owner text-tag-owner' },
  CANCELLED: { label: 'Cancelled', tone: 'border-ink-soft text-ink-soft' },
}

export const RENT_OFFER_STATUS = {
  AWAITING_OWNER: { label: 'Waiting for owner', tone: 'text-[#8a6410] border-brass' },
  AWAITING_TENANT: { label: 'Waiting for tenant', tone: 'text-[#8a6410] border-brass' },
  ACCEPTED: { label: 'Terms accepted', tone: 'text-gate border-gate' },
  REJECTED: { label: 'Declined', tone: 'text-tag-owner border-tag-owner' },
  WITHDRAWN: { label: 'Withdrawn', tone: 'text-ink-soft border-ink-soft' },
  CLOSED: { label: 'Closed', tone: 'text-ink-soft border-ink-soft' },
}

// Whose move it is on an offer card: the lister's (seller/owner) or the other side's (buyer/tenant).
export const LISTER_TURN = ['AWAITING_SELLER', 'AWAITING_OWNER']
export const COUNTERPARTY_TURN = ['AWAITING_BUYER', 'AWAITING_TENANT']

export const QR_CARD_STATUS = {
  ACTIVE: { label: 'Ready to scan', tone: 'border-gate text-gate' },
  CONFIRMED: { label: 'Deal confirmed', tone: 'border-gate text-gate' },
  EXPIRED: { label: 'Expired', tone: 'border-ink-soft text-ink-soft' },
  REVOKED: { label: 'Replaced', tone: 'border-ink-soft text-ink-soft' },
}

const clock = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
export const clockTime = (iso) => clock.format(new Date(iso))

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto', style: 'short' })
const shortDate = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' })

// "just now", "5 min. ago", "3 hr. ago", "yesterday", then a date.
export function timeAgo(iso) {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 45) return 'just now'
  if (seconds < 3600) return relative.format(-Math.round(seconds / 60), 'minute')
  if (seconds < 86400) return relative.format(-Math.round(seconds / 3600), 'hour')
  if (seconds < 172800) return relative.format(-1, 'day')
  return shortDate.format(new Date(iso))
}

// Separators in the message stream: "Today", "Yesterday", or the date.
export function dayHeading(iso) {
  const day = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (day.toDateString() === today.toDateString()) return 'Today'
  if (day.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }).format(day)
}

// A card's visit slot in Dhaka time: "Tue 3 Nov, 10:30 AM".
export function visitSlotLabel(startsAt) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Dhaka',
  }).format(new Date(startsAt))
}
