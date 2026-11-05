import api from './client.js'

const repeatKeys = { indexes: null }

// Sale listings (Feature 6)
export const searchSales = async (params, signal) =>
  (await api.get('/marketplace/sale-listings', { params, paramsSerializer: repeatKeys, signal })).data
export const getSale = async (id) => (await api.get(`/marketplace/sale-listings/${id}`)).data
export const getMySales = async () => (await api.get('/marketplace/sale-listings/mine')).data
export const createSale = async (payload) => (await api.post('/marketplace/sale-listings', payload)).data
export const updateSale = async (id, payload) => (await api.put(`/marketplace/sale-listings/${id}`, payload)).data
export const deleteSale = (id) => api.delete(`/marketplace/sale-listings/${id}`)

// Title vault (Feature 7)
export const getTitleVault = async (id) => (await api.get(`/marketplace/sale-listings/${id}/title-documents`)).data
export async function uploadTitleDocument(id, docType, file) {
  const body = new FormData()
  body.append('doc_type', docType)
  body.append('file', file)
  return (await api.post(`/marketplace/sale-listings/${id}/title-documents`, body)).data
}
export const titleDocumentPath = (id, docType) => `/marketplace/sale-listings/${id}/title-documents/${docType}/file`
export const getPendingTitleReviews = async () => (await api.get('/marketplace/title-reviews/pending')).data
export const reviewTitle = async (id, status, note) =>
  (await api.patch(`/marketplace/sale-listings/${id}/title-review`, { status, note: note || null })).data

// Price analysis (Feature 8)
export const getPriceAnalysis = async (id) => (await api.get(`/marketplace/sale-listings/${id}/price-analysis`)).data

// Offers (Feature 9)
export const createOffer = async (payload) => (await api.post('/marketplace/offers', payload)).data
export const getMyOffers = async (side) => (await api.get('/marketplace/offers/mine', { params: { side } })).data
export const respondToOffer = async (id, payload) => (await api.post(`/marketplace/offers/${id}/respond`, payload)).data

// Visits (Feature 10)
export const getDaySlots = async (listingId, date) =>
  (await api.get(`/marketplace/listings/${listingId}/visit-slots`, { params: { date } })).data
export const bookVisit = async (payload) => (await api.post('/marketplace/visits', payload)).data
export const getMyVisits = async () => (await api.get('/marketplace/visits/mine')).data
export const cancelVisit = async (id) => (await api.post(`/marketplace/visits/${id}/cancel`)).data
// status: APPROVED | RESCHEDULE_PROPOSED (with starts_at) | DECLINED
export const updateVisitStatus = async (id, status, startsAt) =>
  (await api.patch(`/marketplace/visits/${id}/status`, { status, starts_at: startsAt ?? null })).data

// Admin KYC review (Feature 1 endpoints, surfaced on the admin dashboard)
export const getPendingKyc = async () => (await api.get('/auth/kyc/pending')).data
export const reviewKyc = async (userId, status, note) =>
  (await api.patch(`/auth/kyc/${userId}/review`, { status, note: note || null })).data
