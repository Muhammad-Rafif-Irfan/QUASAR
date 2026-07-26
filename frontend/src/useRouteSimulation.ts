import { useState, useCallback, useMemo, useEffect } from 'react'

// ─── Pleiku real-geography demo coordinates (OpenStreetMap) ──────────
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

export type OptimizedFleetRoute = {
  vehicle_id: string
  vehicle_name: string
  capacity: number
  load: number
  route: number[]
  distance_meters: number
}

export type DemoPresetId = 'quantum-3' | 'city-5' | 'fleet-8'

type DemoPreset = {
  id: DemoPresetId
  label: string
  detail: string
  stops: Array<MapLocation & { weight: string; startTime: string; endTime: string }>
}

export const DEPOT: MapLocation = {
  id: 'depot',
  name: 'Pleiku Stadium (demo depot)',
  lat: 13.9791553,
  lon: 108.0049003,
}

/**
 * Real OSM geography, but synthetic delivery demand. Source object IDs and
 * licensing are recorded in docs/demo_data/pleiku_quantum_demo.json.
 */
const DEMO_PRESETS: DemoPreset[] = [
  {
    id: 'quantum-3',
    label: '3 stops · QAOA smoke test',
    detail: 'Small, auditable instance for the verified QAOA flow.',
    stops: [
      { id: 'N1', name: 'Pleiku Airport', lat: 14.0044240, lon: 108.0135476, weight: '12', startTime: '09:00', endTime: '10:00' },
      { id: 'N2', name: 'Biển Hồ Pleiku', lat: 14.0468591, lon: 107.9960066, weight: '38', startTime: '09:00', endTime: '10:00' },
      { id: 'N3', name: 'Chùa Minh Đạo, Diên Phú', lat: 13.9569300, lon: 107.9828185, weight: '24', startTime: '10:00', endTime: '11:00' },
    ],
  },
  {
    id: 'city-5',
    label: '5 stops · city demo',
    detail: 'Classical routing comparison across a compact Pleiku delivery area.',
    stops: [
      { id: 'N1', name: 'Pleiku Airport', lat: 14.0044240, lon: 108.0135476, weight: '12', startTime: '09:00', endTime: '10:00' },
      { id: 'N2', name: 'Biển Hồ Pleiku', lat: 14.0468591, lon: 107.9960066, weight: '38', startTime: '09:00', endTime: '10:00' },
      { id: 'N3', name: 'Chùa Minh Đạo, Diên Phú', lat: 13.9569300, lon: 107.9828185, weight: '24', startTime: '10:00', endTime: '11:00' },
      { id: 'N4', name: 'Đại học Nông Lâm TP. Hồ Chí Minh – Gia Lai', lat: 13.9692560, lon: 108.0200740, weight: '18', startTime: '10:00', endTime: '12:00' },
      { id: 'N5', name: 'Quảng trường Đại Đoàn Kết', lat: 13.9786630, lon: 108.0103610, weight: '28', startTime: '11:00', endTime: '12:00' },
    ],
  },
  {
    id: 'fleet-8',
    label: '8 stops · fleet demo',
    detail: 'A fuller multi-vehicle story for the six-minute presentation.',
    stops: [
      { id: 'N1', name: 'Pleiku Airport', lat: 14.0044240, lon: 108.0135476, weight: '12', startTime: '09:00', endTime: '10:00' },
      { id: 'N2', name: 'Biển Hồ Pleiku', lat: 14.0468591, lon: 107.9960066, weight: '38', startTime: '09:00', endTime: '10:00' },
      { id: 'N3', name: 'Chùa Minh Đạo, Diên Phú', lat: 13.9569300, lon: 107.9828185, weight: '24', startTime: '10:00', endTime: '11:00' },
      { id: 'N4', name: 'Đại học Nông Lâm TP. Hồ Chí Minh – Gia Lai', lat: 13.9692560, lon: 108.0200740, weight: '18', startTime: '10:00', endTime: '12:00' },
      { id: 'N5', name: 'Quảng trường Đại Đoàn Kết', lat: 13.9786630, lon: 108.0103610, weight: '28', startTime: '11:00', endTime: '12:00' },
      { id: 'N6', name: 'Bệnh viện Đại học Y Dược Hoàng Anh Gia Lai', lat: 13.9823900, lon: 108.0007150, weight: '16', startTime: '11:00', endTime: '13:00' },
      { id: 'N7', name: 'Chợ Pleiku', lat: 13.9820590, lon: 108.0034030, weight: '22', startTime: '12:00', endTime: '14:00' },
      { id: 'N8', name: 'Công viên Diên Hồng', lat: 13.9739680, lon: 108.0054850, weight: '14', startTime: '12:00', endTime: '14:00' },
    ],
  },
]

export const demoPresets = DEMO_PRESETS.map(({ id, label, detail, stops }) => ({ id, label, detail, stopCount: stops.length }))

