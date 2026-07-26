import { useEffect, useRef, useState, useCallback } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Popup, useMapEvents, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { MapLocation, TruckRoute } from './useRouteSimulation'

// ─── Custom marker icons ──────────────────────────────────────────────

const DEPOT_ICON = L.divIcon({
  className: 'custom-depot-marker',
  html: `<div class="depot-pin"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg></div>`,
  iconSize: [36, 36],
  iconAnchor: [18, 36],
  popupAnchor: [0, -36],
})

const STOP_ICON = L.divIcon({
  className: 'custom-stop-marker',
  html: `<div class="stop-pin"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg></div>`,
  iconSize: [30, 30],
  iconAnchor: [15, 30],
  popupAnchor: [0, -30],
})

const NEW_STOP_ICON = L.divIcon({
  className: 'custom-new-stop-marker',
  html: `<div class="new-stop-pin"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>`,
  iconSize: [30, 30],
  iconAnchor: [15, 30],
  popupAnchor: [0, -30],
})

function createTruckIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: 'custom-truck-marker',
    html: `<div class="truck-pin" style="--truck-color: ${color}"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg></div>`,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  })
}

// ─── Interpolation helpers ────────────────────────────────────────────

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

type LatLon = [number, number]

function interpolateAlongPath(waypoints: LatLon[], progress: number): LatLon {
  if (waypoints.length < 2) return waypoints[0] || [0, 0]

  // Calculate total path length
  const segmentLengths: number[] = []
  let totalLength = 0
  for (let i = 0; i < waypoints.length - 1; i++) {
    const dx = waypoints[i + 1][0] - waypoints[i][0]
    const dy = waypoints[i + 1][1] - waypoints[i][1]
    const len = Math.sqrt(dx * dx + dy * dy)
    segmentLengths.push(len)
    totalLength += len
  }

  const targetDist = progress * totalLength
  let accumulated = 0

  for (let i = 0; i < segmentLengths.length; i++) {
    if (accumulated + segmentLengths[i] >= targetDist) {
      const segProgress = segmentLengths[i] > 0 ? (targetDist - accumulated) / segmentLengths[i] : 0
      return [
        lerp(waypoints[i][0], waypoints[i + 1][0], segProgress),
        lerp(waypoints[i][1], waypoints[i + 1][1], segProgress),
      ]
    }
    accumulated += segmentLengths[i]
  }

  return waypoints[waypoints.length - 1]
}

// ─── Map click handler ────────────────────────────────────────────────

function ClickHandler({ onMapClick }: { onMapClick?: (latlng: { lat: number; lon: number }) => void }) {
  useMapEvents({
    click(e) {
      onMapClick?.({ lat: e.latlng.lat, lon: e.latlng.lng })
    },
  })
  return null
}

// ─── Auto-fit bounds when stops change ────────────────────────────────

function AutoFitBounds({ depot, stops }: { depot: MapLocation; stops: MapLocation[] }) {
  const map = useMap()
  const initialFitDone = useRef(false)

  useEffect(() => {
    if (!initialFitDone.current) {
      const allPoints: LatLon[] = [
        [depot.lat, depot.lon],
        ...stops.map((s) => [s.lat, s.lon] as LatLon),
      ]
      if (allPoints.length > 1) {
        const bounds = L.latLngBounds(allPoints.map(([lat, lon]) => L.latLng(lat, lon)))
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 })
      }
      initialFitDone.current = true
    }
  }, [map, depot, stops])

  return null
}

// ─── Animated truck markers ───────────────────────────────────────────

function AnimatedTrucks({ routes, isLive }: { routes: TruckRoute[]; isLive: boolean }) {
  const map = useMap()
  const markersRef = useRef<Map<string, L.Marker>>(new Map())
  const animRef = useRef<number>(0)
  const startTimeRef = useRef<number>(0)

  // Duration for one full route traversal (ms)
  const CYCLE_DURATION = 20000

  useEffect(() => {
    if (!isLive) {
      // Remove truck markers when not live
      markersRef.current.forEach((marker) => marker.remove())
      markersRef.current.clear()
      if (animRef.current) cancelAnimationFrame(animRef.current)
      return
    }

    // Create/update truck markers
    routes.forEach((route) => {
      if (!markersRef.current.has(route.truckId)) {
        const icon = createTruckIcon(route.color)
        const startPos = route.waypoints[0]
        const marker = L.marker([startPos.lat, startPos.lon], { icon, zIndexOffset: 1000 })
          .bindTooltip(route.truckName, { permanent: false, direction: 'top', offset: [0, -20] })
          .addTo(map)
        markersRef.current.set(route.truckId, marker)
      }
    })

    // Remove markers for routes that no longer exist
    markersRef.current.forEach((marker, truckId) => {
      if (!routes.find((r) => r.truckId === truckId)) {
        marker.remove()
        markersRef.current.delete(truckId)
      }
    })

    startTimeRef.current = performance.now()

    function animate(timestamp: number) {
      const elapsed = timestamp - startTimeRef.current
      const progress = (elapsed % CYCLE_DURATION) / CYCLE_DURATION

      routes.forEach((route) => {
        const marker = markersRef.current.get(route.truckId)
        if (!marker) return

        // Use detailed road geometry for smooth road-following animation
        const path: LatLon[] = route.roadGeometry.length > 2
          ? route.roadGeometry
          : route.waypoints.map((wp) => [wp.lat, wp.lon] as LatLon)
        const pos = interpolateAlongPath(path, progress)
        marker.setLatLng(pos)
      })

      animRef.current = requestAnimationFrame(animate)
    }

    animRef.current = requestAnimationFrame(animate)

    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current)
    }
  }, [isLive, routes, map])

  return null
}

