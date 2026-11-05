import { ChevronLeft, ChevronRight, Film, ImageOff, ImagePlus, LoaderCircle, Play, Star, X } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { getErrorMessage } from '../../api/client.js'
import {
  MAX_PHOTO_BYTES,
  MAX_PHOTOS,
  MAX_ROOM_PHOTOS,
  MAX_VIDEO_BYTES,
  MAX_VIDEO_MINUTES,
  PHOTO_TYPES,
  VIDEO_TYPES,
  deletePhoto,
  deleteVideo,
  makeCoverPhoto,
  photoUrl,
  uploadPhoto,
  uploadVideo,
  videoUrl,
} from '../../api/photos.js'
import { Alert } from '../ui.jsx'

// 84 -> "1:24"
const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`

// The cover (first photo) as a thumbnail, for cards, map pins and lists. `className` sets its size.
export function CoverPhoto({ listing, className = '' }) {
  const cover = listing.photos?.[0]
  if (!cover) {
    return (
      <div className={`grid place-items-center bg-plaster text-ink-soft/70 ${className}`}>
        <ImageOff className="size-5" aria-label="No photo yet" />
      </div>
    )
  }
  return <img src={photoUrl(listing, cover, 'thumb')} alt="" loading="lazy" className={`bg-plaster object-cover ${className}`} />
}

// A full-screen <dialog>, open while `open` is true. Esc closes it.
function Viewer({ open, onClose, label, onKeyDown, children }) {
  const dialogRef = useRef(null)
  useEffect(() => {
    const dialog = dialogRef.current
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])
  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      onKeyDown={onKeyDown}
      aria-label={label}
      className="m-0 h-dvh max-h-none w-screen max-w-none bg-transparent p-0 backdrop:bg-ink/90"
    >
      {open && (
        <div className="flex h-dvh w-screen flex-col items-center justify-center gap-3 p-4">
          {children}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="absolute right-4 top-4 rounded-full bg-white/15 p-2 text-white hover:bg-white/25"
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>
      )}
    </dialog>
  )
}

// Arrow keys or the buttons move between `photos`, Esc closes.
function Lightbox({ listing, photos, title, index, onIndex, onClose }) {
  const step = (delta) => onIndex((index + delta + photos.length) % photos.length)
  return (
    <Viewer
      open={index !== null}
      onClose={onClose}
      label={`Photos of ${title}`}
      onKeyDown={(event) => {
        if (event.key === 'ArrowRight') step(1)
        if (event.key === 'ArrowLeft') step(-1)
      }}
    >
      {index !== null && (
        <>
          <img
            src={photoUrl(listing, photos[index])}
            alt={`Photo ${index + 1} of ${photos.length}: ${title}`}
            className="max-h-[80dvh] max-w-full rounded-md object-contain"
          />
          <div className="flex items-center gap-4 text-white">
            {photos.length > 1 && (
              <button type="button" onClick={() => step(-1)} aria-label="Previous photo" className="rounded-full bg-white/15 p-2 hover:bg-white/25">
                <ChevronLeft className="size-5" aria-hidden="true" />
              </button>
            )}
            <span className="font-mono text-sm">
              {index + 1} / {photos.length}
            </span>
            {photos.length > 1 && (
              <button type="button" onClick={() => step(1)} aria-label="Next photo" className="rounded-full bg-white/15 p-2 hover:bg-white/25">
                <ChevronRight className="size-5" aria-hidden="true" />
              </button>
            )}
          </div>
        </>
      )}
    </Viewer>
  )
}

function VideoTour({ listing }) {
  const [open, setOpen] = useState(false)
  const { video } = listing
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 inline-flex items-center gap-2 rounded-md border border-rule bg-sheet px-3 py-2 text-sm font-semibold hover:border-ink"
      >
        <span className="grid size-6 place-items-center rounded-full bg-gate text-white">
          <Play className="size-3.5 fill-current" aria-hidden="true" />
        </span>
        Watch the video tour
        {video.duration_seconds != null && <span className="font-mono text-xs font-normal text-ink-soft">{clock(video.duration_seconds)}</span>}
      </button>
      <Viewer open={open} onClose={() => setOpen(false)} label={`Video tour of ${listing.title}`}>
        <video src={videoUrl(listing, video)} controls autoPlay playsInline className="max-h-[85dvh] max-w-full rounded-md bg-black">
          Your browser can't play this video.
        </video>
      </Viewer>
    </>
  )
}

// The photos at the top of a listing page: the cover large, two more beside it, the rest in the viewer, then the
// video tour if there is one.
export function PhotoGallery({ listing }) {
  const [open, setOpen] = useState(null)
  const photos = listing.photos ?? []
  if (photos.length === 0) {
    return (
      <>
        <div className="grid aspect-[3/1] place-items-center rounded-xl border border-dashed border-rule bg-plaster text-sm text-ink-soft">
          <span className="inline-flex items-center gap-2">
            <ImageOff className="size-5" aria-hidden="true" /> No photos yet
          </span>
        </div>
        {listing.video && <VideoTour listing={listing} />}
      </>
    )
  }
  const side = photos.slice(1, 3)
  const hidden = photos.length - 1 - side.length
  return (
    <>
      <div className={`grid gap-2 ${side.length ? 'sm:h-[26rem] sm:grid-cols-[3fr_1fr] sm:grid-rows-2' : ''}`}>
        <button
          type="button"
          onClick={() => setOpen(0)}
          className={`overflow-hidden rounded-xl bg-plaster ${side.length ? 'aspect-[4/3] sm:row-span-2 sm:aspect-auto' : 'aspect-[16/9]'}`}
        >
          <img src={photoUrl(listing, photos[0])} alt={`Photo 1 of ${photos.length}: ${listing.title}`} className="size-full object-cover" />
        </button>
        {side.length > 0 && (
          <div className="grid grid-cols-2 gap-2 sm:contents">
            {side.map((photo, offset) => (
              <button
                key={photo.id}
                type="button"
                onClick={() => setOpen(offset + 1)}
                className="relative aspect-[4/3] overflow-hidden rounded-xl bg-plaster sm:aspect-auto"
              >
                <img src={photoUrl(listing, photo, 'thumb')} alt={`Photo ${offset + 2} of ${photos.length}`} loading="lazy" className="size-full object-cover" />
                {offset === side.length - 1 && hidden > 0 && (
                  <span className="absolute inset-0 grid place-items-center bg-ink/55 text-lg font-semibold text-white">+{hidden} more</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
      {listing.video && <VideoTour listing={listing} />}
      <Lightbox listing={listing} photos={photos} title={listing.title} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />
    </>
  )
}

// A room's photos on the listing page, as a row of thumbnails that open the viewer.
export function RoomPhotoStrip({ listing, room }) {
  const [open, setOpen] = useState(null)
  if (room.photos.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-ink-soft">
        <ImageOff className="size-4" aria-hidden="true" /> No photos of this room yet
      </p>
    )
  }
  return (
    <>
      <ul className="flex gap-2 overflow-x-auto">
        {room.photos.map((photo, index) => (
          <li key={photo.id} className="shrink-0">
            <button type="button" onClick={() => setOpen(index)} className="block overflow-hidden rounded-md bg-plaster">
              <img
                src={photoUrl(listing, photo, 'thumb')}
                alt={`${room.name}, photo ${index + 1} of ${room.photos.length}`}
                loading="lazy"
                className="h-20 w-28 object-cover transition-transform hover:scale-105"
              />
            </button>
          </li>
        ))}
      </ul>
      <Lightbox listing={listing} photos={room.photos} title={room.name} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />
    </>
  )
}

function PhotoTile({ src, label, isCover, onCover, onRemove, disabled }) {
  return (
    <li className="group relative aspect-[4/3] overflow-hidden rounded-lg border border-rule bg-plaster">
      <img src={src} alt={label} className="size-full object-cover" />
      {isCover && (
        <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded bg-gate px-1.5 py-0.5 text-xs font-semibold text-white">
          <Star className="size-3" aria-hidden="true" /> Cover
        </span>
      )}
      <div className="absolute inset-x-2 bottom-2 flex justify-between gap-2">
        {onCover && !isCover ? (
          <button
            type="button"
            disabled={disabled}
            onClick={onCover}
            className="rounded bg-sheet/95 px-2 py-1 text-xs font-semibold text-ink shadow hover:bg-white disabled:opacity-60"
          >
            Make cover
          </button>
        ) : (
          <span />
        )}
        <button
          type="button"
          disabled={disabled}
          onClick={onRemove}
          aria-label={`Remove ${label}`}
          className="rounded bg-sheet/95 p-1 text-tag-owner shadow hover:bg-white disabled:opacity-60"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
    </li>
  )
}

// A dashed drop target that opens the file picker.
function AddTile({ icon: Icon, title, hint, busy, accept, multiple, onFiles, className = 'aspect-[4/3]' }) {
  const inputId = useId()
  const [dragging, setDragging] = useState(false)
  return (
    <label
      htmlFor={inputId}
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        if (!busy) onFiles(event.dataTransfer.files)
      }}
      className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-3 text-center text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-leaf ${className} ${
        dragging ? 'border-gate bg-gate/8' : 'border-rule bg-white hover:border-gate'
      }`}
    >
      {busy ? <LoaderCircle className="size-6 animate-spin text-gate" aria-hidden="true" /> : <Icon className="size-6 text-gate" aria-hidden="true" />}
      <span className="font-semibold">{busy || title}</span>
      {!busy && <span className="text-xs text-ink-soft">{hint}</span>}
      <input
        id={inputId}
        type="file"
        multiple={multiple}
        accept={accept}
        disabled={Boolean(busy)}
        onChange={(event) => {
          onFiles(event.target.files)
          event.target.value = ''
        }}
        className="sr-only"
      />
    </label>
  )
}

