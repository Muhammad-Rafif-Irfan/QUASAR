import { CheckCircle2, Clock3, MapPin, PackageCheck, Truck } from 'lucide-react'
import LiveMap from './LiveMap'
import type { MapLocation, TruckRoute } from './useRouteSimulation'

type LiveDeliveryProps = {
  onChangeAddress: () => void
  onAddNewOrder: () => void
  onEndDelivery: () => void
  onViewLogDetails: () => void
  depot: MapLocation
  stops: MapLocation[]
  truckRoutes: TruckRoute[]
  totalDistance: number
  onMapClick: (latlng: { lat: number; lon: number }) => void
  newStopIds: Set<string>
}

// Screen 04 mirrors the approved live-routing wireframe with mock operational data.
function LiveDeliveryAndRouting({
  onChangeAddress,
  onAddNewOrder,
  onEndDelivery,
  onViewLogDetails,
  depot,
  stops,
  truckRoutes,
  totalDistance,
  onMapClick,
  newStopIds,
}: LiveDeliveryProps) {
  const routingOverview = [
    { label: 'Active vehicles', value: String(truckRoutes.length) },
    { label: 'Delivery stops', value: String(stops.length) },
    { label: 'Total distance', value: `${(totalDistance / 1000).toFixed(1)} km` },
    { label: 'Route status', value: 'LIVE', status: 'resolved' },
  ]

  return (
    <section className="workspace live-routing-workspace" aria-labelledby="live-delivery-title">
      <div className="live-routing-intro">
        <div>
          <p className="eyebrow">Routing overview</p>
          <h1 id="live-delivery-title">Live Delivery and Routing</h1>
          <p className="subtitle">Monitor the active route and current vehicle assignments.</p>
        </div>
        <button type="button" className="settings-button" onClick={onChangeAddress}>Change Address</button>
      </div>

      <section className="live-routing-metrics" aria-label="Live routing summary">
        {routingOverview.map((metric) => <article className="metric" key={metric.label}>
          <span className="metric-label">{metric.label}</span>
          <strong className={metric.status === 'resolved' ? 'live-routing-success' : ''}>{metric.value}</strong>
        </article>)}
      </section>

      <section className="live-routing-main">
        <article className="panel live-map-panel">
          <div className="live-map-panel__head"><span className="live-map-status"><i /> LIVE</span></div>
          <LiveMap
            depot={depot}
            stops={stops}
            truckRoutes={truckRoutes}
            isLive={true}
            onMapClick={onMapClick}
            newStopIds={newStopIds}
            className="live-map-active"
          />
        </article>

        <div className="live-truck-list">
          {truckRoutes.map((route) => (
            <article className="panel live-truck-card" key={route.truckId}>
              <div className="live-truck-card__heading">
                <div>
                  <Truck size={16} />
                  <h2>{route.truckName}</h2>
                  <span className="truck-color-dot" style={{ background: route.color }} />
                </div>
                <span>{route.capacity}</span>
              </div>
              <div className="live-truck-stops">
                {route.waypoints
                  .filter((wp) => wp.id !== 'depot')
                  .map((wp) => (
                    <div className={`live-truck-stop ${newStopIds.has(wp.id) ? 'live-truck-stop--new' : ''}`} key={wp.id}>
                      <MapPin size={15} />
                      <strong>{wp.id}</strong>
                      <span>{wp.name}</span>
                      <span className="live-truck-stop__coords">
                        {wp.lat.toFixed(4)}, {wp.lon.toFixed(4)}
                      </span>
                    </div>
                  ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="live-routing-footer">
        <div className="live-routing-controls">
          <div className="live-order-actions">
            <button type="button" className="settings-button" onClick={onAddNewOrder}>
              <PackageCheck size={15} /> Add new order
            </button>
            <button type="button" className="settings-button" onClick={onEndDelivery}>End Delivery</button>
          </div>
          <div className="live-conditions">
            <Clock3 size={15} />
            <div>
              <span>Live conditions</span>
              <strong>All roads are clear, no obstacles reported.</strong>
            </div>
            <CheckCircle2 size={16} />
          </div>
        </div>
        <button type="button" className="settings-button" onClick={onViewLogDetails}>View log details</button>
      </section>
    </section>
  )
}

export default LiveDeliveryAndRouting
