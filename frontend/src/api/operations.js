import api from './client.js'

// Leases (QR-confirmed bookings)
export const getLeases = async (side) => (await api.get('/operations/leases', { params: { side } })).data
export const getLease = async (id) => (await api.get(`/operations/leases/${id}`)).data
export const leasePhotoPath = (leaseId, photoId) => `/operations/leases/${leaseId}/photos/${photoId}`

export async function uploadConditionPhotos(leaseId, { room, caption, files }) {
  const body = new FormData()
  body.append('room', room)
  if (caption) body.append('caption', caption)
  for (const file of files) body.append('files', file)
  return (await api.post(`/operations/leases/${leaseId}/photos`, body)).data
}

export const giveMoveOutNotice = async (leaseId, payload) =>
  (await api.post(`/operations/leases/${leaseId}/move-out-notice`, payload)).data

// Invoices (Feature 16)
export const getInvoices = async (bookingId) => (await api.get('/operations/invoices', { params: { booking_id: bookingId } })).data
export const generateInvoices = async (payload) => (await api.post('/operations/invoices/generate', payload)).data
export const payInvoice = async (id, payload) => (await api.post(`/operations/invoices/${id}/pay`, payload)).data
export const confirmInvoice = async (id, payload) => (await api.post(`/operations/invoices/${id}/confirm`, payload ?? null)).data
export const rejectInvoicePayment = async (id, note) => (await api.post(`/operations/invoices/${id}/reject-payment`, { note })).data
export const receiptPath = (id) => `/operations/invoices/${id}/receipt.pdf`

// Maintenance (Feature 18)
export const getTickets = async (bookingId) => (await api.get('/operations/tickets', { params: { booking_id: bookingId } })).data
export async function reportIssue({ bookingId, category, priority, title, description, photos }) {
  const body = new FormData()
  body.append('booking_id', bookingId)
  body.append('category', category)
  body.append('priority', priority)
  body.append('title', title)
  body.append('description', description)
  for (const photo of photos) body.append('photos', photo)
  return (await api.post('/operations/tickets', body)).data
}
export const advanceTicket = async (id, status, note) => (await api.post(`/operations/tickets/${id}/status`, { status, note: note || null })).data
export const commentOnTicket = async (id, note) => (await api.post(`/operations/tickets/${id}/comments`, { note })).data
export const ticketPhotoPath = (ticketId, photoId) => `/operations/tickets/${ticketId}/photos/${photoId}`

// Reviews (Feature 19)
export const saveReview = async (payload) => (await api.put('/operations/reviews', payload)).data
export const getLeaseReviews = async (bookingId) => (await api.get(`/operations/reviews/lease/${bookingId}`)).data
export const getUserReviews = async (userId) => (await api.get(`/operations/reviews/user/${userId}`)).data