// Photos for the listing or for one room (`roomId`). With a saved `listing` (and, for a room, a saved room) changes go
// to the server straight away and come back through `onListingChange`; otherwise files wait in `pending` until the
// listing has been saved.
function PhotoGrid({ listing, roomId = null, photos, max, onListingChange, pending, onPendingChange, canCover, columns }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const live = Boolean(listing)
  const saved = photos ?? []
  const previews = useMemo(() => pending.map((file) => ({ file, url: URL.createObjectURL(file) })), [pending])
  useEffect(() => () => previews.forEach(({ url }) => URL.revokeObjectURL(url)), [previews])
  const room = max - saved.length - pending.length

  async function addFiles(fileList) {
    const problems = []
    const accepted = [...fileList].filter((file) => {
      if (!PHOTO_TYPES.includes(file.type)) problems.push(`${file.name} isn't a JPEG, PNG or WebP photo`)
      else if (file.size > MAX_PHOTO_BYTES) problems.push(`${file.name} is larger than 5 MB`)
      else return true
      return false
    })
    const fitting = accepted.slice(0, Math.max(room, 0))
    if (accepted.length > fitting.length) problems.push(`Only ${max} photos fit, so ${accepted.length - fitting.length} were left out`)
    setError('')
    if (!live) {
      onPendingChange([...pending, ...fitting])
      setError(problems.join('. '))
      return
    }
    let current = listing
    for (const [index, file] of fitting.entries()) {
      setBusy(`Uploading ${index + 1} of ${fitting.length}…`)
      try {
        current = await uploadPhoto(current, file, roomId)
      } catch (err) {
        problems.push(`${file.name}: ${getErrorMessage(err)}`)
      }
    }
    setBusy('')
    onListingChange(current)
    setError(problems.join('. '))
  }

  async function change(action, photo) {
    setError('')
    setBusy(action === makeCoverPhoto ? 'Saving…' : 'Removing…')
    try {
      onListingChange(await action(listing, photo, roomId))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy('')
    }
  }

  const movePendingFirst = (file) => onPendingChange([file, ...pending.filter((item) => item !== file)])

  return (
    <div className="space-y-3">
      <ul className={`grid gap-3 ${columns}`}>
        {saved.map((photo, index) => (
          <PhotoTile
            key={photo.id}
            src={photoUrl(listing, photo, 'thumb')}
            label={`photo ${index + 1}`}
            isCover={canCover && index === 0}
            disabled={Boolean(busy)}
            onCover={canCover ? () => change(makeCoverPhoto, photo) : null}
            onRemove={() => window.confirm('Remove this photo?') && change(deletePhoto, photo)}
          />
        ))}
        {previews.map(({ file, url }, index) => (
          <PhotoTile
            key={url}
            src={url}
            label={`photo ${saved.length + index + 1}`}
            isCover={canCover && saved.length === 0 && index === 0}
            onCover={canCover ? () => movePendingFirst(file) : null}
            onRemove={() => onPendingChange(pending.filter((item) => item !== file))}
          />
        ))}
        {room > 0 && (
          <li>
            <AddTile
              icon={ImagePlus}
              title="Add photos"
              hint="or drop them here"
              busy={busy}
              multiple
              accept={PHOTO_TYPES.join(',')}
              onFiles={addFiles}
            />
          </li>
        )}
      </ul>
      <Alert>{error}</Alert>
    </div>
  )
}

