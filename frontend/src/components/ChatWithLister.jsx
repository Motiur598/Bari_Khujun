import { MessageCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useRealtime } from '../context/RealtimeContext.jsx'

// "Chat with owner / seller" on a listing page. Opens the chat drawer on this listing's thread with its lister.
export default function ChatWithLister({ listing, label, className = '' }) {
  const { user } = useAuth()
  const { openChat } = useRealtime()
  const style = `inline-flex w-full items-center justify-center gap-2 rounded-md border border-ink bg-white px-3 py-2.5 text-sm font-semibold text-ink hover:bg-ink hover:text-white ${className}`

  if (user?.id === listing.lister_id) return null
  if (!user) {
    const pathname = `/${listing.listing_mode === 'SALE' ? 'sale' : 'rentals'}/${listing.id}`
    return (
      <Link to="/login" state={{ from: { pathname } }} className={style}>
        <MessageCircle className="size-4" aria-hidden="true" /> Sign in to {label.toLowerCase()}
      </Link>
    )
  }
  return (
    <button
      type="button"
      onClick={() =>
        openChat({ propertyId: listing.id, otherUserId: listing.lister_id, otherName: listing.lister?.full_name, listingTitle: listing.title })
      }
      className={style}
    >
      <MessageCircle className="size-4" aria-hidden="true" /> {label}
    </button>
  )
}
