import {
  CalendarCheck,
  CalendarClock,
  Check,
  Clock,
  Download,
  HandCoins,
  LoaderCircle,
  PartyPopper,
  QrCode,
  RefreshCw,
  Sparkles,
  X,
} from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { useEffect, useMemo, useState } from 'react'
import { downloadFile, getErrorMessage } from '../../api/client.js'
import { leasePath, scanAndConfirm } from '../../api/handshake.js'
import { cancelVisit, getDaySlots, respondToOffer, updateVisitStatus } from '../../api/marketplace.js'
import { respondToRentOffer, sendConfirmationQr } from '../../api/realtime.js'
import { OFFER_STATUS, OFFER_TYPES, VISIT_MODES, formatPrice, formatTime } from '../../constants/marketplace.js'
import {
  COUNTERPARTY_TURN,
  LISTER_TURN,
  QR_CARD_STATUS,
  RENT_OFFER_STATUS,
  VISIT_CARD_STATUS,
  visitSlotLabel,
} from '../../constants/realtime.js'
import { formatDay, formatTaka } from '../../constants/rentals.js'
import { dayLabel, upcomingDays } from '../VisitScheduler.jsx'
import { Alert, Stamp } from '../ui.jsx'

const fallbackStatus = { label: 'Closed', tone: 'border-ink-soft text-ink-soft' }

// Runs one card action at a time, keeps its error, and asks the chat to refresh afterwards (the live
// CHAT_CARD_UPDATED event usually gets there first; this covers a dropped socket).
function useCardAction(onChanged) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')
  async function run(key, action) {
    setBusy(key)
    setError('')
    try {
      const result = await action()
      onChanged()
      return result
    } catch (err) {
      setError(getErrorMessage(err))
      onChanged()
      return undefined
    } finally {
      setBusy(null)
    }
  }
  return { busy, error, run }
}

