import { LogOut, MonitorX, Pencil } from 'lucide-react'
import { useState } from 'react'
import api, { getErrorMessage } from '../api/client.js'
import KeyTag from '../components/KeyTag.jsx'
import KYCVerificationCard from '../components/KYCVerificationCard.jsx'
import { Alert, Button, TextField } from '../components/ui.jsx'
import { ROLES } from '../constants/roles.js'
import { useAuth } from '../context/AuthContext.jsx'

// Name and phone are the only details a user can change; the API rejects anything else.
function DetailsForm({ user, onSaved, onCancel }) {
  const [form, setForm] = useState({ full_name: user.full_name, phone: user.phone })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // Once ID documents are in review, verified or revoked, the name has to keep matching them.
  const nameLocked = ['PENDING', 'VERIFIED', 'REVOKED'].includes(user.kyc_status)

  async function handleSubmit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const changes = { phone: form.phone.trim() }
      if (!nameLocked) changes.full_name = form.full_name.trim()
      onSaved((await api.patch('/auth/me', changes)).data)
    } catch (err) {
      setError(getErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-6 space-y-4 rounded-xl border border-rule bg-sheet p-5 sm:p-7">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Full name"
          required
          minLength={2}
          maxLength={100}
          value={form.full_name}
          disabled={nameLocked}
          hint={nameLocked ? 'Locked to your ID documents. Contact support to correct it.' : undefined}
          onChange={(event) => setForm({ ...form, full_name: event.target.value })}
        />
        <TextField
          label="Phone"
          type="tel"
          autoComplete="tel"
          required
          value={form.phone}
          onChange={(event) => setForm({ ...form, phone: event.target.value })}
        />
      </div>
      <Alert>{error}</Alert>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" busy={busy}>
          Save changes
        </Button>
        <button type="button" onClick={onCancel} className="rounded-md px-4 py-2.5 text-sm font-semibold text-ink-soft hover:text-ink">
          Cancel
        </button>
      </div>
    </form>
  )
}

export default function Profile() {
  const { user, logout, setUser } = useAuth()
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)
  const role = ROLES[user.role]

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 sm:py-12">
      <section className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex items-start gap-4 sm:gap-6">
          <KeyTag role={user.role} className="w-20 shrink-0 rotate-2 shadow-md sm:w-24" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink-soft">{role.title}</p>
            <h1 className="break-words font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">
              {user.full_name}
            </h1>
            <p className="mt-2 text-sm text-ink-soft">
              <span className="break-all">{user.email}</span> ·{' '}
              <span className="whitespace-nowrap">{user.phone}</span>
            </p>
          </div>
        </div>
        <dl className="shrink-0 sm:text-right">
          <dt className="text-xs font-medium uppercase tracking-widest text-ink-soft">Trust score</dt>
          <dd className="font-mono text-3xl font-medium">{user.trust_score}</dd>
        </dl>
      </section>

      {editing ? (
        <DetailsForm
          user={user}
          onCancel={() => setEditing(false)}
          onSaved={(updated) => {
            setUser(updated)
            setEditing(false)
            setSaved(true)
          }}
        />
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          <button
            type="button"
            onClick={() => {
              setSaved(false)
              setEditing(true)
            }}
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-gate hover:underline"
          >
            <Pencil className="size-4" aria-hidden="true" /> Edit name and phone
          </button>
          {saved && (
            <p role="status" className="text-sm text-gate-dark">
              Changes saved.
            </p>
          )}
        </div>
      )}

      {user.role === 'ADMIN' ? (
        <p className="mt-10 rounded-xl border border-rule bg-sheet p-5 text-sm text-ink-soft sm:p-7">
          Admin accounts don't need identity verification.
        </p>
      ) : (
        <KYCVerificationCard className="mt-10" />
      )}
      <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2">
        {/* The header has no room for sign-out on phones, so it lives here. */}
        <button
          type="button"
          onClick={logout}
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-soft hover:text-ink sm:hidden"
        >
          <LogOut className="size-4" aria-hidden="true" /> Sign out
        </button>
        <button
          type="button"
          onClick={async () => {
            if (!window.confirm('Sign out on every device, including this one?')) return
            await api.post('/auth/logout-all').catch(() => {})
            logout()
          }}
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-soft hover:text-ink"
        >
          <MonitorX className="size-4" aria-hidden="true" /> Sign out on all devices
        </button>
      </div>
    </div>
  )
}
