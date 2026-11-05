import { ImageOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import api from '../api/client.js'

// Private photos need the bearer token, so they're fetched as blobs rather than linked directly.
export default function AuthImage({ path, alt, className = '' }) {
  const [src, setSrc] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let url
    let cancelled = false
    api
      .get(path, { responseType: 'blob' })
      .then(({ data }) => {
        if (cancelled) return
        url = URL.createObjectURL(data)
        setSrc(url)
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [path])

  if (failed) {
    return (
      <div className={`grid place-items-center bg-plaster text-ink-soft ${className}`}>
        <ImageOff className="size-5" aria-label="Photo unavailable" />
      </div>
    )
  }
  if (!src) return <div className={`animate-pulse bg-plaster ${className}`} aria-hidden="true" />
  return (
    <a href={src} target="_blank" rel="noreferrer" className="block">
      <img src={src} alt={alt} className={`object-cover ${className}`} />
    </a>
  )
}
