import { Bell, CheckCheck, MessageCircle } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { notificationKind, timeAgo } from '../../constants/realtime.js'
import { useRealtime } from '../../context/RealtimeContext.jsx'

function Badge({ count, label }) {
  if (!count) return null
  return (
    <span className="absolute -right-0.5 -top-0.5 min-w-4.5 rounded-full bg-tag-owner px-1 text-center font-mono text-[10px] font-semibold leading-4.5 text-white">
      {count > 99 ? '99+' : count}
      <span className="sr-only"> {label}</span>
    </span>
  )
}

const iconButton = 'relative inline-flex size-10 items-center justify-center rounded-md text-ink-soft hover:bg-plaster hover:text-ink'

// Opens the chat drawer on the thread list; the badge counts unread messages across every thread.
export function MessagesButton() {
  const { unreadMessages, openChat } = useRealtime()
  return (
    <button type="button" onClick={() => openChat(null)} className={iconButton} aria-label="Messages" title="Messages">
      <MessageCircle className="size-5" aria-hidden="true" />
      <Badge count={unreadMessages} label="unread messages" />
    </button>
  )
}

const CONNECTION_NOTE = {
  connecting: 'Connecting…',
  offline: 'Offline. Reconnecting, and anything new will arrive when you are back.',
}

export default function NotificationBell() {
  const { notifications, unreadNotifications, connection, openNotification, markAllNotificationsRead } = useRealtime()
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return undefined
    const onPointer = (event) => root.current && !root.current.contains(event.target) && setOpen(false)
    const onKey = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label="Notifications"
        title="Notifications"
        className={iconButton}
      >
        <Bell className="size-5" aria-hidden="true" />
        <Badge count={unreadNotifications} label="unread notifications" />
        {connection === 'offline' && (
          <span className="absolute bottom-1.5 right-1.5 size-2 rounded-full border border-sheet bg-ink-soft" aria-hidden="true" />
        )}
      </button>

      {open && (
        <div
          id={panelId}
          className="absolute right-0 top-full z-10 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-rule bg-sheet shadow-xl"
        >
          <div className="flex items-center justify-between gap-2 border-b border-rule px-4 py-2.5">
            <p className="font-semibold">Notifications</p>
            {unreadNotifications > 0 && (
              <button
                type="button"
                onClick={markAllNotificationsRead}
                className="inline-flex items-center gap-1 text-xs font-semibold text-gate hover:underline"
              >
                <CheckCheck className="size-3.5" aria-hidden="true" /> Mark all read
              </button>
            )}
          </div>
          {CONNECTION_NOTE[connection] && <p className="border-b border-rule bg-plaster px-4 py-2 text-xs text-ink-soft">{CONNECTION_NOTE[connection]}</p>}
          {notifications.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-ink-soft">Nothing yet. Visits, offers and messages show up here.</p>
          ) : (
            <ul className="max-h-[min(28rem,70dvh)] divide-y divide-rule overflow-y-auto">
              {notifications.map((notification) => {
                const { icon: Icon, accent } = notificationKind(notification.type)
                return (
                  <li key={notification.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setOpen(false)
                        openNotification(notification)
                      }}
                      className={`flex w-full gap-3 px-4 py-3 text-left hover:bg-plaster ${notification.is_read ? '' : 'bg-gate/5'}`}
                    >
                      <Icon className={`mt-0.5 size-4 shrink-0 ${accent}`} aria-hidden="true" />
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm ${notification.is_read ? 'font-medium' : 'font-semibold'}`}>{notification.title}</span>
                        <span className="mt-0.5 line-clamp-2 block text-sm text-ink-soft">{notification.message}</span>
                        <span className="mt-1 block text-xs text-ink-soft">{timeAgo(notification.created_at)}</span>
                      </span>
                      {!notification.is_read && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-tag-owner" aria-label="Unread" />}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
