import { LoaderCircle, ShieldX } from 'lucide-react'
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { ROLES } from '../constants/roles.js'
import { useAuth } from '../context/AuthContext.jsx'

const listFormat = new Intl.ListFormat('en', { type: 'conjunction' })
const withArticle = (noun) => `${/^[aeiou]/i.test(noun) ? 'an' : 'a'} ${noun}`

// Wrong role for this page: say whose page it is instead of silently bouncing somewhere else.
function AccessDenied({ allowedRoles, role }) {
  const audience = listFormat.format(allowedRoles.map((allowed) => `${ROLES[allowed].title.toLowerCase()}s`))
  return (
    <div className="mx-auto w-full max-w-xl px-4 py-16 text-center sm:px-6">
      <ShieldX className="mx-auto size-10 text-tag-owner" aria-hidden="true" />
      <h1 className="mt-4 font-display text-3xl font-extrabold uppercase tracking-wide">Not available to your account</h1>
      <p className="mt-3 text-ink-soft">
        This page is for {audience}. You're signed in as {withArticle(ROLES[role].title.toLowerCase())}.
      </p>
      <Link to="/dashboard" className="mt-6 inline-block font-semibold text-gate hover:underline">
        Go to your dashboard
      </Link>
    </div>
  )
}

// Gate for signed-in pages. Checks the session first, then `allowedRoles` (all signed-in roles when omitted).
// The API enforces the same rules on every request; this keeps people out of screens they can't use.
export default function ProtectedRoute({ allowedRoles }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="grid min-h-dvh place-items-center text-ink-soft" role="status">
        <LoaderCircle className="size-6 animate-spin" aria-label="Loading your account" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  if (allowedRoles && !allowedRoles.includes(user.role)) return <AccessDenied allowedRoles={allowedRoles} role={user.role} />
  return <Outlet />
}