function CardButton({ busy, disabled = false, icon: Icon, tone = 'primary', type = 'button', children, ...props }) {
  const tones = {
    primary: 'bg-gate text-white hover:bg-gate-dark',
    outline: 'border border-rule bg-white text-ink hover:border-ink',
    danger: 'border border-tag-owner/40 bg-white text-tag-owner hover:bg-tag-owner/8',
  }
  return (
    <button
      type={type}
      disabled={Boolean(busy) || disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${tones[tone]}`}
      {...props}
    >
      {busy ? <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" /> : Icon && <Icon className="size-3.5" aria-hidden="true" />}
      {children}
    </button>
  )
}

function CardShell({ icon: Icon, title, status, highlight = false, children }) {
  return (
    <div className={`rounded-xl border bg-white p-4 text-ink shadow-sm ${highlight ? 'border-gate ring-1 ring-gate/30' : 'border-rule'}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-soft">
          <Icon className="size-4" aria-hidden="true" /> {title}
        </p>
        {status && <Stamp tone={status.tone}>{status.label}</Stamp>}
      </div>
      <div className="mt-3 space-y-3">{children}</div>
    </div>
  )
}

function Facts({ rows }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
      {rows.filter(Boolean).map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-ink-soft">{label}</dt>
          <dd className="text-right font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

// ================================================================ visit request

// The host picks another free slot on the listing's calendar.
function SlotPicker({ listingId, current, busy, onPick, onCancel }) {
  const days = useMemo(upcomingDays, [])
  const [day, setDay] = useState(days[0])
  const [slots, setSlots] = useState(null)
  const [picked, setPicked] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setSlots(null)
    setPicked(null)
    getDaySlots(listingId, day)
      .then((data) => !cancelled && setSlots(data.slots))
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [listingId, day])

  return (
    <div className="space-y-2 rounded-lg border border-rule bg-plaster p-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">Propose a new time</p>
      <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1" role="group" aria-label="Day">
        {days.map((iso) => (
          <button
            key={iso}
            type="button"
            aria-pressed={iso === day}
            onClick={() => setDay(iso)}
            className={`flex w-11 shrink-0 flex-col items-center rounded border py-1 text-[11px] ${
              iso === day ? 'border-ink bg-ink text-white' : 'border-rule bg-white hover:border-ink'
            }`}
          >
            <span className="opacity-70">{dayLabel(iso, { weekday: 'short' })}</span>
            <span className="text-sm font-semibold">{dayLabel(iso, { day: 'numeric' })}</span>
          </button>
        ))}
      </div>
      {slots === null ? (
        error ? <Alert>{error}</Alert> : <LoaderCircle className="mx-auto size-4 animate-spin text-ink-soft" aria-label="Loading times" />
      ) : (
        <div className="grid grid-cols-4 gap-1" role="group" aria-label="Time">
          {slots.map((slot) => (
            <button
              key={slot.starts_at}
              type="button"
              disabled={!slot.available || slot.starts_at === current}
              aria-pressed={picked === slot.starts_at}
              onClick={() => setPicked(slot.starts_at)}
              className={`rounded border px-1 py-1 font-mono text-[11px] ${
                picked === slot.starts_at
                  ? 'border-gate bg-gate text-white'
                  : slot.available
                    ? 'border-rule bg-white hover:border-gate'
                    : 'border-transparent bg-plaster text-ink-soft/50 line-through'
              }`}
            >
              {formatTime(slot.starts_at)}
            </button>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <CardButton icon={Clock} busy={busy} disabled={!picked} onClick={() => onPick(picked)}>
          {picked ? `Propose ${formatTime(picked)}` : 'Pick a time'}
        </CardButton>
        <CardButton tone="outline" onClick={onCancel}>
          Back
        </CardButton>
      </div>
    </div>
  )
}

function VisitRequestCard({ message, context, onChanged }) {
  const payload = message.action_payload
  const { busy, error, run } = useCardAction(onChanged)
  const [picking, setPicking] = useState(false)
  const isHost = context.viewer_is_lister
  const upcoming = new Date(payload.starts_at).getTime() > Date.now()
  const live = upcoming && ['PENDING', 'APPROVED', 'RESCHEDULE_PROPOSED'].includes(payload.status)
  const visitId = payload.reference_id

  const answer = (status, startsAt) => run(status, () => updateVisitStatus(visitId, status, startsAt))

  return (
    <CardShell icon={CalendarClock} title="House visit request" status={VISIT_CARD_STATUS[payload.status] ?? fallbackStatus}>
      <div>
        <p className="font-semibold">{visitSlotLabel(payload.starts_at)}</p>
        <p className="text-sm text-ink-soft">{VISIT_MODES[payload.mode] ?? 'Visit'} · 30 minutes</p>
        {payload.note && <p className="mt-1 text-sm">“{payload.note}”</p>}
      </div>
      {!upcoming && payload.status !== 'DECLINED' && payload.status !== 'CANCELLED' && (
        <p className="text-sm text-ink-soft">This visit time has passed.</p>
      )}
      {payload.status === 'RESCHEDULE_PROPOSED' && live && (
        <p className="text-sm text-ink-soft">{isHost ? 'Waiting for the visitor to accept this new time.' : 'The owner proposed this new time.'}</p>
      )}

      {live && isHost && !picking && (
        <div className="flex flex-wrap gap-2">
          {payload.status === 'PENDING' && (
            <CardButton icon={CalendarCheck} busy={busy === 'APPROVED'} onClick={() => answer('APPROVED')}>
              Approve visit time
            </CardButton>
          )}
          <CardButton icon={Clock} tone="outline" onClick={() => setPicking(true)}>
            Propose new time
          </CardButton>
          <CardButton icon={X} tone="danger" busy={busy === 'DECLINED'} onClick={() => answer('DECLINED')}>
            Decline
          </CardButton>
        </div>
      )}
      {live && isHost && picking && (
        <SlotPicker
          listingId={context.listing.id}
          current={payload.starts_at}
          busy={busy === 'RESCHEDULE_PROPOSED'}
          onCancel={() => setPicking(false)}
          onPick={async (startsAt) => {
            await answer('RESCHEDULE_PROPOSED', startsAt)
            setPicking(false)
          }}
        />
      )}
      {live && !isHost && (
        <div className="flex flex-wrap gap-2">
          {payload.status === 'RESCHEDULE_PROPOSED' && (
            <CardButton icon={Check} busy={busy === 'APPROVED'} onClick={() => answer('APPROVED')}>
              Accept new time
            </CardButton>
          )}
          <CardButton
            icon={X}
            tone="danger"
            busy={busy === 'CANCEL'}
            onClick={() => window.confirm('Cancel this visit? The time becomes free for others.') && run('CANCEL', () => cancelVisit(visitId))}
          >
            Cancel visit
          </CardButton>
        </div>
      )}
      <Alert>{error}</Alert>
    </CardShell>
  )
}

// ================================================================ offers (sale) and rent proposals

function OfferProposalCard({ message, context, onChanged }) {
  const payload = message.action_payload
  const rent = payload.kind === 'RENT'
  const { busy, error, run } = useCardAction(onChanged)
  const [countering, setCountering] = useState(false)
  const [amount, setAmount] = useState(String(payload.proposed_amount))
  const isLister = context.viewer_is_lister
  const open = LISTER_TURN.includes(payload.status) || COUNTERPARTY_TURN.includes(payload.status)
  const myTurn = isLister ? LISTER_TURN.includes(payload.status) : COUNTERPARTY_TURN.includes(payload.status)
  const status = (rent ? RENT_OFFER_STATUS : OFFER_STATUS)[payload.status] ?? fallbackStatus
  const otherSide = isLister ? (rent ? 'tenant' : 'buyer') : rent ? 'owner' : 'seller'

  const respond = (action, extra = {}) =>
    run(action, () => (rent ? respondToRentOffer : respondToOffer)(payload.reference_id, { action, ...extra }))

  async function submitCounter(event) {
    event.preventDefault()
    await respond('COUNTER', { amount: Number(amount) })
    setCountering(false)
  }

  return (
    <CardShell icon={HandCoins} title={rent ? 'Rent proposal' : OFFER_TYPES[payload.offer_type] ?? 'Offer'} status={status}>
      <div>
        <p className="font-mono text-2xl font-medium">{rent ? formatTaka(payload.proposed_amount) : formatPrice(payload.proposed_amount)}</p>
        <p className="text-sm text-ink-soft">{rent ? 'per month' : formatTaka(payload.proposed_amount)}</p>
      </div>
      <Facts
        rows={
          rent
            ? [
                payload.unit_label && ['For', payload.unit_label],
                ['Listed rent', formatTaka(payload.listed_rent)],
                ['Advance deposit', formatTaka(payload.deposit_amount)],
                ['Move-in', formatDay(payload.move_in_date)],
              ]
            : [
                ['Asking price', formatPrice(payload.asking_price)],
                payload.token_amount && ['Bayna (token)', formatTaka(payload.token_amount)],
              ]
        }
      />

      {open && myTurn && !countering && (
        <div className="flex flex-wrap gap-2">
          <CardButton icon={Check} busy={busy === 'ACCEPT'} onClick={() => respond('ACCEPT')}>
            Accept terms
          </CardButton>
          <CardButton icon={RefreshCw} tone="outline" onClick={() => setCountering(true)}>
            Counter-offer
          </CardButton>
          <CardButton icon={X} tone="danger" busy={busy === 'REJECT'} onClick={() => respond('REJECT')}>
            Decline
          </CardButton>
        </div>
      )}
      {open && myTurn && countering && (
        <form onSubmit={submitCounter} className="flex flex-wrap items-end gap-2 rounded-lg border border-rule bg-plaster p-3">
          <label className="min-w-32 flex-1 text-xs font-medium">
            {rent ? 'Your rent (৳ / month)' : 'Your price (৳)'}
            <input
              type="number"
              required
              min={1}
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              className="mt-1 w-full rounded-md border border-rule bg-white px-2 py-1.5 font-mono text-sm"
            />
          </label>
          <CardButton type="submit" icon={RefreshCw} busy={busy === 'COUNTER'}>
            Send counter
          </CardButton>
          <CardButton tone="outline" onClick={() => setCountering(false)}>
            Back
          </CardButton>
        </form>
      )}
      {open && !myTurn && <p className="text-sm text-ink-soft">Waiting for the {otherSide} to respond.</p>}
      {open && !isLister && (
        <button
          type="button"
          disabled={Boolean(busy)}
          onClick={() => respond('WITHDRAW')}
          className="text-xs font-semibold text-tag-owner hover:underline disabled:opacity-60"
        >
          Withdraw {rent ? 'proposal' : 'offer'}
        </button>
      )}
      {payload.status === 'ACCEPTED' && (
        <p className="rounded-md bg-gate/8 px-3 py-2 text-sm text-gate-dark">
          {rent
            ? isLister
              ? context.can_send_qr
                ? 'Rent agreed and the request is ready. Send the confirmation QR from the toolbar below.'
                : 'Rent agreed.'
              : 'Rent agreed. The owner can now send you the confirmation QR.'
            : 'Offer accepted. The property is now under offer.'}
        </p>
      )}
      <Alert>{error}</Alert>
    </CardShell>
  )
}

// ================================================================ handshake QR

function useCountdown(expiresAt) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!expiresAt) return undefined
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [expiresAt])
  if (!expiresAt) return null
  const seconds = Math.max(0, Math.floor((new Date(expiresAt).getTime() - now) / 1000))
  const pad = (n) => String(n).padStart(2, '0')
  return { seconds, label: `${Math.floor(seconds / 3600)}:${pad(Math.floor((seconds % 3600) / 60))}:${pad(seconds % 60)}` }
}

function QrConfirmationCard({ message, context, onChanged }) {
  const payload = message.action_payload
  const { busy, error, run } = useCardAction(onChanged)
  const countdown = useCountdown(payload.status === 'ACTIVE' ? payload.expires_at : null)
  const isOwner = context.viewer_is_lister
  // The card flips to expired on screen the moment the clock runs out; the server strips the token on next read.
  const state = payload.status === 'ACTIVE' && countdown?.seconds === 0 ? 'EXPIRED' : payload.status
  const tenantId = message.receiver_id
  const regenerate = () => run('SEND', () => sendConfirmationQr(context.listing.id, tenantId))

  if (state === 'CONFIRMED') {
    return (
      <CardShell icon={PartyPopper} title="Handshake" status={QR_CARD_STATUS.CONFIRMED} highlight>
        <div className="rounded-lg bg-gate px-4 py-3 text-white">
          <p className="font-display text-xl font-extrabold uppercase tracking-wide">Deal confirmed</p>
          <p className="text-sm text-white/85">Digital lease issued{payload.lease_number ? ` · ${payload.lease_number}` : ''}</p>
        </div>
        <Facts rows={[['Monthly rent', formatTaka(payload.agreed_rent)], ['Advance deposit', formatTaka(payload.deposit_amount)]]} />
        <CardButton
          icon={Download}
          busy={busy === 'PDF'}
          onClick={() => run('PDF', () => downloadFile(leasePath(payload.reference_id), `${payload.lease_number ?? 'lease'}.pdf`))}
        >
          Download signed lease PDF
        </CardButton>
        {!payload.lease_ready && <p className="text-xs text-ink-soft">The PDF is still being prepared; try again in a moment if it isn't ready.</p>}
        <Alert>{error}</Alert>
      </CardShell>
    )
  }

  if (state !== 'ACTIVE' || !payload.qr_token) {
    return (
      <CardShell icon={QrCode} title="Confirmation QR" status={QR_CARD_STATUS[state] ?? fallbackStatus}>
        <p className="text-sm text-ink-soft">
          {state === 'EXPIRED' ? 'This code expired before it was used.' : 'This code was replaced or the request was closed.'}{' '}
          {isOwner ? '' : 'Ask the owner to send a new one.'}
        </p>
        {isOwner && context.can_send_qr && (
          <CardButton icon={RefreshCw} busy={busy === 'SEND'} onClick={regenerate}>
            Send a new code
          </CardButton>
        )}
        <Alert>{error}</Alert>
      </CardShell>
    )
  }

  return (
    <CardShell icon={QrCode} title="Confirmation QR" status={QR_CARD_STATUS.ACTIVE} highlight>
      <div className="flex flex-col items-center gap-2">
        <div className="rounded-lg border-2 border-ink bg-white p-3">
          <QRCodeSVG value={payload.qr_token} size={168} level="M" marginSize={0} fgColor="#264076" title="Handshake code" />
        </div>
        <p className="text-xs text-ink-soft">
          Expires in <span className="font-mono font-medium text-ink">{countdown?.label}</span> · works once
        </p>
      </div>
      <Facts rows={[['Monthly rent', formatTaka(payload.agreed_rent)], ['Advance deposit', formatTaka(payload.deposit_amount)], ['Move-in', formatDay(payload.move_in_date)]]} />
      {isOwner ? (
        <>
          <p className="text-sm text-ink-soft">The tenant confirms from this card or scans it with their phone. That releases the deposit to you and issues the lease.</p>
          <CardButton icon={RefreshCw} tone="outline" busy={busy === 'SEND'} onClick={regenerate}>
            Revoke / regenerate QR
          </CardButton>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-soft">Confirming accepts these terms, releases your deposit to the owner and issues the digital lease.</p>
          <CardButton icon={Sparkles} busy={busy === 'SCAN'} onClick={() => run('SCAN', () => scanAndConfirm(payload.qr_token))}>
            Scan / confirm deal now
          </CardButton>
        </>
      )}
      <Alert>{error}</Alert>
    </CardShell>
  )
}

const CARDS = {
  VISIT_REQUEST_CARD: VisitRequestCard,
  OFFER_PROPOSAL_CARD: OfferProposalCard,
  QR_CONFIRMATION_CARD: QrConfirmationCard,
}

export default function ActionCard({ message, context, onChanged }) {
  const Card = CARDS[message.message_type]
  if (!Card || !context) return <p className="rounded-xl border border-rule bg-white px-3.5 py-2 text-sm">{message.content}</p>
  return <Card message={message} context={context} onChanged={onChanged} />
}
