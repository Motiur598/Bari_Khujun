import {
  AlertTriangle,
  BadgeCheck,
  Camera,
  CircleUser,
  Crop,
  ImageUp,
  LoaderCircle,
  RotateCcw,
  ScanSearch,
  ShieldAlert,
  Sun,
  X,
  ZapOff,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { getErrorMessage } from '../api/client.js'
import { KYC_APPEAL_EMAIL, autoVerifyKyc } from '../api/kyc.js'
import { KYC_DOC_TYPES } from '../constants/roles.js'
import { useAuth } from '../context/AuthContext.jsx'
import { Alert, Button, Segmented, Stamp } from './ui.jsx'

const SIDES = [
  ['front', 'Front side', 'The side with your photo, name and ID number.'],
  ['back', 'Back side', 'Turn the card over and take a second photo.'],
]
const STAMPS = {
  NOT_SUBMITTED: ['Not verified', 'border-ink-soft text-ink-soft'],
  REJECTED: ['Not accepted', 'border-tag-owner text-tag-owner'],
  PENDING: ['Being checked', 'border-brass text-[#8a6410]'],
  VERIFIED: ['Verified', 'border-gate text-gate'],
  REVOKED: ['Restricted', 'border-tag-owner text-tag-owner'],
}
// Photos are shrunk before upload: plenty for reading the card, and quick on mobile data.
const MAX_EDGE = 2000
const MAX_BYTES = 10 * 1024 * 1024

async function shrink(file, name) {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height))
    if (scale === 1 && file.size <= MAX_BYTES && file.type === 'image/jpeg') return file
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92))
    return blob ? new File([blob], name, { type: 'image/jpeg' }) : file
  } catch {
    // A format the browser can't draw (some HEIC photos): send it as it is and let the server say.
    return file
  }
}

// A live camera view with a card-shaped guide. Falls back to the phone's camera app when there's no camera API.
function CameraDialog({ side, onCapture, onClose }) {
  const dialogRef = useRef(null)
  const videoRef = useRef(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog.open) dialog.showModal()
    let stream
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false })
      .then((media) => {
        stream = media
        videoRef.current.srcObject = media
      })
      .catch(() => setError('The camera is blocked or unavailable. Allow camera access in your browser, or upload a photo instead.'))
    return () => stream?.getTracks().forEach((track) => track.stop())
  }, [])

  function capture() {
    const video = videoRef.current
    if (!video?.videoWidth) return
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d').drawImage(video, 0, 0)
    canvas.toBlob((blob) => blob && onCapture(new File([blob], `${side}.jpg`, { type: 'image/jpeg' })), 'image/jpeg', 0.92)
  }

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-label={`Photograph the ${side} of your ID`}
      className="m-auto w-[min(44rem,calc(100vw-2rem))] max-w-none rounded-xl bg-ink p-0 text-white backdrop:bg-ink/80"
    >
      <div className="relative">
        <video ref={videoRef} autoPlay playsInline muted className="aspect-video w-full rounded-t-xl bg-black object-cover" />
        {/* The guide: keep all four corners inside it. */}
        <div className="pointer-events-none absolute inset-[12%_10%] rounded-xl border-2 border-dashed border-white/80 shadow-[0_0_0_9999px_rgb(0_0_0/0.35)]" />
        <button
          type="button"
          onClick={() => dialogRef.current.close()}
          aria-label="Close the camera"
          className="absolute right-3 top-3 rounded-full bg-black/50 p-2 hover:bg-black/70"
        >
          <X className="size-5" aria-hidden="true" />
        </button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 p-4">
        <p className="text-sm text-white/85">
          {error || `Fit the ${side} of the card inside the frame, hold steady, then capture.`}
        </p>
        <button
          type="button"
          onClick={capture}
          disabled={Boolean(error)}
          className="inline-flex items-center gap-2 rounded-md bg-gate px-4 py-2.5 font-semibold hover:bg-gate-dark disabled:opacity-50"
        >
          <Camera className="size-4" aria-hidden="true" /> Capture
        </button>
      </div>
    </dialog>
  )
}

