import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getOverview } from '../api/governance.js'
import { KycReviewsPanel } from '../components/dashboard/AdminPanels.jsx'
import ArbitrationTab from '../components/governance/ArbitrationTab.jsx'
import BanDialog from '../components/governance/BanDialog.jsx'
import DeedVaultTab from '../components/governance/DeedVaultTab.jsx'
import QrAuditTab from '../components/governance/QrAuditTab.jsx'
import RadarTab from '../components/governance/RadarTab.jsx'

// [key, label, panel, overview counter shown on the tab]
const TABS = [
  ['radar', 'Scammer radar', RadarTab, 'open_alerts'],
  ['qr', 'QR audit trail', QrAuditTab, 'active_qr_codes'],
  ['deeds', 'Deed vault', DeedVaultTab, 'pending_titles'],
  ['court', 'Arbitration court', ArbitrationTab, 'open_disputes'],
  ['kyc', 'KYC reviews', KycReviewsPanel, null],
]

export default function AdminGovernanceCenter() {
  const [params, setParams] = useSearchParams()
  const [overview, setOverview] = useState(null)
  const [banTarget, setBanTarget] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const refreshOverview = useCallback(() => {
    getOverview().then(setOverview, () => setOverview(null))
  }, [])
  useEffect(refreshOverview, [refreshOverview])

  const [activeKey, , Panel] = TABS.find(([key]) => key === params.get('tab')) ?? TABS[0]

  return (
    <div className="mx-auto w-full max-w-5xl px-4 pb-28 pt-8 sm:px-6">
      <p className="text-sm font-medium text-ink-soft">Fraud detection and dispute arbitration</p>
      <h1 className="font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">Governance</h1>

      {overview && (
        <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            ['Open alerts', overview.open_alerts, overview.open_alerts > 0],
            ['Open disputes', overview.open_disputes, overview.open_disputes > 0],
            ['Titles to review', overview.pending_titles, false],
            ['Live QR codes', overview.active_qr_codes, false],
            ['Banned users', overview.banned_users, false],
          ].map(([label, value, urgent]) => (
            <div key={label} className={`rounded-lg border bg-sheet px-4 py-3 ${urgent ? 'border-tag-owner/50' : 'border-rule'}`}>
              <dt className="text-xs font-medium uppercase tracking-wider text-ink-soft">{label}</dt>
              <dd className={`font-mono text-2xl font-medium ${urgent ? 'text-tag-owner' : ''}`}>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <div role="tablist" aria-label="Governance sections" className="mt-6 flex gap-1 overflow-x-auto shadow-[inset_0_-1px_0_var(--color-rule)]">
        {TABS.map(([key, label, , counter]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === activeKey}
            onClick={() => setParams({ tab: key }, { replace: true })}
            className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-semibold transition-colors ${
              key === activeKey ? 'border-ink text-ink' : 'border-transparent text-ink-soft hover:text-ink'
            }`}
          >
            {label}
            {counter && overview?.[counter] > 0 && (
              <span className="rounded-full bg-plaster px-1.5 font-mono text-xs">{overview[counter]}</span>
            )}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="mt-6">
        <Panel
          key={activeKey}
          refreshKey={refreshKey}
          onChanged={refreshOverview}
          onBan={(person, reason = '') => setBanTarget({ person, reason })}
        />
      </div>

      <BanDialog
        target={banTarget?.person ?? null}
        defaultReason={banTarget?.reason ?? ''}
        onClose={() => setBanTarget(null)}
        onBanned={() => {
          refreshOverview()
          setRefreshKey((n) => n + 1)
        }}
      />
    </div>
  )
}
