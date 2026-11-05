import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import AuthLayout from '../components/AuthLayout.jsx'
import { Alert, Button, TextField } from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'

// Why the app sent someone back here (AuthContext records it when a session ends).
const SESSION_NOTICES = {
  expired: { tone: 'info', text: 'Your session ended. Sign in again to pick up where you left off.' },
  banned: { tone: 'error', text: 'This account has been suspended. Contact Bari Khujun support.' },
}

export default function Login() {
  const { user, sessionNotice, login } = useAuth()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) {
    const from = location.state?.from
    return <Navigate to={from ? `${from.pathname}${from.search ?? ''}` : '/rentals'} replace />
  }
  const notice = SESSION_NOTICES[sessionNotice]

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(form.email.trim(), form.password)
    } catch (err) {
      setError(getErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      intro="Rentals, sales and key handovers between verified people."
      aside={
        <>
          New here?{' '}
          <Link to="/register" className="font-semibold text-gate underline-offset-4 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-5">
        {notice && !error && <Alert tone={notice.tone}>{notice.text}</Alert>}
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={update('email')}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={form.password}
          onChange={update('password')}
        />
        <Alert>{error}</Alert>
        <Button type="submit" busy={busy} className="w-full">
          Sign in
        </Button>
      </form>
    </AuthLayout>
  )
}
