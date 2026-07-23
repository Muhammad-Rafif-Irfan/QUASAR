import { CheckCircle2, Clock3, MapPin, Navigation, PackageCheck, Truck } from 'lucide-react'

const routingOverview = [
  { label: 'Baseline vehicles', value: '2' },
  { label: 'Updated vehicles', value: '2' },
  { label: 'Split package', value: '136 kg → 2' },
  { label: 'Overflow resolved', value: 'YES', status: 'resolved' },
]

const truckRoutes = [
  {
    name: 'Truck 1', capacity: '60 kg', stops: [
      { node: 'N1', weight: '12 kg', window: '09:00 – 10:00' },
      { node: 'N2', weight: '38 kg', window: '09:00 – 10:00' },
    ],
  },
  {
    name: 'Truck 2', capacity: '100 kg', stops: [
      { node: 'N3', weight: '24 kg', window: '10:00 – 11:00' },
      { node: 'N4', weight: '62 kg', window: '10:00 – 11:00' },
    ],
  },
]

// Screen 04 mirrors the approved live-routing wireframe with mock operational data.
function LiveDeliveryAndRouting({ onChangeAddress, onAddNewOrder, onEndDelivery, onViewLogDetails }: { onChangeAddress: () => void; onAddNewOrder: () => void; onEndDelivery: () => void; onViewLogDetails: () => void }) {
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
          <div className="live-map-placeholder" role="img" aria-label="Placeholder for the live delivery route map and moving vehicle positions">
            <Navigation size={20} />
            <p>Live route map</p>
            <small>Vehicle positions will update here.</small>
          </div>
        </article>

        <div className="live-truck-list">
          {truckRoutes.map((truck) => <article className="panel live-truck-card" key={truck.name}>
            <div className="live-truck-card__heading"><div><Truck size={16} /><h2>{truck.name}</h2></div><span>{truck.capacity}</span></div>
            <div className="live-truck-stops">
              {truck.stops.map((stop) => <div className="live-truck-stop" key={stop.node}><MapPin size={15} /><strong>{stop.node}</strong><span>{stop.weight}</span><time>{stop.window}</time></div>)}
            </div>
          </article>)}
          <span className="route-update-arrow" aria-hidden="true">↓</span>
        </div>
      </section>

      <section className="live-routing-footer">
        <div className="live-routing-controls">
          <div className="live-order-actions"><button type="button" className="settings-button" onClick={onAddNewOrder}><PackageCheck size={15} /> Add new order</button><button type="button" className="settings-button" onClick={onEndDelivery}>End Delivery</button></div>
          <div className="live-conditions"><Clock3 size={15} /><div><span>Live conditions</span><strong>All roads are clear, no obstacles reported.</strong></div><CheckCircle2 size={16} /></div>
        </div>
        <button type="button" className="settings-button" onClick={onViewLogDetails}>View log details</button>
      </section>
    </section>
  )
}

export default LiveDeliveryAndRouting
