import api from './client.js'

// FastAPI reads repeated keys (category=A&category=B), not axios' default category[]=A.
const repeatKeys = { indexes: null }

export async function searchRentals(params, signal) {
  return (await api.get('/rentals', { params, paramsSerializer: repeatKeys, signal })).data
}

let landmarksRequest
export function getLandmarks() {
  landmarksRequest ??= api.get('/rentals/landmarks').then(({ data }) => data)
  landmarksRequest.catch(() => (landmarksRequest = undefined))
  return landmarksRequest
}

// Popular areas (with a centre and radius) plus every other area name in use, with rental and sale counts. Given a
// { division, district, upazila }, only the area names of listings there.
export async function getAreas(region = {}) {
  return (await api.get('/rentals/areas', { params: region })).data
}

export async function getListing(id) {
  return (await api.get(`/rentals/${id}`)).data
}

export async function compareListings(ids) {
  return (await api.get('/rentals/compare', { params: { ids }, paramsSerializer: repeatKeys })).data
}

export async function getMyListings() {
  return (await api.get('/rentals/mine')).data
}

export async function createListing(payload) {
  return (await api.post('/rentals', payload)).data
}

export async function updateListing(id, payload) {
  return (await api.put(`/rentals/${id}`, payload)).data
}

export async function deleteListing(id) {
  await api.delete(`/rentals/${id}`)
}
