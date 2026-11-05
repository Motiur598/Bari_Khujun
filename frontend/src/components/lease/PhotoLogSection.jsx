import { Camera, Fingerprint } from 'lucide-react'
import { useRef, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import { leasePhotoPath, uploadConditionPhotos } from '../../api/operations.js'
import { formatDateTime } from '../../constants/marketplace.js'
import { ROOMS } from '../../constants/operations.js'
import AuthImage from '../AuthImage.jsx'
import { Alert, Button, EmptyState, TextField } from '../ui.jsx'

function UploadForm({ lease, onUploaded }) {
  const fileInput = useRef(null)
  const [room, setRoom] = useState(ROOMS[0])
  const [caption, setCaption] = useState('')
  const [files, setFiles] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    if (!files.length) return setError('Choose at least one photo.')
    setBusy(true)
    setError('')
    try {
      onUploaded(await uploadConditionPhotos(lease.id, { room, caption: caption.trim(), files }))
      setFiles([])
      setCaption('')
      fileInput.current.value = ''
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-rule bg-sheet p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Room" list="room-names" required minLength={2} maxLength={40} value={room} onChange={(e) => setRoom(e.target.value)} />
        <datalist id="room-names">
          {ROOMS.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <TextField label="What it shows (optional)" maxLength={200} placeholder="Damp patch behind the door" value={caption} onChange={(e) => setCaption(e.target.value)} />
      </div>
      <label className="mt-4 flex cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed border-rule bg-white px-4 py-4 hover:border-gate has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-leaf">
        <Camera className="size-5 shrink-0 text-gate" aria-hidden="true" />
        <span className="text-sm">
          {files.length ? `${files.length} photo${files.length === 1 ? '' : 's'} chosen` : 'Choose up to 10 photos of this room'}
          <span className="block text-xs text-ink-soft">JPEG, PNG or WebP, up to 5 MB each</span>
        </span>
        <input
          ref={fileInput}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          onChange={(e) => setFiles([...e.target.files].slice(0, 10))}
          className="sr-only"
        />
      </label>
      <div className="mt-3 space-y-2">
        <Alert>{error}</Alert>
        <Button type="submit" busy={busy}>
          Add to move-in log
        </Button>
      </div>
    </form>
  )
}

export default function PhotoLogSection({ lease, onLeaseChange }) {
  const photos = lease.move_in_photos
  const rooms = Object.entries(Object.groupBy(photos, (photo) => photo.room))
  const deadline = formatDateTime(lease.photo_deadline)

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-soft">
        Photos of the flat's condition at move-in protect the tenant's deposit. The server stamps each photo with the time it
        arrived and its SHA-256 fingerprint, and photos can't be edited or removed.{' '}
        {lease.can_upload_photos ? (
          <span className="font-medium text-ink">You can add photos until {deadline}.</span>
        ) : lease.status === 'CONFIRMED' && new Date(lease.photo_deadline) > new Date() ? (
          <span>The tenant can add photos until {deadline}.</span>
        ) : (
          <span>The upload window closed on {deadline}.</span>
        )}
      </p>
      {lease.can_upload_photos && <UploadForm lease={lease} onUploaded={onLeaseChange} />}
      {photos.length === 0 ? (
        <EmptyState title="No move-in photos.">
          {lease.can_upload_photos ? 'Walk through each room and photograph walls, floors, fittings and meters.' : null}
        </EmptyState>
      ) : (
        rooms.map(([room, list]) => (
          <section key={room}>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-soft">
              {room} · {list.length}
            </h3>
            <ul className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {list.map((photo) => (
                <li key={photo.id} className="overflow-hidden rounded-lg border border-rule bg-sheet">
                  <AuthImage path={leasePhotoPath(lease.id, photo.id)} alt={photo.caption || `${room} at move-in`} className="aspect-[4/3] w-full" />
                  <div className="space-y-0.5 p-2 text-xs">
                    {photo.caption && <p className="font-medium text-ink">{photo.caption}</p>}
                    <p className="font-mono text-ink-soft">{formatDateTime(photo.uploaded_at)}</p>
                    <p className="flex items-center gap-1 font-mono text-ink-soft" title={`SHA-256 ${photo.sha256}`}>
                      <Fingerprint className="size-3 shrink-0" aria-hidden="true" /> {photo.sha256.slice(0, 12)}…
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}
