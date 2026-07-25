import { ArrowLeft, CheckCircle2, Cpu, TriangleAlert } from 'lucide-react'
import type { QuantumJob } from './InitialRoutingResults'

export type BenchmarkRow = {
  algorithm: string
  distanceMeters: number
  executionTimeMs: number
  isValid: boolean
  approximationRatio: number | null
}

type BenchmarkAnalysisProps = {
  rows: BenchmarkRow[]
  quantumJobs: QuantumJob[]
  onBack: () => void
}

const formatDistance = (meters: number) => `${(meters / 1000).toFixed(2)} km`

/** Displays only the latest completed API response; it has no preset data. */
export default function BenchmarkAnalysis({ rows, quantumJobs, onBack }: BenchmarkAnalysisProps) {
  const bestDistance = rows.length ? Math.min(...rows.map((row) => row.distanceMeters)) : null

  return (
    <section className="workspace" aria-labelledby="benchmark-title">
      <div className="page-intro">
        <div>
          <p className="eyebrow">Verified API run</p>
          <h1 id="benchmark-title">Benchmark Analysis</h1>
          <p className="subtitle">Only results returned by the current QUASAR API run are displayed.</p>
        </div>
        <div className="page-actions"><button type="button" className="settings-button" onClick={onBack}><ArrowLeft size={16} /> Back</button></div>
      </div>

      {rows.length === 0 ? (
        <article className="panel empty-state" role="status"><TriangleAlert size={20} /><div><h2>No completed benchmark yet</h2><p>Run an optimization first. This screen does not show preset or mock results.</p></div></article>
      ) : (
        <>
          <section className="metric-grid" aria-label="Latest benchmark summary">
            <article className="metric"><div className="metric-label"><CheckCircle2 size={17} /><span>Verified results</span></div><strong>{rows.length}</strong><small className="good"><b>API returned</b> solver rows shown below</small></article>
            <article className="metric"><div className="metric-label"><Cpu size={17} /><span>Best route</span></div><strong>{bestDistance ? formatDistance(bestDistance) : '—'}</strong><small className="neutral"><b>Current run</b> smallest returned distance</small></article>
            <article className="metric"><div className="metric-label"><Cpu size={17} /><span>Quantum jobs</span></div><strong>{quantumJobs.length}</strong><small className="neutral"><b>Traceable</b> job records from the API</small></article>
            <article className="metric"><div className="metric-label"><TriangleAlert size={17} /><span>Impact metrics</span></div><strong>Not claimed</strong><small className="warning"><b>Honest scope</b> no CO₂/SDG estimate without an approved emissions model</small></article>
          </section>
          <article className="panel planner-panel">
            <div className="planner-panel-heading"><div><p className="section-label">Latest completed run</p><h2>Solver comparison</h2></div></div>
            <div className="planner-table" role="table" aria-label="Verified benchmark results">
              <div className="planner-table-head" role="row"><span>Algorithm</span><span>Distance</span><span>Time</span><span>Valid</span><span>Ratio</span></div>
              {rows.map((row) => <div className="planner-table-row" role="row" key={row.algorithm}><strong>{row.algorithm}</strong><span>{formatDistance(row.distanceMeters)}</span><span>{row.executionTimeMs.toFixed(1)} ms</span><span>{row.isValid ? 'Yes' : 'No'}</span><span>{row.approximationRatio === null ? '—' : row.approximationRatio.toFixed(3)}</span></div>)}
            </div>
          </article>
        </>
      )}
    </section>
  )
}
