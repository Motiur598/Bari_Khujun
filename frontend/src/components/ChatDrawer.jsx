import { ArrowLeft, Check, CheckCheck, HandCoins, LoaderCircle, MessageCircle, QrCode, SendHorizontal, X } from 'lucide-react'
import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import { createOffer } from '../api/marketplace.js'
import {
  getMessages,
  getThreadContext,
  makeRentOffer,
  markThreadRead,
  sendChatMessage,
  sendConfirmationQr,
} from '../api/realtime.js'
import { DEPOSIT_METHODS, OFFER_TYPES, formatPrice } from '../constants/marketplace.js'
import { clockTime, dayHeading, timeAgo } from '../constants/realtime.js'
import { formatTaka, unitChoices, unitKey, unitLabel } from '../constants/rentals.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useRealtime } from '../context/RealtimeContext.jsx'
import ActionCard from './chat/ActionCards.jsx'
import { Alert, Button, Segmented, TextField } from './ui.jsx'

const MAX_MESSAGE = 2000

const byTime = (a, b) => (a.created_at === b.created_at ? (a.id < b.id ? -1 : 1) : a.created_at < b.created_at ? -1 : 1)

function mergeMessages(list, incoming) {
  const byId = new Map(list.map((message) => [message.id, message]))
  incoming.forEach((message) => byId.set(message.id, message))
  return [...byId.values()].sort(byTime)
}

function Avatar({ name, online }) {
  return (
    <span className="relative inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-plaster font-semibold text-ink">
      {name?.trim()?.[0]?.toUpperCase() ?? '?'}
      <span
        className={`absolute bottom-0 right-0 size-3 rounded-full border-2 border-sheet ${online ? 'bg-leaf' : 'bg-ink-soft/50'}`}
        aria-hidden="true"
      />
    </span>
  )
}

function CloseButton({ onClick }) {
  return (
    <button type="button" onClick={onClick} aria-label="Close messages" className="inline-flex size-9 items-center justify-center rounded-md text-ink-soft hover:bg-plaster hover:text-ink">
      <X className="size-5" aria-hidden="true" />
    </button>
  )
}

// ================================================================ thread list

