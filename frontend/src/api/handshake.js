import api from './client.js'

export const requestToRent = async (payload) => (await api.post('/qr-handshake/bookings', payload)).data
export const getMyBookings = async (side) => (await api.get('/qr-handshake/bookings/mine', { params: { side } })).data
export const rejectBooking = async (id) => (await api.post(`/qr-handshake/bookings/${id}/reject`)).data
export const cancelBooking = async (id) => (await api.post(`/qr-handshake/bookings/${id}/cancel`)).data
export const generateHandshakeQr = async (id) => (await api.post(`/qr-handshake/generate/${id}`)).data
export const scanAndConfirm = async (token) => (await api.post('/qr-handshake/scan-and-confirm', { token })).data
export const leasePath = (id) => `/qr-handshake/bookings/${id}/lease.pdf`
export const verifyLease = async (bookingId, sig) =>
  (await api.get(`/qr-handshake/leases/${bookingId}/verify`, { params: { sig } })).data