// How long a video file runs, read by the browser (null if it can't tell, e.g. a codec it doesn't play).
function videoDuration(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const probe = document.createElement('video')
    const done = (value) => {
      URL.revokeObjectURL(url)
      resolve(value)
    }
    probe.preload = 'metadata'
    probe.onloadedmetadata = () => done(Number.isFinite(probe.duration) ? probe.duration : null)
    probe.onerror = () => done(null)
    probe.src = url
  })
}

// The listing's one video: shown with a remove button, or a tile to add it. Saved listings upload straight away.
function VideoSlot({ listing, onListingChange, pending, onPendingChange }) {
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState('')
  const saved = listing?.video
  const previewUrl = useMemo(() => (pending ? URL.createObjectURL(pending) : null), [pending])
  useEffect(() => () => previewUrl && URL.revokeObjectURL(previewUrl), [previewUrl])

  async function addFiles(fileList) {
    const file = fileList[0]
    if (!file) return
    setError('')
    if (!VIDEO_TYPES.includes(file.type)) return setError(`${file.name} isn't an MP4 or MOV video`)
    if (file.size > MAX_VIDEO_BYTES) return setError(`${file.name} is larger than ${MAX_VIDEO_BYTES / (1024 * 1024)} MB`)
    const seconds = await videoDuration(file)
    if (seconds !== null && seconds > MAX_VIDEO_MINUTES * 60) return setError(`Keep the video under ${MAX_VIDEO_MINUTES} minutes (this one is ${clock(seconds)})`)
    if (!listing) return onPendingChange(file)
    setProgress(0)
    try {
      onListingChange(await uploadVideo(listing, file, setProgress))
    } catch (err) {
      setError(`${file.name}: ${getErrorMessage(err)}`)
    } finally {
      setProgress(null)
    }
  }

  async function remove() {
    if (!window.confirm('Remove the video from the listing?')) return
    setError('')
    setProgress(0)
    try {
      onListingChange(await deleteVideo(listing, saved))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setProgress(null)
    }
  }

  const src = saved ? videoUrl(listing, saved) : previewUrl
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">
        Video tour <span className="font-normal text-ink-soft">(optional, one video)</span>
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {src ? (
          <div className="relative col-span-2 aspect-video overflow-hidden rounded-lg border border-rule bg-black sm:col-span-1">
            <video src={src} controls preload="metadata" playsInline className="size-full object-contain" aria-label="Video tour" />
            <button
              type="button"
              disabled={progress !== null}
              onClick={saved ? remove : () => onPendingChange(null)}
              aria-label="Remove the video"
              className="absolute right-2 top-2 rounded bg-sheet/95 p-1 text-tag-owner shadow hover:bg-white disabled:opacity-60"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        ) : (
          <AddTile
            icon={Film}
            title="Add a video"
            hint={`MP4 or MOV, up to ${MAX_VIDEO_BYTES / (1024 * 1024)} MB and ${MAX_VIDEO_MINUTES} min`}
            busy={progress !== null ? `Uploading… ${progress}%` : ''}
            accept={VIDEO_TYPES.join(',')}
            onFiles={addFiles}
            className="col-span-2 aspect-video sm:col-span-1"
          />
        )}
      </div>
      <Alert>{error}</Alert>
    </div>
  )
}

