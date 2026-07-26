import { ArrowLeft, CheckCircle2, Cpu, TriangleAlert } from 'lucide-react'
import type { QuantumJob } from './InitialRoutingResults'
import type { QuantumWarmStartEvidence, RunEvidence } from './App'

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
  quantumWarmStart: QuantumWarmStartEvidence | null
  onBack: () => void
  runEvidence: RunEvidence | null
}

const formatDistance = (meters: number) => `${(meters / 1000).toFixed(2)} km`

/** Displays only the latest completed API response; it has no preset data. */
export default function BenchmarkAnalysis({ rows, quantumJobs, quantumWarmStart, onBack, runEvidence }: BenchmarkAnalysisProps) {
  const bestDistance = rows.length ? Math.min(...rows.map((row) => row.distanceMeters)) : null
  const quantumEvidenceCount = quantumJobs.length + (quantumWarmStart?.jobIds.length || 0)
  const quantumRequested = runEvidence?.quantumRequested ?? false
  const quantumRows = rows.filter((row) => /qaoa|quantum/i.test(row.algorithm))
  const classicalRows = rows.filter((row) => !/qaoa|quantum/i.test(row.algorithm))
  const bestQuantumDistance = quantumRows.length ? Math.min(...quantumRows.map((row) => row.distanceMeters)) : null
  const bestClassicalDistance = classicalRows.length ? Math.min(...classicalRows.map((row) => row.distanceMeters)) : null
  const isMeasuredTie = bestQuantumDistance !== null && bestClassicalDistance !== null
    && Math.abs(bestQuantumDistance - bestClassicalDistance) < 0.5
  const quantumStatus = !quantumRequested
    ? `Not requested — ${runEvidence?.solverLabel || 'the latest run'} was classical.`
    : quantumEvidenceCount > 0
      ? `${quantumEvidenceCount} traceable job record(s) from the latest run.`
      : quantumWarmStart?.error || 'Quantum was requested, but no traceable job record was returned.'

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
            <article className="metric"><div className="metric-label"><Cpu size={17} /><span>Quantum evidence</span></div><strong>{quantumRequested ? quantumEvidenceCount : '—'}</strong><small className={quantumRequested && quantumEvidenceCount ? 'good' : 'neutral'}><b>{quantumRequested ? 'Requested' : 'Classical run'}</b> {quantumStatus}</small></article>
            <article className="metric"><div className="metric-label"><TriangleAlert size={17} /><span>Impact metrics</span></div><strong>Not claimed</strong><small className="warning"><b>Honest scope</b> no CO₂/SDG estimate without an approved emissions model</small></article>
          </section>
          <article className="panel planner-panel">
            <div className="planner-panel-heading"><div><p className="section-label">Latest completed run</p><h2>Solver comparison</h2></div></div>
            <p className="benchmark-provenance">
              Run <code>{runEvidence?.runId ?? 'unavailable'}</code> · {runEvidence?.stopsCount ?? 0} stops ·
              {' '}{runEvidence?.distanceMetric ?? 'distance basis unavailable for this historical run'}
            </p>
            <div className="planner-table benchmark-table" role="table" aria-label="Verified benchmark results">
              <div className="planner-table-head" role="row"><span>Algorithm</span><span>Distance</span><span>Time</span><span>Valid</span><span>Ratio</span></div>
              {rows.map((row) => <div className="planner-table-row" role="row" key={row.algorithm}><strong>{row.algorithm}</strong><span>{formatDistance(row.distanceMeters)}</span><span>{row.executionTimeMs.toFixed(1)} ms</span><span>{row.isValid ? 'Yes' : 'No'}</span><span>{row.approximationRatio === null ? '—' : row.approximationRatio.toFixed(3)}</span></div>)}
            </div>
          </article>
          {isMeasuredTie && (
            <article className="benchmark-disclosure" role="note">
              <TriangleAlert size={17} />
              <div><strong>No quantum distance advantage was measured in this run.</strong><p>This 3-stop instance is small enough for classical solvers to reach the same optimum. The reported QAOA simulator time is not a quantum speedup claim; use QAOA+ feasibility evidence on its bounded warm-start benchmark for the NISQ-specific comparison.</p></div>
            </article>
          )}
        </>
      )}
    </section>
  )
}
