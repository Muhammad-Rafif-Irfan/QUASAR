import { useState, useCallback, useMemo, useEffect } from 'react'

// ─── Da Nang demo coordinates (matches backend demo data) ────────────
export type MapLocation = {
  id: string
  name: string
  lat: number
  lon: number
  weight?: string
}

export type TruckRoute = {
  truckId: string
  truckName: string
  capacity: string
  color: string
  /** Ordered waypoints including depot at start/end */
  waypoints: MapLocation[]
  /** Order IDs assigned to this truck */
  orderIds: string[]
  /** Detailed road geometry from OSRM — hundreds of points following real roads */
  roadGeometry: [number, number][]
  /** Road distance in meters from OSRM */
  roadDistance: number
}

export const DEPOT: MapLocation = {
  id: 'depot',
  name: 'Depot Pusat',
  lat: 16.0544,
  lon: 108.2022,
}

/** Pre-assigned Da Nang coordinates for the demo orders N1–N4. */
const DEMO_COORDS: Record<string, { name: string; lat: number; lon: number }> = {
  N1: { name: 'Pelabuhan', lat: 16.0650, lon: 108.2200 },
  N2: { name: 'Pasar Con', lat: 16.0450, lon: 108.2100 },
  N3: { name: 'Bandara', lat: 16.0438, lon: 108.1990 },
  N4: { name: 'Hai Chau District', lat: 16.0680, lon: 108.2140 },
}

/** Extra location pool for dynamically added orders. */
const EXTRA_LOCATIONS: { name: string; lat: number; lon: number }[] = [
  { name: 'Son Tra District', lat: 16.0930, lon: 108.2480 },
  { name: 'Lien Chieu District', lat: 16.0780, lon: 108.1510 },
  { name: 'Thanh Khe Market', lat: 16.0600, lon: 108.1880 },
  { name: 'Ngu Hanh Son', lat: 16.0190, lon: 108.2520 },
  { name: 'Hoa Vang District', lat: 16.0070, lon: 108.1350 },
  { name: 'My Khe Beach', lat: 16.0560, lon: 108.2470 },
  { name: 'Dragon Bridge Area', lat: 16.0612, lon: 108.2278 },
  { name: 'Marble Mountains', lat: 16.0035, lon: 108.2630 },
]

let extraIndex = 0

// ─── Haversine helper (metres) ────────────────────────────────────────
function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6_371_000
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

// ─── Greedy nearest-neighbour route ───────────────────────────────────
function greedyRoute(depot: MapLocation, stops: MapLocation[]): MapLocation[] {
  if (stops.length === 0) return [depot, depot]
  const remaining = [...stops]
  const route: MapLocation[] = [depot]
  let current = depot
  while (remaining.length > 0) {
    let bestIdx = 0
    let bestDist = Infinity
    for (let i = 0; i < remaining.length; i++) {
      const d = haversine(current.lat, current.lon, remaining[i].lat, remaining[i].lon)
      if (d < bestDist) {
        bestDist = d
        bestIdx = i
      }
    }
    current = remaining.splice(bestIdx, 1)[0]
    route.push(current)
  }
  route.push(depot)
  return route
}

// ─── OSRM road routing ───────────────────────────────────────────────
/**
 * Fetch actual road geometry from the OSRM public API.
 * Returns an array of [lat, lon] points following real roads.
 * Falls back to straight-line waypoints on any error.
 */
async function fetchRoadRoute(waypoints: MapLocation[]): Promise<{ geometry: [number, number][]; distance: number }> {
  if (waypoints.length < 2) {
    return { geometry: waypoints.map((wp) => [wp.lat, wp.lon] as [number, number]), distance: 0 }
  }

  // OSRM expects lon,lat format (not lat,lon)
  const coords = waypoints.map((wp) => `${wp.lon},${wp.lat}`).join(';')
  const url = `https://router.project-osrm.org/route/v1/driving/${coords}?overview=full&geometries=geojson`

  try {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`OSRM HTTP ${response.status}`)

    const data = await response.json()
    if (data.code !== 'Ok' || !data.routes?.[0]) {
      throw new Error(`OSRM error: ${data.code}`)
    }

    const route = data.routes[0]
    // GeoJSON coordinates are [lon, lat], convert to [lat, lon] for Leaflet
    const geometry: [number, number][] = route.geometry.coordinates.map(
      (coord: [number, number]) => [coord[1], coord[0]] as [number, number],
    )
    const distance: number = route.distance // meters

    return { geometry, distance }
  } catch (err) {
    console.warn('OSRM routing failed, using straight lines:', err)
    // Fallback: straight lines between waypoints
    return {
      geometry: waypoints.map((wp) => [wp.lat, wp.lon] as [number, number]),
      distance: waypoints.reduce((total, wp, i) => {
        if (i === 0) return 0
        return total + haversine(waypoints[i - 1].lat, waypoints[i - 1].lon, wp.lat, wp.lon)
      }, 0),
    }
  }
}

