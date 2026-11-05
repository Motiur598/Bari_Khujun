import { CircleUser, House, KeyRound, LayoutDashboard, LayoutList, LoaderCircle, LogOut, Menu, Plus, ShieldAlert, X } from 'lucide-react'
import { Suspense, useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import ChatDrawer from './ChatDrawer.jsx'
import NotificationBell, { MessagesButton } from './realtime/NotificationBell.jsx'
import ToastStack from './realtime/ToastStack.jsx'
import CompareModal from './rentals/CompareModal.jsx'
import CompareTray from './rentals/CompareTray.jsx'
import { Wordmark } from './ui.jsx'

export const LISTER_ROLES = ['OWNER', 'BACHELOR_TENANT']

function NavItem({ to, icon: Icon, end = false, stacked = false, children }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center rounded-md font-medium transition-colors ${
          stacked ? 'gap-3 px-3 py-3 text-base' : 'gap-1.5 px-2.5 py-2 text-sm'
        } ${isActive ? 'bg-plaster text-ink' : 'text-ink-soft hover:text-ink'}`
      }
    >
      <Icon className={`${stacked ? 'size-5' : 'size-4'} shrink-0`} aria-hidden="true" />
      {children}
    </NavLink>
  )
}

// The header runs edge to edge, with the same side padding as the full-width search pages under it. Wide screens get
// the whole menu in the bar; phones and tablets get the logo, the post button and a menu that drops down.
export default function AppShell() {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const canList = user && LISTER_ROLES.includes(user.role)

  // Following a link, or pressing Escape, closes the phone menu.
  useEffect(() => setMenuOpen(false), [pathname])
  useEffect(() => {
    if (!menuOpen) return undefined
    const onKey = (event) => event.key === 'Escape' && setMenuOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  const links = [
    { to: '/rentals', icon: KeyRound, label: 'Rent' },
    { to: '/sale', icon: House, label: 'Buy' },
    user && { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    user?.role === 'ADMIN' && { to: '/admin/governance', icon: ShieldAlert, label: 'Governance' },
    canList && { to: '/listings', icon: LayoutList, label: 'My listings', end: true },
  ].filter(Boolean)

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-[1100] border-b border-rule bg-sheet">
        <div className="flex h-16 items-center gap-2 px-4 sm:gap-4 sm:px-6">
          <Link to="/rentals" aria-label="Bari Khujun home" className="shrink-0">
            <Wordmark />
          </Link>
          <nav aria-label="Main" className="hidden flex-1 items-center gap-1 lg:flex">
            {links.map(({ to, icon, label, end }) => (
              <NavItem key={to} to={to} icon={icon} end={end}>
                {label}
              </NavItem>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            {canList && (
              <Link
                to={user.role === 'OWNER' ? '/listings' : '/listings/new'}
                className="inline-flex items-center gap-1.5 rounded-md bg-gate px-2.5 py-2 text-sm font-semibold text-white hover:bg-gate-dark"
              >
                <Plus className="size-4" aria-hidden="true" />
                <span className="sr-only sm:not-sr-only">{user.role === 'OWNER' ? 'Post' : 'Sublet seats'}</span>
              </Link>
            )}
            {user && (
              <>
                <MessagesButton />
                <NotificationBell />
              </>
            )}
            {user ? (
              <div className="hidden items-center gap-1 lg:flex">
                <NavItem to="/profile" icon={CircleUser}>
                  {user.full_name.split(' ')[0]}
                </NavItem>
                <button
                  type="button"
                  onClick={logout}
                  className="inline-flex rounded-md p-2 text-ink-soft hover:text-ink"
                  aria-label="Sign out"
                  title="Sign out"
                >
                  <LogOut className="size-4" aria-hidden="true" />
                </button>
              </div>
            ) : (
              <Link to="/login" className="rounded-md px-2.5 py-2 text-sm font-semibold text-gate hover:underline">
                Sign in
              </Link>
            )}
            <button
              type="button"
              onClick={() => setMenuOpen(!menuOpen)}
              aria-expanded={menuOpen}
              aria-controls="phone-menu"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              className="inline-flex size-10 items-center justify-center rounded-md border border-rule text-ink lg:hidden"
            >
              {menuOpen ? <X className="size-5" aria-hidden="true" /> : <Menu className="size-5" aria-hidden="true" />}
            </button>
          </div>
        </div>

        {menuOpen && (
          <>
            <div className="fixed inset-x-0 bottom-0 top-16 bg-ink/30 lg:hidden" aria-hidden="true" onClick={() => setMenuOpen(false)} />
            <nav
              id="phone-menu"
              aria-label="Main"
              className="absolute inset-x-0 top-full max-h-[calc(100dvh-4rem)] overflow-y-auto border-b border-rule bg-sheet px-4 pb-4 pt-2 shadow-lg sm:px-6 lg:hidden"
            >
              <div className="grid gap-1">
                {links.map(({ to, icon, label, end }) => (
                  <NavItem key={to} to={to} icon={icon} end={end} stacked>
                    {label}
                  </NavItem>
                ))}
              </div>
              {user && (
                <div className="mt-2 grid gap-1 border-t border-rule pt-2">
                  <NavItem to="/profile" icon={CircleUser} stacked>
                    {user.full_name}
                  </NavItem>
                  <button
                    type="button"
                    onClick={logout}
                    className="flex items-center gap-3 rounded-md px-3 py-3 text-base font-medium text-ink-soft hover:text-ink"
                  >
                    <LogOut className="size-5 shrink-0" aria-hidden="true" />
                    Sign out
                  </button>
                </div>
              )}
            </nav>
          </>
        )}
      </header>
      <main className="flex flex-1 flex-col">
        <Suspense
          fallback={
            <div className="grid flex-1 place-items-center text-ink-soft" role="status">
              <LoaderCircle className="size-6 animate-spin" aria-label="Loading page" />
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
      <CompareTray />
      <CompareModal />
      {user && <ChatDrawer />}
      <ToastStack />
    </div>
  )
}
