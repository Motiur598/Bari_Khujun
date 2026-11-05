import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { TOKEN_KEY } from '../api/client.js'
import { getNotifications, getThreads, readAllNotifications, readNotification, realtimeUrl } from '../api/realtime.js'
import { chime } from '../lib/chime.js'
import { useAuth } from './AuthContext.jsx'

const RealtimeContext = createContext(null)

const PING_EVERY_MS = 25_000
const PONG_WITHIN_MS = 10_000
const MAX_RETRY_MS = 30_000
const MAX_TOASTS = 6
// After a reconnect: one summary toast, plus one per missed item up to this many.
const MAX_AWAY_TOASTS = 4
const VISIT_TYPES = ['VISIT_SCHEDULED', 'VISIT_STATUS_CHANGED']

const listFormat = new Intl.ListFormat('en', { type: 'conjunction' })
const plural = (count, noun) => `${count} ${noun}${count === 1 ? '' : 's'}`

let toastSeq = 0

// The signed-in user's live connection: one WebSocket that reconnects on its own (exponential backoff, and at once
// when the browser comes back online or the tab is shown again), the notification bell, the chat threads and the
// toast queue. The chat drawer and toasts themselves are drawn by AppShell.
export function RealtimeProvider({ children }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  // idle (signed out) | connecting | live | offline
  const [connection, setConnection] = useState('idle')
  const [notifications, setNotifications] = useState([])
  const [unreadNotifications, setUnreadNotifications] = useState(0)
  const [threads, setThreads] = useState([])
  const [presence, setPresence] = useState({})
  const [toasts, setToasts] = useState([])
  // target: { propertyId, otherUserId, otherName?, listingTitle? }, or null for the thread list alone.
  const [chat, setChat] = useState({ open: false, target: null })

  const listeners = useRef(new Set())
  const chatRef = useRef(chat)
  const threadsRef = useRef(threads)
  const notificationsRef = useRef(notifications)
  const handleRef = useRef(null)
  useEffect(() => {
    chatRef.current = chat
    threadsRef.current = threads
    notificationsRef.current = notifications
  })

  const refreshThreads = useCallback(() => getThreads().then(setThreads, () => {}), [])
  const refreshNotifications = useCallback(
    () =>
      getNotifications().then(({ items, unread_count }) => {
        setNotifications(items)
        setUnreadNotifications(unread_count)
      }, () => {}),
    [],
  )

  const dismissToast = useCallback((id) => setToasts((list) => list.filter((toast) => toast.id !== id)), [])
  const pushToast = useCallback((toast) => setToasts((list) => [...list, { id: ++toastSeq, ...toast }].slice(-MAX_TOASTS)), [])

  const openChat = useCallback((target = null) => setChat({ open: true, target }), [])
  const closeChat = useCallback(() => setChat({ open: false, target: null }), [])

  // Drawer components listen to every socket event (new messages, card updates, read receipts, presence).
  const subscribe = useCallback((listener) => {
    listeners.current.add(listener)
    return () => listeners.current.delete(listener)
  }, [])

  const markNotificationRead = useCallback(
    async (notification) => {
      if (notification.is_read) return
      setNotifications((list) => list.map((item) => (item.id === notification.id ? { ...item, is_read: true } : item)))
      setUnreadNotifications((count) => Math.max(0, count - 1))
      try {
        await readNotification(notification.id)
      } catch {
        refreshNotifications()
      }
    },
    [refreshNotifications],
  )

  const markAllNotificationsRead = useCallback(async () => {
    setNotifications((list) => list.map((item) => ({ ...item, is_read: true })))
    setUnreadNotifications(0)
    try {
      await readAllNotifications()
    } catch {
      refreshNotifications()
    }
  }, [refreshNotifications])

  // The chat drawer read a thread: clear its badge and its message alert.
  const markThreadSeen = useCallback(
    (propertyId, otherUserId) => {
      setThreads((list) =>
        list.map((thread) => (thread.property_id === propertyId && thread.other_user.id === otherUserId ? { ...thread, unread_count: 0 } : thread)),
      )
      const alert = notificationsRef.current.some(
        (n) => n.type === 'NEW_MESSAGE' && !n.is_read && n.property_id === propertyId && n.metadata?.chat_with === otherUserId,
      )
      if (alert) refreshNotifications()
    },
    [refreshNotifications],
  )

  // Where a notification leads: a dashboard tab it names, the visit schedule, or the chat it came from.
  const notificationActions = useCallback(
    (notification) => {
      const { metadata = {}, property_id: propertyId, type } = notification
      const go = (run) => () => {
        markNotificationRead(notification)
        run()
      }
      const actions = []
      if (metadata.dashboard_tab) {
        actions.push({ label: 'Open dashboard', run: go(() => navigate(`/dashboard?tab=${metadata.dashboard_tab}`)) })
      } else if (propertyId && metadata.chat_with) {
        actions.push({ label: type === 'NEW_MESSAGE' ? 'Reply' : 'Open chat', run: go(() => openChat({ propertyId, otherUserId: metadata.chat_with })) })
      }
      if (VISIT_TYPES.includes(type)) actions.push({ label: 'View visits', run: go(() => navigate('/dashboard?tab=visits')) })
      return actions
    },
    [markNotificationRead, navigate, openChat],
  )

  const openNotification = useCallback(
    (notification) => {
      const actions = notificationActions(notification)
      // Visit alerts open the schedule from the bell; everything else opens its chat (or dashboard tab).
      const primary = VISIT_TYPES.includes(notification.type) ? actions.at(-1) : actions[0]
      if (primary) primary.run()
      else markNotificationRead(notification)
    },
    [notificationActions, markNotificationRead],
  )

  const toastFor = useCallback(
    (notification) => pushToast({ kind: notification.type, title: notification.title, body: notification.message, actions: notificationActions(notification) }),
    [notificationActions, pushToast],
  )

  // ---------------------------------------------------------------- socket events

  const isViewing = (propertyId, otherUserId) => {
    const { open, target } = chatRef.current
    return open && target?.propertyId === propertyId && target?.otherUserId === otherUserId && document.visibilityState === 'visible'
  }

  const upsertThread = (message, unreadDelta) => {
    if (!threadsRef.current.some((thread) => thread.thread_id === message.thread_id)) {
      refreshThreads() // a new conversation: the server has its listing and person
      return
    }
    setThreads((list) => {
      const thread = list.find((t) => t.thread_id === message.thread_id)
      if (!thread) return list
      const updated = { ...thread, last_message: message, unread_count: thread.unread_count + unreadDelta }
      return [updated, ...list.filter((t) => t !== thread)]
    })
  }

  const addNotification = (notification) => {
    const known = notificationsRef.current.some((n) => n.id === notification.id && !n.is_read)
    setNotifications((list) => [notification, ...list.filter((n) => n.id !== notification.id)])
    if (!known) setUnreadNotifications((count) => count + 1)
  }

  function handleEvent(event) {
    listeners.current.forEach((listener) => listener(event))
    switch (event.type) {
      case 'OFFLINE_SYNC_BUNDLE': {
        setUnreadNotifications(event.unread_notifications)
        setPresence({}) // the fresh thread list carries who is online now
        refreshThreads()
        refreshNotifications()
        // Only what never reached this user before counts as missed, so a page reload doesn't pop it all up again.
        const missed = event.notifications.filter((n) => !n.is_delivered)
        const messages = event.messages.filter((m) => !m.is_delivered && m.message_type === 'TEXT').length
        const visits = missed.filter((n) => n.type === 'VISIT_SCHEDULED').length
        const others = missed.filter((n) => n.type !== 'NEW_MESSAGE' && n.type !== 'VISIT_SCHEDULED').length
        const parts = [
          messages && plural(messages, 'new message'),
          visits && plural(visits, 'scheduled house visit'),
          others && plural(others, 'other update'),
        ].filter(Boolean)
        if (parts.length === 0) break
        pushToast({
          kind: 'SUMMARY',
          title: 'Welcome back',
          body: `You have ${listFormat.format(parts)} while you were away.`,
          actions: [{ label: 'Open messages', run: () => openChat(null) }],
        })
        missed.slice(0, MAX_AWAY_TOASTS).forEach(toastFor)
        chime()
        break
      }
      case 'NEW_CHAT_MESSAGE': {
        const { message, notification } = event
        const viewing = isViewing(message.property_id, message.sender_id)
        upsertThread(message, viewing ? 0 : 1)
        // Action cards come with their own notification event (visit, offer, QR); only plain messages toast here.
        if (notification && !viewing) {
          addNotification(notification)
          toastFor(notification)
          chime()
        }
        break
      }
      case 'CHAT_MESSAGE_SENT':
        upsertThread(event.message, 0)
        break
      case 'CHAT_CARD_UPDATED':
        setThreads((list) => list.map((t) => (t.last_message.id === event.message.id ? { ...t, last_message: event.message } : t)))
        break
      case 'MESSAGES_READ':
        if (event.reader_id === user?.id) {
          setThreads((list) => list.map((t) => (t.thread_id === event.thread_id ? { ...t, unread_count: 0 } : t)))
        }
        break
      case 'PRESENCE':
        setPresence((map) => ({ ...map, [event.user_id]: event.online }))
        break
      default:
        if (event.notification) {
          const { notification } = event
          addNotification(notification)
          // Already looking at that chat: the card has just changed on screen, so no pop-up for it.
          if (notification.metadata?.chat_with && isViewing(notification.property_id, notification.metadata.chat_with)) {
            markNotificationRead(notification)
            break
          }
          toastFor(notification)
          chime()
        }
    }
  }
  useEffect(() => {
    handleRef.current = handleEvent
  })

  // ---------------------------------------------------------------- the socket

  useEffect(() => {
    if (!user?.id) return undefined
    let socket = null
    let stopped = false
    let attempt = 0
    let retryTimer
    let pingTimer
    let pongTimer

    const scheduleRetry = () => {
      clearTimeout(retryTimer)
      if (!navigator.onLine) return // the 'online' event reconnects
      const delay = Math.min(MAX_RETRY_MS, 1000 * 2 ** attempt) * (0.5 + Math.random() / 2)
      attempt += 1
      retryTimer = setTimeout(connect, delay)
    }

    // Let go of the socket at once rather than wait for a close handshake over a dead network.
    const drop = (retry) => {
      const old = socket
      socket = null
      clearInterval(pingTimer)
      clearTimeout(pongTimer)
      if (old) {
        old.onopen = old.onmessage = old.onclose = old.onerror = null
        try {
          old.close()
        } catch {
          // already closed
        }
      }
      if (stopped) return
      setConnection('offline')
      if (retry) scheduleRetry()
    }

    // A socket can look open long after the network went (laptop lid, lift, tunnel); no PONG means it's gone.
    const ping = () => {
      if (socket?.readyState !== WebSocket.OPEN) return
      socket.send(JSON.stringify({ type: 'PING' }))
      clearTimeout(pongTimer)
      pongTimer = setTimeout(() => drop(true), PONG_WITHIN_MS)
    }

    function connect() {
      if (stopped || socket) return
      const token = localStorage.getItem(TOKEN_KEY)
      if (!token) return
      setConnection('connecting')
      const ws = new WebSocket(realtimeUrl(token))
      socket = ws
      let opened = false
      ws.onopen = () => {
        opened = true
        attempt = 0
        setConnection('live')
        pingTimer = setInterval(ping, PING_EVERY_MS)
      }
      ws.onmessage = ({ data }) => {
        let event
        try {
          event = JSON.parse(data)
        } catch {
          return
        }
        if (event.type === 'PONG') clearTimeout(pongTimer)
        else handleRef.current?.(event)
      }
      ws.onclose = ({ code }) => {
        if (socket !== ws) return
        // Refused at the handshake, or closed because the token stopped working: ask the API whether the session
        // still stands. A 401 there signs the user out (api/client.js), which ends this effect.
        if (!opened || code === 4401) api.get('/auth/me').catch(() => {})
        drop(true)
      }
    }

    const reconnectNow = () => {
      attempt = 0
      clearTimeout(retryTimer)
      if (!socket) connect()
    }
    const onOnline = () => reconnectNow()
    const onOffline = () => drop(false)
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      if (socket) ping()
      else reconnectNow()
    }

    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    document.addEventListener('visibilitychange', onVisible)
    connect()
    return () => {
      stopped = true
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
      document.removeEventListener('visibilitychange', onVisible)
      clearTimeout(retryTimer)
      drop(false)
      setConnection('idle')
      setNotifications([])
      setUnreadNotifications(0)
      setThreads([])
      setPresence({})
      setChat({ open: false, target: null })
    }
  }, [user?.id])

  const unreadMessages = useMemo(() => threads.reduce((sum, thread) => sum + thread.unread_count, 0), [threads])
  const isOnline = useCallback((userId, fallback = false) => presence[userId] ?? fallback, [presence])

  const value = useMemo(
    () => ({
      connection,
      notifications,
      unreadNotifications,
      threads,
      unreadMessages,
      isOnline,
      toasts,
      chat,
      openChat,
      closeChat,
      subscribe,
      refreshThreads,
      markThreadSeen,
      openNotification,
      markAllNotificationsRead,
      dismissToast,
    }),
    [
      connection, notifications, unreadNotifications, threads, unreadMessages, isOnline, toasts, chat, openChat, closeChat,
      subscribe, refreshThreads, markThreadSeen, openNotification, markAllNotificationsRead, dismissToast,
    ],
  )

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>
}

export function useRealtime() {
  const context = useContext(RealtimeContext)
  if (!context) throw new Error('useRealtime must be used inside <RealtimeProvider>')
  return context
}
