import api from './client.js'

const G = '/admin/governance'

// Admin governance center (Feature 20)
export const getOverview = async () => (await api.get(`${G}/overview`)).data
export const getAuditLog = async (params) => (await api.get(`${G}/alerts`, { params })).data
export const resolveAlert = async (id, note) => (await api.post(`${G}/alerts/${id}/resolve`, { note })).data
export const runRadar = async () => (await api.post(`${G}/radar/run`)).data
export const getQrHandshakes = async (state) => (await api.get(`${G}/qr-handshakes`, { params: { state: state || undefined } })).data
export const revokeQr = async (bookingId, reason) => (await api.post(`${G}/qr-handshakes/${bookingId}/revoke`, { reason })).data
export const getDeedVault = async (status) => (await api.get(`${G}/deed-vault`, { params: { status } })).data
export const banScammer = async (userId, reason) => (await api.post(`${G}/users/${userId}/ban-scammer`, { reason })).data
export const getAdminDisputes = async (status) => (await api.get(`${G}/disputes`, { params: { status: status || undefined } })).data
export const ruleDispute = async (id, payload) => (await api.post(`${G}/disputes/${id}/rule`, payload)).data

// Disputes, for the parties
export const getEligibleSubjects = async () => (await api.get('/disputes/eligible')).data
export const getMyDisputes = async () => (await api.get('/disputes/mine')).data

export async function raiseDispute({ type, subject, claimedAmount, description, photos }) {
  const body = new FormData()
  body.append('type', type)
  body.append(subject.kind === 'OFFER' ? 'offer_id' : 'booking_id', subject.id)
  body.append('claimed_amount', String(claimedAmount))
  body.append('description', description)
  for (const photo of photos) body.append('photos', photo)
  return (await api.post('/disputes', body)).data
}

export async function respondToDispute(id, { statement, claimedDeduction, photos }) {
  const body = new FormData()
  body.append('statement', statement)
  if (claimedDeduction !== '' && claimedDeduction != null) body.append('claimed_deduction', String(claimedDeduction))
  for (const photo of photos) body.append('photos', photo)
  return (await api.post(`/disputes/${id}/response`, body)).data
}

export const disputePhotoPath = (disputeId, photoId) => `/disputes/${disputeId}/photos/${photoId}`
export const baselinePhotoPath = (disputeId, photoId) => `/disputes/${disputeId}/baseline/${photoId}`

export const relistFlat = async (listingId) => (await api.post(`/rentals/${listingId}/relist`)).data
