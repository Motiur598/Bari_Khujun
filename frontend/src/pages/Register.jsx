import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { getErrorMessage } from '../api/client.js'
import AuthLayout from '../components/AuthLayout.jsx'
import RoleTagPicker from '../components/RoleTagPicker.jsx'
import { Alert, Button, TextField } from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'

const EMPTY_FORM = { full_name: '', email: '', phone: '', password: '' }

export default function Register() {
  const { user, register } = useAuth()
  const [role, setRole] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/profile" replace />

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  async function handleSubmit(event) {
    event.preventDefault()
    if (!role) {
      setError('Pick a role to continue.')
      return
    }
    setError('')
    setBusy(true)
    try {
      await register({
        ...form,
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        role,
      })
    } catch (err) {
      setError(getErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      intro="Choose how you'll use Bari Khujun. You'll verify your identity from your profile afterwards."
      width="max-w-xl"
      aside={
        <>
          Already registered?{' '}
          <Link to="/login" className="font-semibold text-gate underline-offset-4 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-5">
        <RoleTagPicker value={role} onChange={setRole} />
        <div className="grid gap-5 sm:grid-cols-2">
          <TextField
            label="Full name"
            autoComplete="name"
            required
            minLength={2}
            maxLength={100}
            value={form.full_name}
            onChange={update('full_name')}
            className="sm:col-span-2"
          />
          <TextField
            label="Email"
            type="email"
            autoComplete="email"
            required
            value={form.email}
            onChange={update('email')}
          />
          <TextField
            label="Phone"
            type="tel"
            autoComplete="tel"
            placeholder="+8801XXXXXXXXX"
            required
            pattern="\+?[0-9][0-9 \-]{5,19}"
            value={form.phone}
            onChange={update('phone')}
          />
          <TextField
            label="Password"
            type="password"
            autoComplete="new-password"
            hint="At least 8 characters."
            required
            minLength={8}
            maxLength={72}
            value={form.password}
            onChange={update('password')}
            className="sm:col-span-2"
          />
        </div>
        <Alert>{error}</Alert>
        <Button type="submit" busy={busy} className="w-full">
          Create account
        </Button>
      </form>
    </AuthLayout>
  )
}