// ─── Main hook ────────────────────────────────────────────────────────
export function useRouteSimulation() {
  const [stops, setStops] = useState<MapLocation[]>(() => {
    return Object.entries(DEMO_COORDS).map(([id, coord]) => ({
      id,
      name: coord.name,
      lat: coord.lat,
      lon: coord.lon,
    }))
  })

  /** Add a new stop at a specific lat/lon (e.g. user clicked the map). */
  const addStop = useCallback((lat: number, lon: number, label?: string) => {
    setStops((prev) => {
      const nextIdx = Math.max(0, ...prev.map((s) => Number(s.id.replace('N', '')) || 0)) + 1
      const name = label || `New Stop ${nextIdx}`
      return [...prev, { id: `N${nextIdx}`, name, lat, lon }]
    })
  }, [])

  /** Add a stop from the "Add new order" modal — auto-assign coordinates. */
  const addStopAuto = useCallback((orderId: string, address?: string) => {
    setStops((prev) => {
      // Pick next available location from the pool
      const loc = EXTRA_LOCATIONS[extraIndex % EXTRA_LOCATIONS.length]
      extraIndex++
      return [
        ...prev,
        {
          id: orderId,
          name: address || loc.name,
          lat: loc.lat + (Math.random() - 0.5) * 0.003,
          lon: loc.lon + (Math.random() - 0.5) * 0.003,
        },
      ]
    })
  }, [])

  /** Split stops across two trucks and compute greedy waypoint order. */
  const baseRoutes = useMemo(() => {
    const half = Math.ceil(stops.length / 2)
    const truck1Stops = stops.slice(0, half)
    const truck2Stops = stops.slice(half)

    const routes: { truckId: string; truckName: string; capacity: string; color: string; waypoints: MapLocation[]; orderIds: string[] }[] = []

    if (truck1Stops.length > 0) {
      routes.push({
        truckId: 'truck-1',
        truckName: 'Truck 1',
        capacity: '60 kg',
        color: '#2563eb',
        waypoints: greedyRoute(DEPOT, truck1Stops),
        orderIds: truck1Stops.map((s) => s.id),
      })
    }

    if (truck2Stops.length > 0) {
      routes.push({
        truckId: 'truck-2',
        truckName: 'Truck 2',
        capacity: '100 kg',
        color: '#16a34a',
        waypoints: greedyRoute(DEPOT, truck2Stops),
        orderIds: truck2Stops.map((s) => s.id),
      })
    }

    return routes
  }, [stops])

  // Fetch real road geometry from OSRM for each truck route
  const [truckRoutes, setTruckRoutes] = useState<TruckRoute[]>([])

  useEffect(() => {
    let cancelled = false

    async function fetchAllRoadRoutes() {
      const enriched: TruckRoute[] = await Promise.all(
        baseRoutes.map(async (route) => {
          const { geometry, distance } = await fetchRoadRoute(route.waypoints)
          return {
            ...route,
            roadGeometry: geometry,
            roadDistance: distance,
          }
        }),
      )

      if (!cancelled) {
        setTruckRoutes(enriched)
      }
    }

    // Set immediate straight-line routes first (so UI is never empty)
    setTruckRoutes(
      baseRoutes.map((route) => ({
        ...route,
        roadGeometry: route.waypoints.map((wp) => [wp.lat, wp.lon] as [number, number]),
        roadDistance: 0,
      })),
    )

    // Then fetch real road geometry in background
    fetchAllRoadRoutes()

    return () => {
      cancelled = true
    }
  }, [baseRoutes])

  const totalDistance = useMemo(() => {
    // Prefer OSRM road distances; fall back to haversine
    const roadTotal = truckRoutes.reduce((sum, r) => sum + r.roadDistance, 0)
    if (roadTotal > 0) return Math.round(roadTotal)

    let total = 0
    for (const route of truckRoutes) {
      for (let i = 0; i < route.waypoints.length - 1; i++) {
        total += haversine(
          route.waypoints[i].lat,
          route.waypoints[i].lon,
          route.waypoints[i + 1].lat,
          route.waypoints[i + 1].lon,
        )
      }
    }
    return Math.round(total)
  }, [truckRoutes])

  return {
    depot: DEPOT,
    stops,
    truckRoutes,
    totalDistance,
    addStop,
    addStopAuto,
  }
}