// ─── Main LiveMap component ───────────────────────────────────────────

type LiveMapProps = {
  depot: MapLocation
  stops: MapLocation[]
  truckRoutes: TruckRoute[]
  isLive: boolean
  onMapClick?: (latlng: { lat: number; lon: number }) => void
  /** Stops that were recently added — shown with a different icon */
  newStopIds?: Set<string>
  className?: string
}

export default function LiveMap({
  depot,
  stops,
  truckRoutes,
  isLive,
  onMapClick,
  newStopIds,
  className = '',
}: LiveMapProps) {
  const [recalculating, setRecalculating] = useState(false)
  const [addStopMode, setAddStopMode] = useState(false)
  const prevStopsCount = useRef(stops.length)
  const hasRoadGeometry = truckRoutes.length > 0 && truckRoutes.every((route) => route.roadGeometrySource === 'osrm')

  // Flash "recalculating" animation when stops change
  useEffect(() => {
    if (stops.length !== prevStopsCount.current && isLive) {
      setRecalculating(true)
      const timer = setTimeout(() => setRecalculating(false), 1200)
      prevStopsCount.current = stops.length
      return () => clearTimeout(timer)
    }
    prevStopsCount.current = stops.length
  }, [stops.length, isLive])

  const handleMapClick = useCallback(
    (latlng: { lat: number; lon: number }) => {
      onMapClick?.(latlng)
      setAddStopMode(false)
    },
    [onMapClick],
  )

  return (
    <div className={`live-map-container ${recalculating ? 'route-recalculating' : ''} ${className}`}>
      {recalculating && (
        <div className="recalc-badge" role="status" aria-live="polite">
          <span className="recalc-spinner" />
          Recalculating routes...
        </div>
      )}
      {onMapClick && (
        <div className="map-interaction-controls">
          <button type="button" className={addStopMode ? 'is-active' : ''} onClick={() => setAddStopMode((enabled) => !enabled)} aria-pressed={addStopMode}>
            {addStopMode ? 'Click map to add stop' : 'Add stop on map'}
          </button>
          <span>{addStopMode ? 'One click adds a stop, then returns to pan.' : 'Drag to pan · scroll to zoom'}</span>
        </div>
      )}
      <MapContainer
        center={[depot.lat, depot.lon]}
        zoom={13}
        scrollWheelZoom={true}
        style={{ height: '100%', width: '100%', borderRadius: '8px' }}
        zoomControl={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        <AutoFitBounds depot={depot} stops={stops} />

        {onMapClick && addStopMode && <ClickHandler onMapClick={handleMapClick} />}

        {/* Depot marker */}
        <Marker position={[depot.lat, depot.lon]} icon={DEPOT_ICON}>
          <Popup>
            <strong>{depot.name}</strong>
            <br />
            Depot (start/end)
          </Popup>
        </Marker>

        {/* Delivery stop markers */}
        {stops.map((stop) => (
          <Marker
            key={stop.id}
            position={[stop.lat, stop.lon]}
            icon={newStopIds?.has(stop.id) ? NEW_STOP_ICON : STOP_ICON}
          >
            <Popup>
              <strong>{stop.id}</strong> — {stop.name}
              {stop.weight && (
                <>
                  <br />
                  Weight: {stop.weight} kg
                </>
              )}
            </Popup>
          </Marker>
        ))}

        {/* Route polylines — use OSRM road geometry for realistic road-following paths */}
        {truckRoutes.map((route) => (
          <Polyline
            key={route.truckId}
            positions={
              route.roadGeometry.length > 2
                ? route.roadGeometry
                : route.waypoints.map((wp) => [wp.lat, wp.lon] as [number, number])
            }
            pathOptions={{
              color: route.color,
              weight: 4,
              opacity: 0.85,
              dashArray: recalculating ? '10 6' : undefined,
            }}
          >
            <Popup>
              <strong>{route.truckName}</strong>
              <br />
              Capacity: {route.capacity}
              <br />
              Stops: {route.orderIds.join(', ')}
              <br />
              Distance: {(route.roadDistance / 1000).toFixed(1)} km
            </Popup>
          </Polyline>
        ))}

        {/* Animated trucks */}
        <AnimatedTrucks routes={truckRoutes} isLive={isLive} />
      </MapContainer>

      {truckRoutes.length > 0 && (
        <div className={`map-route-source ${hasRoadGeometry ? 'is-road' : 'is-fallback'}`}>
          {hasRoadGeometry ? 'OSRM road geometry' : 'Straight-line display fallback — OSRM unavailable'}
        </div>
      )}
    </div>
  )
}
