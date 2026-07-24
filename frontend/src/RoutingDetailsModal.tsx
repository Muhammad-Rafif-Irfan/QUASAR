import { CheckCircle2, X } from 'lucide-react'

type RoutingDetailsModalProps = {
  onClose: () => void
}

const routingDetails = [
  ['Algorithm', 'QAOA+ hybrid quantum-classical'],
  ['Backend', 'AerSimulator (qiskit 1.4)'],
  ['Core solver', 'FALCON r1.3'],
  ['QUBO variables', '64'],
  ['Iterations', '512'],
  ['Execution time', '2.4 s'],
  ['Vehicles assigned', '3 of 4'],
  ['Total stops', '8 delivery points'],
  ['Total demand', '257 kg'],
  ['Fleet capacity', '240 kg (split enabled)'],
  ['Route validity', 'Valid'],
  ['Objective value', '24.7 km total distance'],
  ['Split packages', 'N4 → Truck 2 (42 kg) + Truck 3 (20 kg)'],
  ['Overflow resolved', 'YES — all constraints satisfied'],
  ['Updated nodes', 'N3, N4, N5, N6, N7, N8'],
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
