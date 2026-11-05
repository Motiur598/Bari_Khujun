import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

// Filters live in the URL so searches can be shared. Empty, false or null values remove the key.
export default function useUrlFilters() {
  const [params, setParams] = useSearchParams()
  const update = useCallback(
    (changes) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current)
          for (const [key, value] of Object.entries(changes)) {
            if (value === '' || value === false || value == null) next.delete(key)
            else next.set(key, value === true ? '1' : String(value))
          }
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  return { params, setParams, update }
}
