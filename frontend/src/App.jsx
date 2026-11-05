import { lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell, { LISTER_ROLES } from './components/AppShell.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import { LEASE_ROLES } from './constants/roles.js'
import Login from './pages/Login.jsx'
import MyListings from './pages/MyListings.jsx'
import Profile from './pages/Profile.jsx'
import Register from './pages/Register.jsx'
import VerifyLease from './pages/VerifyLease.jsx'

// Map pages pull in Leaflet, so they load on demand.
const RentalSearch = lazy(() => import('./pages/RentalSearch.jsx'))
const RentalDetail = lazy(() => import('./pages/RentalDetail.jsx'))
const ListingEditor = lazy(() => import('./pages/ListingEditor.jsx'))
const SaleSearch = lazy(() => import('./pages/SaleSearch.jsx'))
const SaleDetail = lazy(() => import('./pages/SaleDetail.jsx'))
const SaleEditor = lazy(() => import('./pages/SaleEditor.jsx'))
const Dashboard = lazy(() => import('./pages/Dashboard.jsx'))
const LeaseWorkspace = lazy(() => import('./pages/LeaseWorkspace.jsx'))
const UserReviews = lazy(() => import('./pages/UserReviews.jsx'))
const AdminGovernanceCenter = lazy(() => import('./pages/AdminGovernanceCenter.jsx'))

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/verify-lease/:bookingId" element={<VerifyLease />} />
      <Route element={<AppShell />}>
        <Route path="/rentals" element={<RentalSearch />} />
        <Route path="/rentals/:id" element={<RentalDetail />} />
        <Route path="/sale" element={<SaleSearch />} />
        <Route path="/sale/:id" element={<SaleDetail />} />
        <Route path="/users/:id" element={<UserReviews />} />
        {/* Every role: each one gets its own dashboard tabs. */}
        <Route element={<ProtectedRoute />}>
          <Route path="/profile" element={<Profile />} />
          <Route path="/dashboard" element={<Dashboard />} />
        </Route>
        <Route element={<ProtectedRoute allowedRoles={LEASE_ROLES} />}>
          <Route path="/leases/:bookingId" element={<LeaseWorkspace />} />
        </Route>
        <Route element={<ProtectedRoute allowedRoles={['ADMIN']} />}>
          <Route path="/admin/governance" element={<AdminGovernanceCenter />} />
        </Route>
        <Route element={<ProtectedRoute allowedRoles={['OWNER']} />}>
          <Route path="/sale/new" element={<SaleEditor />} />
          <Route path="/sale/:id/edit" element={<SaleEditor />} />
        </Route>
        <Route element={<ProtectedRoute allowedRoles={LISTER_ROLES} />}>
          <Route path="/listings" element={<MyListings />} />
          <Route path="/listings/new" element={<ListingEditor />} />
          <Route path="/listings/:id/edit" element={<ListingEditor />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/rentals" replace />} />
    </Routes>
  )
}
