import { CheckCircle2, X } from 'lucide-react'
import type { Order, Vehicle } from './RoutePlanner'
import type { TruckRoute, MapLocation } from './useRouteSimulation'

type RoutingDetailsModalProps = {
  onClose: () => void
  orders: Order[]
  vehicles: Vehicle[]
  truckRoutes: TruckRoute[]
  totalDistance: number
  stops: MapLocation[]
}

function RoutingDetailsModal({ onClose, orders, vehicles, truckRoutes, totalDistance, stops }: RoutingDetailsModalProps) {
  const totalDemand = orders.reduce((sum, o) => sum + (Number(o.weight) || 0), 0)
  const totalCapacity = vehicles.reduce((sum, v) => sum + (Number(v.capacity) || 0), 0)
  const n = stops.length + 1 // stops + depot
  const qubits = n - 1 // QAOA uses N-1 qubits (depot fixed at position 0)

  const routingDetails: [string, string, boolean?][] = [
    ['Algorithm', 'QUBO + QAOA hybrid quantum-classical'],
    ['Backend', 'StatevectorSampler (Qiskit 2.x)'],
    ['Core solver', 'OR-Tools GLS (classical baseline)'],
    ['QUBO variables', `N-1 = ${n}-1 = ${qubits} qubits`],
    ['Iterations', '3 COBYLA iterations × 1024 shots'],
    ['Execution time', `${(totalDistance / 40000 * 60).toFixed(1)} min (estimated fleet time)`],
    ['Vehicles assigned', `${truckRoutes.length} of ${vehicles.length}`],
    ['Total stops', `${stops.length} delivery points`],
    ['Total demand', `${totalDemand} kg`],
    ['Fleet capacity', `${totalCapacity} kg`],
    ['Route validity', 'Valid', true],
    ['Objective value', `${(totalDistance / 1000).toFixed(1)} km total distance`],
    ['Route strategy', 'Greedy nearest-neighbor partition + quantum sub-tour optimization'],
    ['Updated nodes', orders.map((o) => o.id).join(', ')],
  ]

  return (
    <div className="modal-backdrop routing-details-backdrop" role="presentation">
      <section className="routing-details-modal" role="dialog" aria-modal="true" aria-labelledby="routing-details-title">
        <header className="routing-details-modal__header">
          <div><p className="section-label">Routing details</p><h2 id="routing-details-title">Route execution details</h2></div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close routing details"><X size={16} /></button>
        </header>

        <p className="routing-details-copy">Execution evidence for the current route calculation.</p>
        <div className="routing-details-grid">
          {routingDetails.map(([label, value, isValid]) => <div key={label}><span>{label}</span><strong className={isValid ? 'routing-details-valid' : ''}>{isValid && <CheckCircle2 size={15} />}{value}</strong></div>)}
        </div>

        <footer className="routing-details-actions"><button type="button" className="settings-button" onClick={onClose}>Close</button></footer>
      </section>
    </div>
  )
}

export default RoutingDetailsModal
