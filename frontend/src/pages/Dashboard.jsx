import { useSearchParams } from 'react-router-dom'
import { KycReviewsPanel, TitleReviewsPanel } from '../components/dashboard/AdminPanels.jsx'
import DisputesPanel from '../components/dashboard/DisputesPanel.jsx'
import LeasesPanel from '../components/dashboard/LeasesPanel.jsx'
import OffersPanel from '../components/dashboard/OffersPanel.jsx'
import { OwnerRequestsPanel, TenantRentalsPanel } from '../components/dashboard/RentalPanels.jsx'
import VisitsPanel from '../components/dashboard/VisitsPanel.jsx'
import { ROLES } from '../constants/roles.js'
import { useAuth } from '../context/AuthContext.jsx'

const SellerOffers = () => <OffersPanel side="seller" />
const BuyerOffers = () => <OffersPanel side="buyer" />

// [tab key, label, panel] per role. Bachelor tenants can be both tenant and sub-letter.
const TABS = {
  OWNER: [
    ['leases', 'Leases', LeasesPanel],
    ['requests', 'Rent requests', OwnerRequestsPanel],
    ['offers', 'Offers received', SellerOffers],
    ['visits', 'Visits', VisitsPanel],
    ['disputes', 'Disputes', DisputesPanel],
  ],
  BACHELOR_TENANT: [
    ['leases', 'Leases', LeasesPanel],
    ['rentals', 'Requests', TenantRentalsPanel],
    ['requests', 'Sublet requests', OwnerRequestsPanel],
    ['visits', 'Visits', VisitsPanel],
    ['disputes', 'Disputes', DisputesPanel],
  ],
  FAMILY_TENANT: [
    ['leases', 'Leases', LeasesPanel],
    ['rentals', 'Requests', TenantRentalsPanel],
    ['visits', 'Visits', VisitsPanel],
    ['disputes', 'Disputes', DisputesPanel],
  ],
  BUYER: [
    ['offers', 'My offers', BuyerOffers],
    ['visits', 'Visits', VisitsPanel],
    ['disputes', 'Disputes', DisputesPanel],
  ],
  ADMIN: [
    ['titles', 'Title reviews', TitleReviewsPanel],
    ['kyc', 'KYC reviews', KycReviewsPanel],
  ],
}

export default function Dashboard() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const tabs = TABS[user.role]
  const [activeKey, , Panel] = tabs.find(([key]) => key === params.get('tab')) ?? tabs[0]

  return (
    <div className="mx-auto w-full max-w-4xl px-4 pb-28 pt-8 sm:px-6">
      <p className="text-sm font-medium text-ink-soft">{ROLES[user.role].title}</p>
      <h1 className="font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">Dashboard</h1>
      <div role="tablist" aria-label="Dashboard sections" className="mt-6 flex gap-1 overflow-x-auto shadow-[inset_0_-1px_0_var(--color-rule)]">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === activeKey}
            onClick={() => setParams({ tab: key }, { replace: true })}
            className={`shrink-0 border-b-2 px-3 py-2 text-sm font-semibold transition-colors ${
              key === activeKey ? 'border-ink text-ink' : 'border-transparent text-ink-soft hover:text-ink'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="mt-6">
        <Panel key={activeKey} />
      </div>
    </div>
  )
}