export function getDemoPreset(id: DemoPresetId): DemoPreset {
  const preset = DEMO_PRESETS.find((candidate) => candidate.id === id)
  if (!preset) throw new Error(`Unknown demo preset: ${id}`)
  return preset
}

export const ALL_AVAILABLE_LOCATIONS: { name: string; lat: number; lon: number }[] = [
  { name: 'Pleiku Airport', lat: 14.0044240, lon: 108.0135476 },
  { name: 'Biển Hồ Pleiku', lat: 14.0468591, lon: 107.9960066 },
  { name: 'Chùa Minh Đạo, Diên Phú', lat: 13.9569300, lon: 107.9828185 },
  { name: 'Đại học Nông Lâm TP. Hồ Chí Minh – Gia Lai', lat: 13.9692560, lon: 108.0200740 },
  { name: 'Quảng trường Đại Đoàn Kết', lat: 13.9786630, lon: 108.0103610 },
  { name: 'Bệnh viện Đại học Y Dược Hoàng Anh Gia Lai', lat: 13.9823900, lon: 108.0007150 },
  { name: 'Chợ Pleiku', lat: 13.9820590, lon: 108.0034030 },
  { name: 'Công viên Diên Hồng', lat: 13.9739680, lon: 108.0054850 },
  { name: 'Quy Nhon University', lat: 13.7593966, lon: 109.2172639 },
  { name: 'Binh Dinh Conference Center', lat: 13.7731162, lon: 109.2217008 },
  { name: 'Quy Nhon city centre', lat: 13.7549672, lon: 109.1767596 },
  { name: 'ICISE Center, Quy Nhon (QC4SG venue)', lat: 13.7013, lon: 109.1837 },
]

/** Extra location pool for dynamically added orders. */
const EXTRA_LOCATIONS: { name: string; lat: number; lon: number }[] = [
  { name: 'Quy Nhon University', lat: 13.7593966, lon: 109.2172639 },
  { name: 'Binh Dinh Conference Center', lat: 13.7731162, lon: 109.2217008 },
  { name: 'Quy Nhon city centre', lat: 13.7549672, lon: 109.1767596 },
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
    return getDemoPreset('quantum-3').stops.map(({ weight: _weight, startTime: _startTime, endTime: _endTime, ...stop }) => stop)
  })

  /** Replace the complete delivery set atomically when a demo preset is selected. */
  const replaceStops = useCallback((nextStops: MapLocation[]) => {
    setStops(nextStops.map((stop) => ({ ...stop })))
  }, [])
  const [optimizedFleetRoutes, setOptimizedFleetRoutes] = useState<OptimizedFleetRoute[] | null>(null)
  const applyOptimizedFleetRoutes = useCallback((routes: OptimizedFleetRoute[]) => {
    setOptimizedFleetRoutes(routes.length > 0 ? routes : null)
  }, [])

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
          lat: loc.lat,
          lon: loc.lon,
        },
      ]
    })
  }, [])

  /** Keep planner labels aligned with the coordinates submitted to the API. */
  const renameStop = useCallback((id: string, name: string) => {
    const normalized = name.trim()
    if (!normalized) return
    setStops((previous) => previous.map((stop) => (
      stop.id === id ? { ...stop, name: normalized } : stop
    )))
  }, [])

  /** Apply a coordinate change before submitting a fresh backend optimization. */
  const updateStopLocation = useCallback((id: string, name: string, lat: number, lon: number) => {
    setStops((previous) => previous.map((stop) => (
      stop.id === id ? { ...stop, name, lat, lon } : stop
    )))
  }, [])

  /** Removing a planner row must also remove its coordinate from the request. */
  const removeStop = useCallback((id: string) => {
    setStops((previous) => previous.filter((stop) => stop.id !== id))
  }, [])

  // A newly edited stop invalidates any previously returned backend route.
  useEffect(() => {
    setOptimizedFleetRoutes(null)
  }, [stops])

  /** Use the verified backend fleet allocation when present; otherwise show a preview. */
  const baseRoutes = useMemo(() => {
    if (optimizedFleetRoutes) {
      const colors = ['#2563eb', '#16a34a', '#9333ea', '#ea580c', '#0891b2']
      return optimizedFleetRoutes.filter((route) => route.route.length > 2).map((route, index) => {
        const waypoints = route.route.map((node) => node === 0 ? DEPOT : stops[node - 1]).filter(Boolean) as MapLocation[]
        return {
          truckId: route.vehicle_id,
          truckName: route.vehicle_name,
          capacity: `${route.load} / ${route.capacity} kg`,
          color: colors[index % colors.length],
          waypoints,
          orderIds: route.route.filter((node) => node !== 0).map((node) => stops[node - 1]?.id).filter(Boolean),
        }
      })
    }
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
  }, [stops, optimizedFleetRoutes])

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
    renameStop,
    updateStopLocation,
    removeStop,
    replaceStops,
    applyOptimizedFleetRoutes,
  }
}