// The media section of the listing editors: up to MAX_PHOTOS photos (the first is the cover) and one video.
export function PhotoManager({ listing, onListingChange, pending, onPendingChange, pendingVideo, onPendingVideoChange }) {
  return (
    <div className="space-y-6">
      <PhotoGrid
        listing={listing}
        photos={listing?.photos}
        max={MAX_PHOTOS}
        onListingChange={onListingChange}
        pending={pending}
        onPendingChange={onPendingChange}
        canCover
        columns="grid-cols-2 sm:grid-cols-3"
      />
      <VideoSlot listing={listing} onListingChange={onListingChange} pending={pendingVideo} onPendingChange={onPendingVideoChange} />
      <p className="text-xs text-ink-soft">
        Up to {MAX_PHOTOS} photos (JPEG, PNG or WebP, 5 MB each). The first is the cover on cards and the map. Photos are
        resized, and location data is removed from photos and the video before anyone sees them.
      </p>
    </div>
  )
}

// One room's photos in the room editor. `room` is the saved room (null for a room that hasn't been saved yet).
export function RoomPhotoManager({ listing, room, onListingChange, pending, onPendingChange }) {
  return (
    <PhotoGrid
      listing={room ? listing : null}
      roomId={room?.id ?? null}
      photos={room?.photos}
      max={MAX_ROOM_PHOTOS}
      onListingChange={onListingChange}
      pending={pending}
      onPendingChange={onPendingChange}
      columns="grid-cols-2 sm:grid-cols-4"
    />
  )
}
