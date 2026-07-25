import { CheckCircle2, X } from 'lucide-react'
import type { ComparisonRow } from './InitialRoutingResults'
import type { RunEvidence } from './App'

type RoutingDetailsModalProps = {
  onClose: () => void
  solverLabel: string
  comparisonRows: ComparisonRow[]
  runEvidence: RunEvidence | null
}

function RoutingDetailsModal({ onClose, solverLabel, comparisonRows, runEvidence }: RoutingDetailsModalProps) {
  const best = [...comparisonRows].sort((a, b) => a.distanceMeters - b.distanceMeters)[0]
  const details: Array<[string, string]> = [
    ['Selected mode', solverLabel],
    ['Best algorithm', best?.algorithm || '—'],
    ['Best distance', best ? `${(best.distanceMeters / 1000).toFixed(2)} km` : '—'],
    ['Solvers compared', String(comparisonRows.length || 0)],
    ['Route validity', best?.isValid ? 'Valid' : 'Pending'],
  ]

  return (
    <div className="modal-backdrop routing-details-backdrop" role="presentation">
      <section className="routing-details-modal" role="dialog" aria-modal="true" aria-labelledby="routing-details-title">
        <header className="routing-details-modal__header">
          <div>
            <p className="section-label">Routing details</p>
            <h2 id="routing-details-title">Route execution details</h2>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close routing details"><X size={16} /></button>
        </header>

        <p className="routing-details-copy">Execution evidence for the latest algorithm comparison.</p>
        <p className="benchmark-provenance">Run <code>{runEvidence?.runId ?? 'unavailable'}</code> · {runEvidence?.distanceMetric ?? 'distance basis unavailable'}</p>
        <div className="routing-details-grid">
          {details.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong className={label === 'Route validity' ? 'routing-details-valid' : ''}>
                {label === 'Route validity' && <CheckCircle2 size={15} />}
                {value}
              </strong>
            </div>
          ))}
        </div>

        {comparisonRows.length > 0 && (
          <div className="comparison-table routing-details-comparison" role="table">
            <div className="comparison-head" role="row">
              <span>Algorithm</span>
              <span>Distance</span>
              <span>Time</span>
            </div>
            {comparisonRows.map((row) => (
              <div className="comparison-row" role="row" key={row.algorithm}>
                <strong>{row.algorithm}</strong>
                <span>{(row.distanceMeters / 1000).toFixed(2)} km</span>
                <span>{row.executionTimeMs.toFixed(0)} ms</span>
              </div>
            ))}
          </div>
        )}

        <footer className="routing-details-actions">
          <button type="button" className="settings-button" onClick={onClose}>Close</button>
        </footer>
      </section>
    </div>
  )
}

export default RoutingDetailsModal
