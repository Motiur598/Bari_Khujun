import { useCallback, useEffect, useMemo, useState } from 'react'
import { RADIUS, hasCenter, readTarget, targetParams } from './target.js'

// The tenant's target area for a feed page: read from the URL, changed through `select`, plus the map-pick mode and
// the radius slider. `update` is useUrlFilters().update.
export default function useShiftingTarget(params, update) {
  const query = params.toString()
  const target = useMemo(() => readTarget(new URLSearchParams(query)), [query])
  const sort = params.get('sort')
  const [picking, setPicking] = useState(false)
  const [radius, setRadius] = useState(target?.radius ?? RADIUS.initial)

  // Follow the URL when it changes underneath us (back button, a shared link).
  useEffect(() => {
    if (target?.radius) setRadius(target.radius)
  }, [target?.radius])

  const select = useCallback(
    (next) => {
      // "Nearest first" needs a centre, which an area-name target doesn't have.
      const dropSort = sort === 'distance' && !hasCenter(next)
      update({ ...targetParams(next), ...(dropSort ? { sort: '' } : {}) })
    },
    [sort, update],
  )

  // Moving the slider re-runs a radius search once the thumb settles.
  useEffect(() => {
    if (!hasCenter(target) || radius === target.radius) return
    const timer = setTimeout(() => select({ ...target, radius }), 300)
    return () => clearTimeout(timer)
  }, [radius, target, select])

  // Map clicks only count while "Pick shifting spot on map" is on, so panning the results map never moves the search.
  const pickPoint = useCallback(
    ({ lat, lng }) => {
      if (picking) select({ kind: 'point', lat, lng, radius })
    },
    [picking, radius, select],
  )

  return { target, picking, setPicking, radius, setRadius, select, pickPoint }
}