function SideSlot({ side, label, hint, file, mistakes, disabled, onPick, onCamera, onClear }) {
  const inputRef = useRef(null)
  const cameraInputRef = useRef(null)
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
  useEffect(() => () => preview && URL.revokeObjectURL(preview), [preview])
  const hasCameraApi = typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia)
  const flagged = mistakes.length > 0

  return (
    <div id={`kyc-${side}`} className="min-w-0">
      <p className="text-sm font-semibold">{label}</p>
      <p className="text-xs text-ink-soft">{hint}</p>
      <div
        className={`mt-2 overflow-hidden rounded-lg border-2 ${
          flagged ? 'border-brass' : file ? 'border-gate/60' : 'border-dashed border-rule'
        } bg-white`}
      >
        {file ? (
          <div className="relative">
            <img src={preview} alt={`${label} of your ID`} className="aspect-[1.586] w-full object-cover" />
            <button
              type="button"
              disabled={disabled}
              onClick={onClear}
              className="absolute right-2 top-2 inline-flex items-center gap-1 rounded bg-sheet/95 px-2 py-1 text-xs font-semibold shadow hover:bg-white disabled:opacity-60"
            >
              <RotateCcw className="size-3.5" aria-hidden="true" /> Retake
            </button>
          </div>
        ) : (
          <div className="flex aspect-[1.586] flex-col items-center justify-center gap-2 p-4 text-center">
            <ScanSearch className="size-7 text-ink-soft/60" aria-hidden="true" />
            <div className="flex flex-wrap justify-center gap-2">
              <button
                type="button"
                disabled={disabled}
                onClick={() => (hasCameraApi ? onCamera() : cameraInputRef.current.click())}
                className="inline-flex items-center gap-1.5 rounded-md bg-gate px-3 py-2 text-sm font-semibold text-white hover:bg-gate-dark disabled:opacity-60"
              >
                <Camera className="size-4" aria-hidden="true" /> Take photo
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => inputRef.current.click()}
                className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-white px-3 py-2 text-sm font-semibold hover:border-ink disabled:opacity-60"
              >
                <ImageUp className="size-4" aria-hidden="true" /> Upload
              </button>
            </div>
          </div>
        )}
      </div>
      {[inputRef, cameraInputRef].map((ref, index) => (
        <input
          key={index}
          ref={ref}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/*"
          capture={index === 1 ? 'environment' : undefined}
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => {
            const picked = event.target.files?.[0]
            event.target.value = ''
            if (picked) onPick(picked)
          }}
        />
      ))}
      {flagged && (
        <ul className="mt-2 space-y-1">
          {mistakes.map((mistake) => (
            <li key={mistake.code} className="flex gap-1.5 text-xs text-[#8a6410]">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              {mistake.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function KYCVerificationCard({ className = '' }) {
  const { user, refreshUser } = useAuth()
  const [docType, setDocType] = useState('NID')
  const [photos, setPhotos] = useState({ front: null, back: null })
  const [camera, setCamera] = useState(null)
  const [retry, setRetry] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const status = user.kyc_status
  const [stampLabel, stampTone] = STAMPS[status] ?? STAMPS.NOT_SUBMITTED
  const docLabel = KYC_DOC_TYPES.find((type) => type.value === docType)?.label ?? 'ID'

  async function setPhoto(side, file) {
    setError('')
    if (!file.type.startsWith('image/')) return setError('That file isn’t a photo. Use a JPEG, PNG or WebP picture of the card.')
    const ready = await shrink(file, `${side}.jpg`)
    if (ready.size > MAX_BYTES) return setError('That photo is over 10 MB. Take a new one with the camera instead.')
    setPhotos((current) => ({ ...current, [side]: ready }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (!photos.front || !photos.back) return setError('Add a photo of both sides of the card.')
    setError('')
    setRetry(null)
    setBusy(true)
    try {
      const result = await autoVerifyKyc({ docType, front: photos.front, back: photos.back })
      if (result.kyc_status === 'NEEDS_RETRY') {
        setRetry(result)
      } else {
        setPhotos({ front: null, back: null })
        await refreshUser()
      }
    } catch (err) {
      setError(getErrorMessage(err))
      // "Already verified" or "being checked": show the current status.
      if (err.response?.status === 409) await refreshUser()
    } finally {
      setBusy(false)
    }
  }

  function tryAgain() {
    const sides = new Set(retry.mistakes.map((mistake) => mistake.side))
    setPhotos((current) => ({ front: sides.has('front') ? null : current.front, back: sides.has('back') ? null : current.back }))
    setRetry(null)
    document.getElementById(`kyc-${sides.has('front') ? 'front' : 'back'}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  const mistakesFor = (side) => (retry?.mistakes ?? []).filter((mistake) => mistake.side === side)
  const checklist = [
    [Sun, 'Good lighting', 'A bright room, no shadows over the card.'],
    [ZapOff, 'No flash glare', 'Flash off; tilt the card if light reflects on it.'],
    [Crop, 'All 4 corners visible', 'The whole card, flat, filling most of the frame.'],
    [CircleUser, 'Profile name matches ID', `Your profile says “${user.full_name}”.`],
  ]

  return (
    <section className={`rounded-xl border border-rule bg-sheet shadow-sm ${className}`} aria-labelledby="kyc-heading">
      <div className="flex flex-col-reverse items-start gap-3 border-b border-rule p-5 sm:flex-row sm:justify-between sm:gap-4 sm:p-7">
        <div>
          <h2 id="kyc-heading" className="font-display text-2xl font-extrabold uppercase tracking-wide">
            Identity verification
          </h2>
          <p className="mt-1 text-sm text-ink-soft">
            Photograph both sides of your National ID, Student ID or Job ID. It's checked automatically in under a minute.
          </p>
        </div>
        <Stamp tone={stampTone}>{stampLabel}</Stamp>
      </div>

      <div className="p-5 sm:p-7">
        {status === 'VERIFIED' && (
          <div className="flex items-start gap-4 rounded-lg border border-gate/40 bg-gate/8 p-5">
            <BadgeCheck className="size-10 shrink-0 text-gate" aria-hidden="true" />
            <div>
              <p className="font-display text-xl font-extrabold uppercase tracking-wide text-gate-dark">Verified Badge Unlocked</p>
              <p className="mt-1 text-sm">
                Your ID has been verified successfully. Owners and tenants now see the verified badge next to your name.
              </p>
            </div>
          </div>
        )}

        {status === 'REVOKED' && (
          <div role="alert" className="flex items-start gap-4 rounded-lg border border-tag-owner/50 bg-tag-owner/8 p-5">
            <ShieldAlert className="size-10 shrink-0 text-tag-owner" aria-hidden="true" />
            <div className="text-sm">
              <p className="font-semibold text-tag-owner">Account restricted</p>
              <p className="mt-1">
                Verification revoked: This ID document is already associated with another account or violates our
                single-account verification policy.
              </p>
              <p className="mt-3">
                If this ID is yours, you can appeal. Email a short video of yourself holding the card, showing the front
                and the back, to{' '}
                <a href={`mailto:${KYC_APPEAL_EMAIL}?subject=ID%20verification%20appeal`} className="font-semibold text-gate underline">
                  {KYC_APPEAL_EMAIL}
                </a>{' '}
                from the email address on your account. An admin will review it and can restore your account.
              </p>
            </div>
          </div>
        )}

        {status === 'PENDING' && (
          <div className="flex items-start gap-4 rounded-lg border border-brass/50 bg-brass/10 p-5">
            <LoaderCircle className="size-8 shrink-0 text-[#8a6410]" aria-hidden="true" />
            <div className="text-sm">
              <p className="font-semibold">We're taking a closer look at your ID</p>
              <p className="mt-1 text-ink-soft">There's nothing you need to do. You'll be notified once it's checked.</p>
            </div>
          </div>
        )}

        {(status === 'NOT_SUBMITTED' || status === 'REJECTED') && (
          <form onSubmit={handleSubmit} className="space-y-6">
            {status === 'REJECTED' && (
              <Alert>
                Your last ID wasn't accepted{user.kyc_review_note ? `: ${user.kyc_review_note}` : '.'} Take new photos to try
                again.
              </Alert>
            )}

            <div>
              <p className="text-sm font-semibold">Before you start</p>
              <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                {checklist.map(([Icon, title, detail]) => (
                  <li key={title} className="flex gap-3 rounded-lg border border-rule bg-white p-3">
                    <Icon className="mt-0.5 size-5 shrink-0 text-gate" aria-hidden="true" />
                    <span className="text-sm">
                      <span className="block font-medium">{title}</span>
                      <span className="text-ink-soft">{detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <Segmented
              legend="Which ID?"
              name="kyc-doc-type"
              value={docType}
              options={KYC_DOC_TYPES.map(({ value, label }) => [value, label])}
              onChange={setDocType}
              className="sm:w-[28rem]"
            />

            <div className="grid gap-5 sm:grid-cols-2">
              {SIDES.map(([side, label, hint]) => (
                <SideSlot
                  key={side}
                  side={side}
                  label={label}
                  hint={hint}
                  file={photos[side]}
                  mistakes={mistakesFor(side)}
                  disabled={busy}
                  onPick={(file) => setPhoto(side, file)}
                  onCamera={() => setCamera(side)}
                  onClear={() => setPhotos((current) => ({ ...current, [side]: null }))}
                />
              ))}
            </div>

            {retry && (
              <div role="alert" className="rounded-lg border border-brass/60 bg-brass/10 p-4">
                <p className="flex items-center gap-2 font-semibold text-[#8a6410]">
                  <AlertTriangle className="size-5" aria-hidden="true" /> {retry.message}
                </p>
                <ul className="mt-2 list-disc space-y-1 pl-6 text-sm">
                  {retry.mistakes.map((mistake) => (
                    <li key={`${mistake.side}-${mistake.code}`}>
                      <span className="font-medium">{mistake.side === 'front' ? 'Front' : 'Back'}:</span> {mistake.message}
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={tryAgain}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-brass px-3 py-2 text-sm font-semibold text-white hover:bg-[#9a7020]"
                >
                  <RotateCcw className="size-4" aria-hidden="true" /> Try Again with a Clearer Photo
                </button>
              </div>
            )}

            <Alert>{error}</Alert>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" busy={busy} disabled={!photos.front || !photos.back}>
                {busy ? 'Checking your ID…' : `Verify my ${docLabel}`}
              </Button>
              <p className="text-xs text-ink-soft">
                {busy ? 'This can take up to half a minute.' : 'Your photos are only seen by you and, if needed, our admins.'}
              </p>
            </div>
          </form>
        )}
      </div>

      {camera && (
        <CameraDialog
          side={camera}
          onClose={() => setCamera(null)}
          onCapture={async (file) => {
            await setPhoto(camera, file)
            setCamera(null)
          }}
        />
      )}
    </section>
  )
}
