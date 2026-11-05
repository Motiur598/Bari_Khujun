import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { onSessionEnd, TOKEN_KEY } from '../api/client.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const navigate = useNavigate()
  const [user, setUser] = useState(null)
  // Why the last session ended ('expired' or 'banned'), shown on the sign-in page until the next sign-in.
  const [sessionNotice, setSessionNotice] = useState(null)
  // Only block rendering on startup when there is a stored token to validate.
  const [loading, setLoading] = useState(() => Boolean(localStorage.getItem(TOKEN_KEY)))

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setUser(null)
  }, [])

  const startSession = useCallback(({ access_token, user }) => {
    localStorage.setItem(TOKEN_KEY, access_token)
    setSessionNotice(null)
    setUser(user)
    return user
  }, [])

  const login = useCallback(
    async (email, password) => startSession((await api.post('/auth/login', { email, password })).data),
    [startSession],
  )

  const register = useCallback(
    async (payload) => startSession((await api.post('/auth/register', payload)).data),
    [startSession],
  )

  const refreshUser = useCallback(async () => {
    const { data } = await api.get('/auth/me')
    setUser(data)
    return data
  }, [])

  useEffect(() => {
    if (!localStorage.getItem(TOKEN_KEY)) return
    refreshUser()
      .catch(() => logout())
      .finally(() => setLoading(false))
  }, [refreshUser, logout])

  // The API client has already dropped the token (see api/client.js). Clear the user and go to sign-in, which says
  // why. The reason lives here rather than in navigation state, because a protected page redirects on its own as
  // soon as the user is cleared. After a timeout, signing in again returns to the same page.
  useEffect(
    () =>
      onSessionEnd((reason) => {
        setSessionNotice(reason)
        setUser(null)
        const { pathname, search } = window.location
        if (pathname !== '/login') {
          navigate('/login', { replace: true, state: reason === 'expired' ? { from: { pathname, search } } : undefined })
        }
      }),
    [navigate],
  )

  const value = useMemo(
    () => ({ user, loading, sessionNotice, login, register, logout, refreshUser, setUser }),
    [user, loading, sessionNotice, login, register, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
