import api from './client.js'

// The realtime socket goes to the page's own host by default, so Vite proxies it in dev (like /api) and production
// serves it from the same origin. VITE_WS_URL points it somewhere else, e.g. ws://localhost:8000/ws/realtime.
export function realtimeUrl(token) {
  const base = import.meta.env.VITE_WS_URL ?? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/realtime`
  return `${base}?token=${encodeURIComponent(token)}`
}

// Chat (Feature 21)
export const sendChatMessage = async (payload) => (await api.post('/chat/send', payload)).data
export const getThreads = async () => (await api.get('/chat/threads')).data
export const getThreadContext = async (propertyId, otherUserId) => (await api.get(`/chat/threads/${propertyId}/${otherUserId}`)).data
export const getMessages = async (propertyId, otherUserId, before) =>
  (await api.get(`/chat/messages/${propertyId}/${otherUserId}`, { params: { before, limit: 40 } })).data
export const markThreadRead = async (propertyId, otherUserId) => (await api.post(`/chat/messages/${propertyId}/${otherUserId}/read`)).data

// Chat actions: rent proposals and the confirmation QR (sale offers use the marketplace offer endpoints)
export const makeRentOffer = async (payload) => (await api.post('/chat/rent-offers', payload)).data
export const respondToRentOffer = async (id, payload) => (await api.post(`/chat/rent-offers/${id}/respond`, payload)).data
export const sendConfirmationQr = async (propertyId, tenantId) =>
  (await api.post('/chat/qr/send', { property_id: propertyId, tenant_id: tenantId })).data

// Notifications
export const getNotifications = async () => (await api.get('/notifications')).data
export const readNotification = async (id) => (await api.patch(`/notifications/${id}/read`)).data
export const readAllNotifications = async () => (await api.post('/notifications/read-all')).data
