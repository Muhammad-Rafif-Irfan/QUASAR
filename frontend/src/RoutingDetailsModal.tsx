import { CheckCircle2, X } from 'lucide-react'

type RoutingDetailsModalProps = {
  onClose: () => void
}

const routingDetails = [
  ['Algorithm', 'Hybrid classical-quantum routing'],
  ['Backend', 'AerSimulator'],
  ['Core', 'FALCON'],
  ['Iterations', '256'],
  ['Execution time', '1.2 s'],
  ['Route validity', 'Valid'],
  ['Objective value', '28.4 km total distance'],
  ['Updated nodes', 'N3, N4'],
]

// Screen 05 is opened from the live-routing log button and uses mock execution evidence.
function RoutingDetailsModal({ onClose }: RoutingDetailsModalProps) {
  return (
    <div className="modal-backdrop routing-details-backdrop" role="presentation">
      <section className="routing-details-modal" role="dialog" aria-modal="true" aria-labelledby="routing-details-title">
        <header className="routing-details-modal__header">
          <div><p className="section-label">Routing details</p><h2 id="routing-details-title">Route execution details</h2></div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close routing details"><X size={16} /></button>
        </header>

        <p className="routing-details-copy">Execution evidence for the current route calculation.</p>
        <div className="routing-details-grid">
          {routingDetails.map(([label, value]) => <div key={label}><span>{label}</span><strong className={label === 'Route validity' ? 'routing-details-valid' : ''}>{label === 'Route validity' && <CheckCircle2 size={15} />}{value}</strong></div>)}
        </div>

        <footer className="routing-details-actions"><button type="button" className="settings-button" onClick={onClose}>Close</button></footer>
      </section>
    </div>
  )
}

export default RoutingDetailsModal