function ThreadList({ threads, activeKey, onPick, onClose, className }) {
  const { isOnline } = useRealtime()
  return (
    <div className={`flex-col ${className}`}>
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-rule px-4">
        <h2 className="font-display text-2xl font-extrabold uppercase tracking-wide">Messages</h2>
        <span className="md:hidden">
          <CloseButton onClick={onClose} />
        </span>
      </div>
      {threads.length === 0 ? (
        <div className="p-6 text-center text-sm text-ink-soft">
          <MessageCircle className="mx-auto size-8 text-rule" aria-hidden="true" />
          <p className="mt-2 font-medium text-ink">No conversations yet.</p>
          <p className="mt-1">Open a rental or a property for sale and use “Chat with owner” to ask about it.</p>
        </div>
      ) : (
        <ul className="flex-1 overflow-y-auto">
          {threads.map((thread) => {
            const key = `${thread.property_id}:${thread.other_user.id}`
            const last = thread.last_message
            return (
              <li key={thread.thread_id}>
                <button
                  type="button"
                  onClick={() =>
                    onPick({ propertyId: thread.property_id, otherUserId: thread.other_user.id, otherName: thread.other_user.full_name, listingTitle: thread.listing?.title })
                  }
                  aria-current={key === activeKey ? 'true' : undefined}
                  className={`flex w-full gap-3 border-b border-rule px-4 py-3 text-left hover:bg-plaster ${key === activeKey ? 'bg-plaster' : ''}`}
                >
                  <Avatar name={thread.other_user.full_name} online={isOnline(thread.other_user.id, thread.other_user.online)} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className={`truncate text-sm ${thread.unread_count ? 'font-bold' : 'font-semibold'}`}>{thread.other_user.full_name}</span>
                      <span className="shrink-0 text-[11px] text-ink-soft">{timeAgo(last.created_at)}</span>
                    </span>
                    <span className="block truncate text-xs text-ink-soft">{thread.listing?.title ?? 'Listing removed'}</span>
                    <span className="mt-0.5 flex items-center justify-between gap-2">
                      <span className={`truncate text-sm ${thread.unread_count ? 'text-ink' : 'text-ink-soft'}`}>{last.content}</span>
                      {thread.unread_count > 0 && (
                        <span className="shrink-0 rounded-full bg-tag-owner px-1.5 font-mono text-[10px] font-semibold leading-4 text-white">
                          {thread.unread_count}
                          <span className="sr-only"> unread</span>
                        </span>
                      )}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// ================================================================ quick actions

function inDays(days) {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toLocaleDateString('en-CA')
}

// "Make offer" on a sale listing, "Request rent" on a rental: either way it lands in the chat as a card.
function ProposalForm({ context, onSent, onCancel }) {
  const { listing } = context
  const rent = listing.listing_mode === 'RENT'
  const asking = listing.asking_price ?? 0
  // A bachelor tenant's sublet: the proposal is for its seat or one of its rooms, listed at the seat rent (times its
  // seats, for a whole shared room).
  const choices = listing.rooms ? unitChoices({ sublet: { rooms: listing.rooms } }) : []
  const listedRent = (choice) => (choice ? listing.rooms.find((room) => room.id === choice.room_id).seat_rent * choice.seats : listing.effective_rent)
  const [unit, setUnit] = useState(choices[0] ?? null)
  const [form, setForm] = useState({
    offer_type: 'PURCHASE',
    amount: String(rent ? listedRent(unit) : asking),
    token_amount: String(Math.round(asking * 0.1)),
    move_in_date: inDays(7),
    deposit_amount: String(listedRent(unit) ?? ''),
    payment_method: 'BKASH',
    payment_reference: '',
    note: '',
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    const note = form.note.trim() || null
    try {
      if (rent) {
        await makeRentOffer({
          listing_id: listing.id,
          room_id: unit?.room_id ?? null,
          whole_room: unit?.whole_room ?? false,
          amount: Number(form.amount),
          move_in_date: form.move_in_date,
          deposit_amount: Number(form.deposit_amount),
          payment_method: form.payment_method,
          payment_reference: form.payment_reference.trim(),
          note,
        })
      } else {
        await createOffer({
          listing_id: listing.id,
          offer_type: form.offer_type,
          amount: Number(form.amount),
          token_amount: form.offer_type === 'TOKEN_MONEY' ? Number(form.token_amount) : null,
          note,
        })
      }
      onSent()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="max-h-[55dvh] space-y-3 overflow-y-auto border-t border-rule bg-plaster p-4">
      <div className="flex items-center justify-between">
        <p className="font-semibold">{rent ? 'Propose your rent' : 'Make an offer'}</p>
        <button type="button" onClick={onCancel} aria-label="Close" className="text-ink-soft hover:text-ink">
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
      {rent ? (
        <>
          {unit && (
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium">For</span>
              <select
                value={unitKey(unit)}
                onChange={(event) => {
                  const next = choices.find((choice) => unitKey(choice) === event.target.value)
                  setUnit(next)
                  setForm({ ...form, amount: String(listedRent(next)), deposit_amount: String(listedRent(next)) })
                }}
                className="w-full rounded-md border border-rule bg-white px-3 py-2.5"
              >
                {choices.map((choice) => (
                  <option key={unitKey(choice)} value={unitKey(choice)}>
                    {unitLabel(choice)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <TextField
            label="Monthly rent (৳)"
            type="number"
            required
            min={1}
            value={form.amount}
            onChange={set('amount')}
            hint={`Listed at ${formatTaka(listedRent(unit))} a month`}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField label="Move-in date" type="date" required min={inDays(0)} value={form.move_in_date} onChange={set('move_in_date')} />
            <TextField label="Advance deposit paid (৳)" type="number" required min={1} value={form.deposit_amount} onChange={set('deposit_amount')} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium">Paid with</span>
              <select value={form.payment_method} onChange={set('payment_method')} className="w-full rounded-md border border-rule bg-white px-3 py-2.5">
                {Object.entries(DEPOSIT_METHODS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <TextField label="Transaction ID" required minLength={3} maxLength={60} value={form.payment_reference} onChange={set('payment_reference')} />
          </div>
          <p className="text-xs text-ink-soft">
            Send the advance first, then log it here. It is held as pending until the owner accepts, and marked for refund otherwise.
          </p>
        </>
      ) : (
        <>
          <Segmented legend="Offer type" name="chat-offer-type" value={form.offer_type} options={Object.entries(OFFER_TYPES)} onChange={(offer_type) => setForm({ ...form, offer_type })} />
          <TextField label="Your price (৳)" type="number" required min={1} value={form.amount} onChange={set('amount')} hint={`Asking ${formatPrice(asking)}`} />
          {form.offer_type === 'TOKEN_MONEY' && (
            <TextField label="Bayna (token money, ৳)" type="number" required min={1} value={form.token_amount} onChange={set('token_amount')} />
          )}
        </>
      )}
      <TextField label="Note (optional)" maxLength={500} value={form.note} onChange={set('note')} />
      <Alert>{error}</Alert>
      <Button type="submit" busy={busy} className="w-full">
        {rent ? 'Send rent proposal' : 'Send offer'}
      </Button>
    </form>
  )
}

function Toolbar({ context, onPropose, onQrSent }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { listing } = context
  // Once nothing is left to rent and no request is open, there is no code to send.
  const showQr = context.viewer_is_lister && listing.listing_mode === 'RENT' && (context.can_send_qr || listing.available)
  if (!context.can_make_offer && !showQr) return null

  async function sendQr() {
    setBusy(true)
    setError('')
    try {
      onQrSent(await sendConfirmationQr(listing.id, context.other_user.id))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const qrHint = context.open_booking
    ? `Approves the request at ${formatTaka(context.open_booking.agreed_rent)} a month and sends a single-use code (24 h).`
    : 'Available once this tenant has a rent request or an accepted rent proposal.'
  return (
    <div className="border-t border-rule px-3 pt-2">
      <div className="flex flex-wrap gap-2">
        {context.can_make_offer && (
          <button
            type="button"
            onClick={onPropose}
            className="inline-flex items-center gap-1.5 rounded-full border border-brass/60 bg-brass/10 px-3 py-1 text-xs font-semibold text-[#8a6410] hover:bg-brass/20"
          >
            <HandCoins className="size-3.5" aria-hidden="true" /> {listing.listing_mode === 'RENT' ? 'Request rent' : 'Make offer'}
          </button>
        )}
        {showQr && (
          <button
            type="button"
            onClick={sendQr}
            disabled={!context.can_send_qr || busy}
            title={qrHint}
            className="inline-flex items-center gap-1.5 rounded-full border border-gate/50 bg-gate/8 px-3 py-1 text-xs font-semibold text-gate-dark hover:bg-gate/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" /> : <QrCode className="size-3.5" aria-hidden="true" />}
            Send confirmation QR
          </button>
        )}
      </div>
      {showQr && <p className="mt-1 text-[11px] text-ink-soft">{qrHint}</p>}
      {error && (
        <div className="mt-2">
          <Alert>{error}</Alert>
        </div>
      )}
    </div>
  )
}

function Composer({ onSend }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const input = useRef(null)

  useEffect(() => input.current?.focus(), [])

  const resize = () => {
    const element = input.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 128)}px`
    element.style.overflowY = element.scrollHeight > 128 ? 'auto' : 'hidden'
  }

  async function submit(event) {
    event?.preventDefault()
    const content = text.trim()
    if (!content || busy) return
    setBusy(true)
    setError('')
    try {
      await onSend(content)
      setText('')
      requestAnimationFrame(resize)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
      input.current?.focus()
    }
  }

  return (
    <form onSubmit={submit} className="p-3">
      {error && (
        <div className="mb-2">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="flex items-end gap-2">
        <label htmlFor="chat-input" className="sr-only">
          Message
        </label>
        <textarea
          id="chat-input"
          ref={input}
          rows={1}
          maxLength={MAX_MESSAGE}
          value={text}
          placeholder="Write a message"
          onChange={(event) => {
            setText(event.target.value)
            resize()
          }}
          onKeyDown={(event) => {
            // Enter sends, Shift+Enter starts a new line (and Enter while composing Bangla input is left alone).
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              submit()
            }
          }}
          className="max-h-32 min-h-10 flex-1 resize-none overflow-hidden rounded-2xl border border-rule bg-white px-4 py-2 text-[15px] focus:border-gate focus:outline-none"
        />
        <button
          type="submit"
          disabled={busy || !text.trim()}
          aria-label="Send"
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-gate text-white hover:bg-gate-dark disabled:opacity-50"
        >
          {busy ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <SendHorizontal className="size-4" aria-hidden="true" />}
        </button>
      </div>
    </form>
  )
}

// ================================================================ one conversation

function MessageRow({ message, mine, context, onChanged }) {
  const card = message.message_type !== 'TEXT' && message.action_payload
  return (
    <li className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div className={card ? 'w-full max-w-sm' : 'max-w-[85%]'}>
        {card ? (
          <ActionCard message={message} context={context} onChanged={onChanged} />
        ) : (
          <p
            className={`whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-[15px] leading-snug ${
              mine ? 'rounded-br-sm bg-gate text-white' : 'rounded-bl-sm border border-rule bg-white'
            }`}
          >
            {message.content}
          </p>
        )}
        <p className={`mt-1 flex items-center gap-1 px-1 text-[11px] text-ink-soft ${mine ? 'justify-end' : ''}`}>
          {clockTime(message.created_at)}
          {mine &&
            (message.is_read ? (
              <CheckCheck className="size-3.5 text-tag-bachelor" role="img" aria-label="Read" />
            ) : (
              <Check className="size-3.5" role="img" aria-label="Sent" />
            ))}
        </p>
      </div>
    </li>
  )
}

function Conversation({ target, onBack, onClose }) {
  const { user } = useAuth()
  const { subscribe, markThreadSeen, isOnline, closeChat } = useRealtime()
  const { propertyId, otherUserId } = target
  const [context, setContext] = useState(null)
  const [messages, setMessages] = useState(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [proposing, setProposing] = useState(false)
  const [error, setError] = useState('')
  const scroller = useRef(null)
  const pinned = useRef(true) // keep the newest message in view unless the person scrolled up
  const keepFromBottom = useRef(null)

  const merge = useCallback((incoming) => setMessages((list) => mergeMessages(list ?? [], incoming)), [])

  const reloadContext = useCallback(
    () => getThreadContext(propertyId, otherUserId).then(setContext, (err) => setError(getErrorMessage(err))),
    [propertyId, otherUserId],
  )
  // The newest page again: after an action, or when the socket reconnects after missing events.
  const reloadLatest = useCallback(async () => {
    try {
      merge((await getMessages(propertyId, otherUserId)).items)
      markThreadSeen(propertyId, otherUserId)
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }, [propertyId, otherUserId, merge, markThreadSeen])

  const refresh = useCallback(() => {
    reloadLatest()
    reloadContext()
  }, [reloadLatest, reloadContext])

  useEffect(() => {
    let cancelled = false
    Promise.all([getThreadContext(propertyId, otherUserId), getMessages(propertyId, otherUserId)])
      .then(([ctx, page]) => {
        if (cancelled) return
        setContext(ctx)
        setMessages(page.items)
        setHasMore(page.has_more)
        markThreadSeen(propertyId, otherUserId)
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [propertyId, otherUserId, markThreadSeen])

  const readIfVisible = useCallback(() => {
    if (document.visibilityState !== 'visible') return
    markThreadRead(propertyId, otherUserId)
      .then(() => markThreadSeen(propertyId, otherUserId))
      .catch(() => {})
    setMessages((list) => list?.map((m) => (m.receiver_id === user.id ? { ...m, is_read: true } : m)) ?? list)
  }, [propertyId, otherUserId, markThreadSeen, user.id])

  useEffect(
    () =>
      subscribe((event) => {
        const message = event.message
        const inThread = message && message.property_id === propertyId && [message.sender_id, message.receiver_id].includes(otherUserId)
        switch (event.type) {
          case 'NEW_CHAT_MESSAGE':
          case 'CHAT_MESSAGE_SENT':
            if (!inThread) return
            merge([message])
            if (message.receiver_id === user.id) readIfVisible()
            if (message.message_type !== 'TEXT') reloadContext()
            break
          case 'CHAT_CARD_UPDATED':
            if (!inThread) return
            merge([message])
            reloadContext() // e.g. an accepted rent proposal makes "Send confirmation QR" available
            break
          case 'MESSAGES_READ': {
            if (event.reader_id !== otherUserId) return
            const ids = new Set(event.message_ids)
            setMessages((list) => list?.map((m) => (ids.has(m.id) ? { ...m, is_read: true, is_delivered: true } : m)) ?? list)
            break
          }
          case 'OFFLINE_SYNC_BUNDLE':
            refresh()
            break
          default:
        }
      }),
    [subscribe, propertyId, otherUserId, user.id, merge, readIfVisible, reloadContext, refresh],
  )

  // Coming back to the tab with the chat open counts as reading what arrived meanwhile.
  useEffect(() => {
    const onVisible = () => {
      if (messages?.some((m) => m.receiver_id === user.id && !m.is_read)) readIfVisible()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [messages, user.id, readIfVisible])

  useLayoutEffect(() => {
    const element = scroller.current
    if (!element) return
    if (keepFromBottom.current !== null) {
      element.scrollTop = element.scrollHeight - keepFromBottom.current
      keepFromBottom.current = null
    } else if (pinned.current) {
      element.scrollTop = element.scrollHeight
    }
  }, [messages, proposing])

  async function loadOlder() {
    const element = scroller.current
    setLoadingOlder(true)
    try {
      const page = await getMessages(propertyId, otherUserId, messages[0].id)
      keepFromBottom.current = element.scrollHeight - element.scrollTop
      merge(page.items)
      setHasMore(page.has_more)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoadingOlder(false)
    }
  }

  async function send(content) {
    pinned.current = true
    merge([await sendChatMessage({ property_id: propertyId, receiver_id: otherUserId, content })])
  }

  const other = context?.other_user
  const online = isOnline(otherUserId, other?.online ?? false)
  const listingPath = context && `/${context.listing.listing_mode === 'SALE' ? 'sale' : 'rentals'}/${context.listing.id}`

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-rule px-3 sm:px-4">
        <button type="button" onClick={onBack} aria-label="All conversations" className="inline-flex size-9 items-center justify-center rounded-md text-ink-soft hover:bg-plaster md:hidden">
          <ArrowLeft className="size-5" aria-hidden="true" />
        </button>
        <Avatar name={other?.full_name ?? target.otherName} online={online} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{other?.full_name ?? target.otherName ?? 'Conversation'}</p>
          <p className="flex items-center gap-1.5 truncate text-xs text-ink-soft">
            <span className={online ? 'font-medium text-gate' : ''}>{online ? 'Online' : 'Offline'}</span>
            {context && (
              <>
                <span aria-hidden="true">·</span>
                <Link to={listingPath} onClick={closeChat} className="truncate hover:text-ink hover:underline">
                  {context.listing.title}
                </Link>
              </>
            )}
          </p>
        </div>
        <CloseButton onClick={onClose} />
      </header>

      <div
        ref={scroller}
        onScroll={(event) => {
          const element = event.currentTarget
          pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80
        }}
        className="flex-1 overflow-y-auto bg-plaster/60 px-3 py-4 sm:px-5"
      >
        {error && <Alert>{error}</Alert>}
        {messages === null ? (
          !error && (
            <div className="grid h-full place-items-center text-ink-soft" role="status">
              <LoaderCircle className="size-6 animate-spin" aria-label="Loading messages" />
            </div>
          )
        ) : (
          <>
            {hasMore && (
              <div className="mb-3 text-center">
                <button
                  type="button"
                  onClick={loadOlder}
                  disabled={loadingOlder}
                  className="rounded-full border border-rule bg-white px-3 py-1 text-xs font-semibold text-ink-soft hover:text-ink disabled:opacity-60"
                >
                  {loadingOlder ? 'Loading…' : 'Load earlier messages'}
                </button>
              </div>
            )}
            {messages.length === 0 && (
              <p className="mx-auto mt-8 max-w-xs text-center text-sm text-ink-soft">
                Say hello and ask about {target.listingTitle ?? context?.listing.title ?? 'the place'}. Messages are kept until you both read them,
                even if one of you is offline.
              </p>
            )}
            <ol className="space-y-3" aria-live="polite" aria-label="Messages">
              {messages.map((message, index) => {
                const heading = dayHeading(message.created_at)
                const showHeading = index === 0 || heading !== dayHeading(messages[index - 1].created_at)
                return (
                  <Fragment key={message.id}>
                    {showHeading && (
                      <li className="py-1 text-center text-[11px] font-semibold uppercase tracking-widest text-ink-soft" aria-hidden="true">
                        {heading}
                      </li>
                    )}
                    <MessageRow message={message} mine={message.sender_id === user.id} context={context} onChanged={refresh} />
                  </Fragment>
                )
              })}
            </ol>
          </>
        )}
      </div>

      <div className="shrink-0 bg-sheet">
        {context && proposing ? (
          <ProposalForm
            context={context}
            onCancel={() => setProposing(false)}
            onSent={() => {
              setProposing(false)
              pinned.current = true
              refresh()
            }}
          />
        ) : (
          context && (
            <Toolbar
              context={context}
              onPropose={() => setProposing(true)}
              onQrSent={(card) => {
                pinned.current = true
                merge([card])
                reloadContext()
              }}
            />
          )
        )}
        <Composer onSend={send} />
      </div>
    </div>
  )
}

// ================================================================ the drawer

export default function ChatDrawer() {
  const { chat, closeChat, openChat, threads } = useRealtime()

  useEffect(() => {
    if (!chat.open) return undefined
    const onKey = (event) => event.key === 'Escape' && closeChat()
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = overflow
      window.removeEventListener('keydown', onKey)
    }
  }, [chat.open, closeChat])

  if (!chat.open) return null
  const { target } = chat
  const activeKey = target && `${target.propertyId}:${target.otherUserId}`

  return (
    <div className="fixed inset-0 z-[1200]">
      <div className="absolute inset-0 bg-ink/30" onClick={closeChat} aria-hidden="true" />
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Messages"
        className="absolute inset-y-0 right-0 flex w-full max-w-4xl bg-sheet shadow-2xl motion-safe:animate-[drawer-in_200ms_ease-out]"
      >
        <ThreadList
          threads={threads}
          activeKey={activeKey}
          onPick={openChat}
          onClose={closeChat}
          className={`${target ? 'hidden md:flex' : 'flex'} w-full md:w-72 md:shrink-0 md:border-r md:border-rule`}
        />
        {target ? (
          <Conversation key={activeKey} target={target} onBack={() => openChat(null)} onClose={closeChat} />
        ) : (
          <div className="hidden flex-1 flex-col md:flex">
            <div className="flex h-16 shrink-0 items-center justify-end border-b border-rule px-4">
              <CloseButton onClick={closeChat} />
            </div>
            <div className="grid flex-1 place-items-center text-sm text-ink-soft">Pick a conversation to read it.</div>
          </div>
        )}
      </section>
    </div>
  )
}
