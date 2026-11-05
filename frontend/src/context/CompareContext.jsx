import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { MAX_COMPARE, areaLabel } from '../constants/rentals.js'

const STORAGE_KEY = 'barikhujun_compare'
const CompareContext = createContext(null)

function readStored() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY))
    return Array.isArray(stored) ? stored.slice(0, MAX_COMPARE) : []
  } catch {
    return []
  }
}

// Keeps a small summary of each picked listing so the tray can render without refetching.
export function CompareProvider({ children }) {
  const [items, setItems] = useState(readStored)
  const [isOpen, setOpen] = useState(false)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
    } catch {
      // Storage can be unavailable (private mode); the tray still works for this visit.
    }
  }, [items])

  const has = useCallback((id) => items.some((item) => item.id === id), [items])

  const toggle = useCallback((listing) => {
    setItems((current) => {
      if (current.some((item) => item.id === listing.id)) return current.filter((item) => item.id !== listing.id)
      if (current.length >= MAX_COMPARE) return current
      return [...current, { id: listing.id, title: listing.title, category: listing.category, area: areaLabel(listing.location) }]
    })
  }, [])

  const remove = useCallback((id) => setItems((current) => current.filter((item) => item.id !== id)), [])
  const clear = useCallback(() => {
    setItems([])
    setOpen(false)
  }, [])

  const value = useMemo(
    () => ({
      items,
      has,
      toggle,
      remove,
      clear,
      isFull: items.length >= MAX_COMPARE,
      isOpen,
      open: () => setOpen(true),
      close: () => setOpen(false),
    }),
    [items, has, toggle, remove, clear, isOpen],
  )

  return <CompareContext.Provider value={value}>{children}</CompareContext.Provider>
}

export function useCompare() {
  const context = useContext(CompareContext)
  if (!context) throw new Error('useCompare must be used inside <CompareProvider>')
  return context
}
