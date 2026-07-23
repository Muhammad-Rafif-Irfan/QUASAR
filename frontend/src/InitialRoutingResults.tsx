type InitialRoutingResultsProps = {
  onEditSetup: () => void
  onReRoute: () => void
  onStartOperational: () => void
  isOptimizing: boolean
}

// Screen 03 follows the approved wireframe: one route-result canvas and its three actions.
function InitialRoutingResults({ onEditSetup, onReRoute, onStartOperational, isOptimizing }: InitialRoutingResultsProps) {
  return (
    <section className="workspace results-workspace" aria-labelledby="routing-results-title">
      <div className="results-intro">
        <p className="eyebrow">Routing result</p>
        <h1 id="routing-results-title">Initial Routing Results</h1>
        <p className="subtitle">Review the initial route before starting delivery operations.</p>
      </div>

      <section className="panel initial-route-map" aria-label="Initial route map">
        <div className="initial-route-map__placeholder" role="img" aria-label="Placeholder for the optimized route map">
          <p>Initial route map will appear here.</p>
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
