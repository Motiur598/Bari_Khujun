import api, { getErrorMessage } from './client.js'

// Rentals and sales keep their photos under their own paths; a listing's `listing_mode` says which.
const listingPath = (listing) =>
  listing.listing_mode === 'SALE' ? `/marketplace/sale-listings/${listing.id}` : `/rentals/${listing.id}`

// Photos are public, so a plain <img src> can load them (no token needed).
export function photoUrl(listing, photo, size = 'full') {
  return `${api.defaults.baseURL}${listingPath(listing)}/photos/${photo.id}${size === 'thumb' ? '?size=thumb' : ''}`
}

export function videoUrl(listing, video) {
  return `${api.defaults.baseURL}${listingPath(listing)}/video/${video.id}`
}

// A room's photos are served from the listing's photo path too; only adding and removing them is per room.
const photosPath = (listing, roomId) => `${listingPath(listing)}${roomId ? `/rooms/${roomId}` : ''}/photos`

// One file per request: each stays well under the upload limits, and the editor can report progress.
export async function uploadPhoto(listing, file, roomId = null) {
  const form = new FormData()
  form.append('files', file)
  return (await api.post(photosPath(listing, roomId), form)).data
}

export async function uploadVideo(listing, file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  const onUploadProgress = onProgress && ((event) => event.total && onProgress(Math.round((event.loaded / event.total) * 100)))
  return (await api.post(`${listingPath(listing)}/video`, form, { onUploadProgress })).data
}

// Media chosen before the listing was saved, uploaded once it exists: its photos, its video, and `roomPhotos`, a list
// of [room id, files] for photos picked for rooms that had no id yet. Returns the updated listing and any failures.
export async function uploadPending(listing, { photos = [], video = null, roomPhotos = [] }) {
  const failed = []
  let current = listing
  const jobs = [
    ...photos.map((file) => [file, () => uploadPhoto(current, file)]),
    ...roomPhotos.flatMap(([roomId, files]) => files.map((file) => [file, () => uploadPhoto(current, file, roomId)])),
    ...(video ? [[video, () => uploadVideo(current, video)]] : []),
  ]
  for (const [file, upload] of jobs) {
    try {
      current = await upload()
    } catch (err) {
      failed.push(`${file.name}: ${getErrorMessage(err)}`)
    }
  }
  return { listing: current, failed }
}

export const deletePhoto = async (listing, photo, roomId = null) => (await api.delete(`${photosPath(listing, roomId)}/${photo.id}`)).data
export const makeCoverPhoto = async (listing, photo) => (await api.post(`${listingPath(listing)}/photos/${photo.id}/cover`)).data
export const deleteVideo = async (listing, video) => (await api.delete(`${listingPath(listing)}/video/${video.id}`)).data

export const MAX_PHOTOS = 10
export const MAX_ROOM_PHOTOS = 4
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024
export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const MAX_VIDEO_BYTES = 100 * 1024 * 1024
export const MAX_VIDEO_MINUTES = 3
export const VIDEO_TYPES = ['video/mp4', 'video/quicktime']
