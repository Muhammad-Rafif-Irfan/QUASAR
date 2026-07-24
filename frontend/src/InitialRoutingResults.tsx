import LiveMap from './LiveMap'
import type { MapLocation, TruckRoute } from './useRouteSimulation'

export type ComparisonRow = {
  algorithm: string
  distanceMeters: number
  executionTimeMs: number
  isValid: boolean
  approximationRatio: number | null
}

type InitialRoutingResultsProps = {
  onEditSetup: () => void
  onReRoute: () => void
  onStartOperational: () => void
  isOptimizing: boolean
  depot: MapLocation
  stops: MapLocation[]
  truckRoutes: TruckRoute[]
  totalDistance: number
  solverLabel: string
  comparisonRows: ComparisonRow[]
  optimizeError: string | null
}

function InitialRoutingResults({
  onEditSetup,
  onReRoute,
  onStartOperational,
  isOptimizing,
  depot,
  stops,
  truckRoutes,
  totalDistance,
  solverLabel,
  comparisonRows,
  optimizeError,
}: InitialRoutingResultsProps) {
  return (
    <section className="workspace results-workspace" aria-labelledby="routing-results-title">
      <div className="results-intro">
        <p className="eyebrow">Routing result</p>
        <h1 id="routing-results-title">Initial Routing Results</h1>
        <p className="subtitle">
          Review the route and algorithm comparison before starting delivery operations.
          Selected mode: <strong>{solverLabel}</strong>
        </p>
      </div>

      {optimizeError && <p className="optimize-warning" role="status">{optimizeError}</p>}

      {comparisonRows.length > 0 && (
        <section className="panel comparison-panel" aria-label="Algorithm comparison">
          <div className="panel-heading">
            <div>
              <p className="section-label">Benchmark</p>
              <h2>Algorithm comparison</h2>
            </div>
          </div>
          <div className="comparison-table" role="table">
            <div className="comparison-head" role="row">
              <span>Algorithm</span>
              <span>Distance</span>
              <span>Time</span>
              <span>Ratio vs OR-Tools</span>
              <span>Valid</span>
            </div>
            {comparisonRows.map((row) => (
              <div className="comparison-row" role="row" key={row.algorithm}>
                <strong>{row.algorithm}</strong>
                <span>{(row.distanceMeters / 1000).toFixed(2)} km</span>
                <span>{row.executionTimeMs.toFixed(0)} ms</span>
                <span>{row.approximationRatio == null ? '—' : row.approximationRatio.toFixed(3)}</span>
                <span className={row.isValid ? 'is-valid' : 'is-invalid'}>{row.isValid ? 'Yes' : 'No'}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel initial-route-map" aria-label="Initial route map">
        <div className="initial-route-map__live">
          <div className="route-stats-bar">
            <span className="route-stat">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
              {stops.length} stops
            </span>
            <span className="route-stat">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>
              {truckRoutes.length} trucks
            </span>
            <span className="route-stat">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
              {(totalDistance / 1000).toFixed(1)} km total
            </span>
            {truckRoutes.map((route) => (
              <span className="route-stat route-stat--legend" key={route.truckId}>
                <i style={{ background: route.color }} />
                {route.truckName}
              </span>
            ))}
          </div>
          <LiveMap
            depot={depot}
            stops={stops}
            truckRoutes={truckRoutes}
            isLive={false}
          />
        </div>
      </section>

      <div className="initial-results-actions">
        <div className="initial-results-actions__secondary">
          <button type="button" className="settings-button" onClick={onReRoute} disabled={isOptimizing}>
            {isOptimizing ? 'Re-routing...' : 'Re-Route'}
          </button>
          <button type="button" className="settings-button" onClick={onEditSetup}>Edit Setup</button>
        </div>
        <button type="button" className="route-action" onClick={onStartOperational}>Start Operational</button>
      </div>
    </section>
  )
}

export default InitialRoutingResults
