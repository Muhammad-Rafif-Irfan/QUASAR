import { useState, useCallback, useEffect, type FormEvent } from 'react'
import { BarChart3, Map, Navigation, PackageCheck, Route, Settings, TriangleAlert, Truck, type LucideIcon } from 'lucide-react'
import BenchmarkAnalysis from './BenchmarkAnalysis'
import InitialRoutingResults, { type QuantumJob } from './InitialRoutingResults'
import LiveDeliveryAndRouting from './LiveDeliveryAndRouting'
import RoutePlanner, { WorkflowSidebar, initialOrders, initialVehicles, type Order, type Vehicle } from './RoutePlanner'
import RoutingDetailsModal from './RoutingDetailsModal'
import { AddNewOrderModal, ChangeAddressModal, type NewOrderDraft } from './SupportingStates'
import { getDemoPreset, useRouteSimulation, type DemoPresetId, type OptimizedFleetRoute } from './useRouteSimulation'
import {
  DEFAULT_SOLVER_ID,
  MAX_CLASSICAL_DEMO_STOPS,
  MAX_QAOA_STOPS,
  MAX_QAOA_PLUS_WARM_START_STOPS,
  SOLVER_OPTIONS,
  getSolverOption,
} from './solvers'

type Screen = 'overview' | 'planner' | 'results' | 'live' | 'benchmark'
type Theme = 'light' | 'dark'
type FontScale = 'standard' | 'large' | 'xlarge'
type QuantumConnection = {
  status: string
  env_file_present: boolean
  token_configured: boolean
  token_variable?: string | null
  backend_name?: string | null
  backend_qubits?: number | null
  message: string
}

type QudoraConnection = {
  status: string
  env_file_present: boolean
  token_configured: boolean
  worker_configured: boolean
  message: string
  backends: Array<{ name?: string | null }>
}

type Metric = {
  label: string
  value: string
  unit?: string
  detail: string
  emphasis: string
  Icon: LucideIcon
  status: 'neutral' | 'good' | 'warning' | 'alert'
}

type ComparisonRow = {
  algorithm: string
  distanceMeters: number
  executionTimeMs: number
  isValid: boolean
  approximationRatio: number | null
}

export type RunEvidence = {
  runId: string
  stopsCount: number
  distanceMetric: string | null
  solverLabel: string
  quantumRequested: boolean
  vehiclesUsed: number
}

export type QuantumWarmStartEvidence = {
  algorithm: string
  executor: string
  backend: string | null
  jobIds: string[]
  valid: boolean
  accepted: boolean
  acceptanceReason: string | null
  initialCost: number
  finalCost: number
  improvementPercent: number
  feasibleSampleRate: number | null
  shots: number | null
  nQubits: number
  circuitDepth: number | null
  error?: string
}

type OptimizationProgress = {
  percent: number
  stage: string
  detail: string
}

const haversineMeters = (left: { lat: number; lon: number }, right: { lat: number; lon: number }) => {
  const radians = (value: number) => value * Math.PI / 180
  const dLat = radians(right.lat - left.lat)
  const dLon = radians(right.lon - left.lon)
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(radians(left.lat)) * Math.cos(radians(right.lat)) * Math.sin(dLon / 2) ** 2
  return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

type SettingsModalProps = {
  solverId: string
  onSolverChange: (id: string) => void
  theme: Theme
  onThemeChange: (theme: Theme) => void
  fontScale: FontScale
  onFontScaleChange: (scale: FontScale) => void
  quantumConnection: QuantumConnection | null
  isCheckingQuantumConnection: boolean
  onCheckQuantumConnection: () => void
  qudoraConnection: QudoraConnection | null
  isCheckingQudoraConnection: boolean
  onCheckQudoraConnection: () => void
  onClearAppData: () => void
  isClearingAppData: boolean
  onSave: (event: FormEvent<HTMLFormElement>) => void
  onClose: () => void
}

function ApplicationHeader({ onOpenSettings, onGoHome }: { onOpenSettings: () => void; onGoHome: () => void }) {
  const currentDate = new Intl.DateTimeFormat('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  }).format(new Date())

  return (
    <header className="topbar">
      <button type="button" className="brand" onClick={onGoHome} aria-label="Go to QUASAR overview">
        <svg width="20" height="20" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="15" cy="15" r="9" stroke="currentColor" strokeWidth="2.2" />
          <path d="M21.5 21.5L27 27" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
          <path d="M10.5 12.5C13.2 13.4 15.5 15.6 18.5 18.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <circle cx="10" cy="12" r="1.6" fill="currentColor" />
          <circle cx="19" cy="19" r="1.6" fill="currentColor" />
        </svg>
        <span>QUASAR</span>
      </button>
      <div className="topbar-meta">
        <span className="system-status">Connected</span>
        <span>{currentDate}</span>
        <button type="button" className="settings-button header-settings" onClick={onOpenSettings}>
          <Settings size={15} /> Settings
        </button>
      </div>
    </header>
  )
}

function SettingsModal({ solverId, onSolverChange, theme, onThemeChange, fontScale, onFontScaleChange, quantumConnection, isCheckingQuantumConnection, onCheckQuantumConnection, qudoraConnection, isCheckingQudoraConnection, onCheckQudoraConnection, onClearAppData, isClearingAppData, onSave, onClose }: SettingsModalProps) {
  const selected = getSolverOption(solverId)
  return (
    <div className="modal-backdrop" role="presentation">
      <form className="settings-modal" aria-modal="true" aria-labelledby="settings-title" onSubmit={onSave}>
        <div className="settings-modal__heading">
          <div>
            <p className="section-label">Settings</p>
            <h2 id="settings-title">Operational configuration</h2>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close settings">&times;</button>
        </div>
        <p className="settings-copy">Only the algorithm selector changes this UI. Quantum execution policy is enforced by the API, not by decorative local fields.</p>
        <div className="settings-fields">
          <label>
            Algorithm
            <select
              name="solver"
              value={solverId}
              onChange={(event) => onSolverChange(event.target.value)}
              aria-label="Optimization algorithm"
            >
              <optgroup label="Classical">
                {SOLVER_OPTIONS.filter((option) => option.kind === 'classical').map((option) => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                ))}
              </optgroup>
              <optgroup label="Quantum">
                {SOLVER_OPTIONS.filter((option) => option.kind === 'quantum').map((option) => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                ))}
              </optgroup>
              <optgroup label="Comparison">
                {SOLVER_OPTIONS.filter((option) => option.kind === 'hybrid').map((option) => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                ))}
              </optgroup>
            </select>
          </label>
          <fieldset className="execution-policy-settings">
            <legend>Execution policy</legend>
            <p><strong>Fleet routing:</strong> OR-Tools CVRP with capacity constraints; QAOA is not applied.</p>
            <p><strong>Quantum scope:</strong> one vehicle and at most 3 stops. The API reads its QAOA iteration budget from <code>.env</code>.</p>
            <p><strong>Backend:</strong> IBM QPU only when the connection check finds an operational backend; otherwise bounded QAOA uses a local simulator.</p>
          </fieldset>
          <fieldset className="accessibility-settings">
            <legend>Accessibility</legend>
            <label>
              Color mode
              <select value={theme} onChange={(event) => onThemeChange(event.target.value as Theme)} aria-label="Color mode">
                <option value="light">Light mode</option>
                <option value="dark">Dark mode</option>
              </select>
            </label>
            <label>
              Text size
              <select value={fontScale} onChange={(event) => onFontScaleChange(event.target.value as FontScale)} aria-label="Text size">
                <option value="standard">Standard</option>
                <option value="large">Large</option>
                <option value="xlarge">Extra large</option>
              </select>
            </label>
          </fieldset>
          <fieldset className="quantum-connection-settings">
            <legend>IBM Quantum connection</legend>
            <p>Checks whether this API process received a token and performs a read-only backend lookup. No circuit is submitted.</p>
            <button type="button" className="settings-button" onClick={onCheckQuantumConnection} disabled={isCheckingQuantumConnection}>
              {isCheckingQuantumConnection ? 'Checking IBM Quantum…' : 'Check IBM Quantum connection'}
            </button>
            {quantumConnection && (
              <p className={`quantum-connection-status status-${quantumConnection.status}`} role="status">
                <strong>{quantumConnection.status.replaceAll('_', ' ')}</strong> — {quantumConnection.message}
                {quantumConnection.backend_name && ` Backend: ${quantumConnection.backend_name} (${quantumConnection.backend_qubits} qubits).`}
                {!quantumConnection.token_configured && ` .env visible: ${quantumConnection.env_file_present ? 'yes' : 'no'}.`}
              </p>
            )}
          </fieldset>
          <fieldset className="quantum-connection-settings">
            <legend>QUDORA Cloud connection</legend>
            <p>Checks the isolated QUDORA worker, token, and cloud backend discovery. No circuit is submitted. Qamelion and QVLS-Q1 are simulators/emulators, not hardware runs.</p>
            <button type="button" className="settings-button" onClick={onCheckQudoraConnection} disabled={isCheckingQudoraConnection}>
              {isCheckingQudoraConnection ? 'Checking QUDORA Cloud…' : 'Check QUDORA Cloud connection'}
            </button>
            {qudoraConnection && (
              <p className={`quantum-connection-status status-${qudoraConnection.status}`} role="status">
                <strong>{qudoraConnection.status.replaceAll('_', ' ')}</strong> — {qudoraConnection.message}
                {qudoraConnection.backends.length > 0 && ` Backends: ${qudoraConnection.backends.map((backend) => backend.name).filter(Boolean).join(', ')}.`}
                {!qudoraConnection.token_configured && ` .env visible: ${qudoraConnection.env_file_present ? 'yes' : 'no'}.`}
              </p>
            )}
          </fieldset>
          <fieldset className="danger-zone-settings">
            <legend>Danger zone</legend>
            <p>Permanently deletes every saved benchmark run, result, and quantum job trace from this app. This cannot be undone.</p>
            <button type="button" className="danger-button" onClick={onClearAppData} disabled={isClearingAppData}>
              {isClearingAppData ? 'Clearing app data…' : 'Clear all app data'}
            </button>
          </fieldset>
        </div>
        <p className="settings-solver-hint">{selected.description}</p>
        <div className="settings-actions">
          <button type="submit" className="save-settings">Save Settings</button>
          <button type="button" className="cancel-settings" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  )
}

function OptimizationLoading({ solverLabel, progress }: { solverLabel: string; progress: OptimizationProgress }) {
  return (
    <div className="optimization-overlay" role="status" aria-live="polite">
      <div>
        <Route size={20} />
        <strong>{progress.stage}</strong>
        <span>{progress.detail}</span>
        <div className="optimization-progress" role="progressbar" aria-label="Optimization progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent}>
          <i style={{ width: `${progress.percent}%` }} />
        </div>
        <small>{progress.percent}% · {solverLabel}</small>
      </div>
    </div>
  )
}

function App() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [solverId, setSolverId] = useState(DEFAULT_SOLVER_ID)
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem('quasar-theme') === 'dark' ? 'dark' : 'light'))
  const [fontScale, setFontScale] = useState<FontScale>(() => {
    const saved = localStorage.getItem('quasar-font-scale')
    return saved === 'large' || saved === 'xlarge' ? saved : 'standard'
  })
  const [quantumConnection, setQuantumConnection] = useState<QuantumConnection | null>(null)
  const [isCheckingQuantumConnection, setIsCheckingQuantumConnection] = useState(false)
  const [qudoraConnection, setQudoraConnection] = useState<QudoraConnection | null>(null)
  const [isCheckingQudoraConnection, setIsCheckingQudoraConnection] = useState(false)
  const [orders, setOrders] = useState<Order[]>(initialOrders)
  const [vehicles, setVehicles] = useState<Vehicle[]>(initialVehicles)
  const [currentScreen, setCurrentScreen] = useState<Screen>('overview')
  const [isOptimizing, setIsOptimizing] = useState(false)
  const [optimizationProgress, setOptimizationProgress] = useState<OptimizationProgress>({ percent: 0, stage: 'Preparing route', detail: 'Waiting to submit the verified API run.' })
  const [routingDetailsOpen, setRoutingDetailsOpen] = useState(false)
  const [changeAddressOpen, setChangeAddressOpen] = useState(false)
  const [addNewOrderOpen, setAddNewOrderOpen] = useState(false)
  const [comparisonRows, setComparisonRows] = useState<ComparisonRow[]>([])
  const [runEvidence, setRunEvidence] = useState<RunEvidence | null>(null)
  const [quantumJobs, setQuantumJobs] = useState<QuantumJob[]>([])
  const [quantumWarmStart, setQuantumWarmStart] = useState<QuantumWarmStartEvidence | null>(null)
  const [optimizeError, setOptimizeError] = useState<string | null>(null)
  const [rerouteAfterStateChange, setRerouteAfterStateChange] = useState(false)
  const [pendingRestoredFleetRoutes, setPendingRestoredFleetRoutes] = useState<OptimizedFleetRoute[] | null>(null)
  const [isClearingAppData, setIsClearingAppData] = useState(false)

  const {
    depot,
    stops,
    truckRoutes,
    totalDistance,
    addStop,
    addStopAuto,
    renameStop,
    updateStopLocation,
    removeStop,
    replaceStops,
    applyOptimizedFleetRoutes,
  } = useRouteSimulation()
  const [newStopIds, setNewStopIds] = useState<Set<string>>(new Set())
  const selectedSolver = getSolverOption(solverId)
  const canOpenLive = runEvidence != null && !isOptimizing
  const bestDistanceMeters = comparisonRows.length ? Math.min(...comparisonRows.map((row) => row.distanceMeters)) : null
  const quantumEvidenceCount = quantumJobs.length + (quantumWarmStart?.jobIds.length || 0)
  const routePreviewDistances = truckRoutes.map((route) => ({
    label: route.truckName,
    meters: route.roadDistance || route.waypoints.reduce((total, waypoint, index) => (
      index === 0 ? 0 : total + haversineMeters(route.waypoints[index - 1], waypoint)
    ), 0),
    color: route.color,
  }))
  let cumulativePreviewDistance = 0
  const cumulativeRoutePreviewPoints = routePreviewDistances.map((route, index) => {
    cumulativePreviewDistance += route.meters
    return {
      ...route,
      cumulativeMeters: cumulativePreviewDistance,
      x: routePreviewDistances.length === 1 ? 350 : 34 + (index * 632) / (routePreviewDistances.length - 1),
    }
  })
  const maxCumulativePreviewDistance = Math.max(...cumulativeRoutePreviewPoints.map((route) => route.cumulativeMeters), 1)
  const overviewMetrics: Metric[] = [
    {
      label: 'Vehicles in latest run',
      value: runEvidence ? String(runEvidence.vehiclesUsed) : '—',
      unit: runEvidence ? `/${vehicles.length}` : undefined,
      detail: runEvidence ? 'assigned by the verified API result' : 'run an optimization to populate this card',
      emphasis: runEvidence ? 'Verified' : 'No run yet',
      Icon: Truck,
      status: runEvidence ? 'good' : 'neutral',
    },
    {
      label: 'Delivery stops',
      value: runEvidence ? String(runEvidence.stopsCount) : '—',
      detail: runEvidence ? 'submitted to the latest route run' : 'not using placeholder orders',
      emphasis: runEvidence ? 'Verified' : 'No run yet',
      Icon: PackageCheck,
      status: runEvidence ? 'good' : 'neutral',
    },
    {
      label: 'Solver objective',
      value: bestDistanceMeters == null ? '—' : `${(bestDistanceMeters / 1000).toFixed(2)} km`,
      detail: runEvidence?.distanceMetric || 'available after a completed API run',
      emphasis: runEvidence?.solverLabel || 'No run yet',
      Icon: Map,
      status: runEvidence ? 'neutral' : 'warning',
    },
    {
      label: 'Quantum evidence',
      value: runEvidence?.quantumRequested ? String(quantumEvidenceCount) : '—',
      detail: !runEvidence ? 'select a quantum mode to request it' : runEvidence.quantumRequested
        ? (quantumEvidenceCount ? 'traceable quantum job record(s)' : quantumWarmStart?.error || 'quantum path returned no traceable job record')
        : 'not requested: latest run used a classical solver',
      emphasis: runEvidence?.quantumRequested ? 'Requested' : 'Classical run',
      Icon: TriangleAlert,
      status: runEvidence?.quantumRequested && quantumEvidenceCount ? 'good' : 'neutral',
    },
  ]

  useEffect(() => {
    localStorage.setItem('quasar-theme', theme)
    localStorage.setItem('quasar-font-scale', fontScale)
  }, [theme, fontScale])

  useEffect(() => {
    if (!pendingRestoredFleetRoutes) return
    applyOptimizedFleetRoutes(pendingRestoredFleetRoutes)
    setPendingRestoredFleetRoutes(null)
  }, [applyOptimizedFleetRoutes, pendingRestoredFleetRoutes, stops.length])

  useEffect(() => {
    let cancelled = false
    const restoreLatestRun = async () => {
      try {
        const response = await fetch('/api/v1/optimize/latest')
        if (response.status === 404) return
        if (!response.ok) throw new Error(`Latest-run restore failed (${response.status})`)
        const latest = await response.json() as {
          run_id: string
          stops_count: number
          distance_metric?: string | null
          stops: Array<{ name: string; lat: number; lon: number; demand: number }>
          fleet_routes: OptimizedFleetRoute[]
          results: Array<{ algorithm: string; tour: number[]; distance_meters: number; execution_time_ms: number; is_valid: boolean; approximation_ratio?: number | null }>
          quantum_jobs: QuantumJob[]
        }
        if (cancelled) return
        const restoredStops = latest.stops.map((stop, index) => ({ id: `N${index + 1}`, name: stop.name, lat: stop.lat, lon: stop.lon }))
        if (restoredStops.length > 0) {
          replaceStops(restoredStops)
          setOrders(latest.stops.map((stop, index) => ({ id: `N${index + 1}`, address: stop.name, weight: String(stop.demand), startTime: '09:00', endTime: '17:00' })))
        }
        const restoredFleetRoutes = latest.fleet_routes.length > 0
          ? latest.fleet_routes
          : (() => {
              const seed = latest.results.find((row) => row.algorithm.startsWith('OR-Tools')) || latest.results[0]
              return seed ? [{ vehicle_id: 'truck-1', vehicle_name: 'Truck 1', capacity: 100, load: latest.stops.reduce((total, stop) => total + stop.demand, 0), route: seed.tour, distance_meters: seed.distance_meters }] : []
            })()
        if (restoredFleetRoutes.length > 0) {
          setVehicles(restoredFleetRoutes.map((route) => ({ id: route.vehicle_id, name: route.vehicle_name, capacity: String(route.capacity) })))
          setPendingRestoredFleetRoutes(restoredFleetRoutes)
        }
        setComparisonRows(latest.results.map((row) => ({
          algorithm: row.algorithm,
          distanceMeters: row.distance_meters,
          executionTimeMs: row.execution_time_ms,
          isValid: row.is_valid,
          approximationRatio: row.approximation_ratio ?? null,
        })))
        setQuantumJobs(latest.quantum_jobs)
        const restoredSolverLabel = latest.results.some((row) => /qaoa|quantum/i.test(row.algorithm))
          ? 'Restored verified solver comparison'
          : latest.results[0]?.algorithm || 'Restored verified run'
        setRunEvidence({
          runId: latest.run_id,
          stopsCount: latest.stops_count,
          distanceMetric: latest.distance_metric ?? null,
          solverLabel: restoredSolverLabel,
          quantumRequested: latest.quantum_jobs.length > 0,
          vehiclesUsed: restoredFleetRoutes.length,
        })
      } catch {
        // A dashboard must remain usable when the optional historical restore is unavailable.
      }
    }
    void restoreLatestRun()
    return () => { cancelled = true }
  }, [replaceStops])

  // The verified quantum encoding is single-vehicle TSP. Keep fleet mode on
  // the production OR-Tools CVRP solver instead of presenting a false QAOA run.
  useEffect(() => {
    if (vehicles.length > 1 && getSolverOption(solverId).algorithms.includes('qaoa')) {
      setSolverId('or_tools')
    }
  }, [vehicles.length, solverId])

  const handleStartRouting = () => {
    setCurrentScreen('planner')
  }

  const handleSaveSettings = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSettingsOpen(false)
  }

  const clearAppData = useCallback(async () => {
    if (!window.confirm('Clear every saved run, result, and quantum job trace? This cannot be undone.')) return
    if (window.prompt('Type DELETE to permanently clear app data.') !== 'DELETE') return
    setIsClearingAppData(true)
    try {
      const response = await fetch('/api/v1/app-data', {
        method: 'DELETE',
        headers: { 'X-Confirm-Reset': 'DELETE_ALL_APP_DATA' },
      })
      if (!response.ok) throw new Error(`Clear app data failed (${response.status})`)
      setComparisonRows([])
      setQuantumJobs([])
      setQuantumWarmStart(null)
      setRunEvidence(null)
      setOptimizeError(null)
      setPendingRestoredFleetRoutes(null)
      setOrders(initialOrders)
      setVehicles(initialVehicles)
      replaceStops(getDemoPreset('quantum-3').stops.map(({ weight: _weight, startTime: _startTime, endTime: _endTime, ...stop }) => stop))
      setNewStopIds(new Set())
      localStorage.removeItem('quasar-theme')
      localStorage.removeItem('quasar-font-scale')
      setTheme('light')
      setFontScale('standard')
      setSolverId(DEFAULT_SOLVER_ID)
      setSettingsOpen(false)
      setCurrentScreen('overview')
    } catch (error) {
      setOptimizeError(error instanceof Error ? error.message : 'Could not clear app data.')
    } finally {
      setIsClearingAppData(false)
    }
  }, [replaceStops])

  const checkQuantumConnection = useCallback(async () => {
    setIsCheckingQuantumConnection(true)
    try {
      const response = await fetch('/api/v1/quantum/connection-check', { method: 'POST' })
      if (!response.ok) throw new Error(`Connection check failed (${response.status})`)
      setQuantumConnection(await response.json() as QuantumConnection)
    } catch (error) {
      setQuantumConnection({
        status: 'api_unreachable',
        env_file_present: false,
        token_configured: false,
        message: error instanceof Error ? error.message : 'Could not reach the QUASAR API.',
      })
    } finally {
      setIsCheckingQuantumConnection(false)
    }
  }, [])

  const checkQudoraConnection = useCallback(async () => {
    setIsCheckingQudoraConnection(true)
    try {
      const response = await fetch('/api/v1/quantum/qudora/connection-check', { method: 'POST' })
      if (!response.ok) throw new Error(`QUDORA connection check failed (${response.status})`)
      setQudoraConnection(await response.json() as QudoraConnection)
    } catch (error) {
      setQudoraConnection({
        status: 'api_unreachable', env_file_present: false, token_configured: false,
        worker_configured: false, backends: [],
        message: error instanceof Error ? error.message : 'Could not reach the QUASAR API.',
      })
    } finally {
      setIsCheckingQudoraConnection(false)
    }
  }, [])

  const runOptimization = useCallback(async () => {
    setIsOptimizing(true)
    setOptimizationProgress({ percent: 8, stage: 'Preparing routing request', detail: 'Validating stops, fleet capacity, and the selected solver.' })
    setOptimizeError(null)
    const solver = getSolverOption(solverId)

    if (stops.length > MAX_CLASSICAL_DEMO_STOPS) {
      setOptimizeError(`This demo accepts at most ${MAX_CLASSICAL_DEMO_STOPS} stops per API run.`)
      setIsOptimizing(false)
      return
    }
    if (solver.algorithms.includes('qaoa') && stops.length > MAX_QAOA_STOPS) {
      setOptimizeError(`QAOA is verified only for up to ${MAX_QAOA_STOPS} stops. Choose a classical solver for this route.`)
      setIsOptimizing(false)
      return
    }
    if (solver.id === 'qaoa_plus_qudora' && stops.length > MAX_QAOA_PLUS_WARM_START_STOPS) {
      setOptimizeError(`QAOA+ warm-start evidence accepts at most ${MAX_QAOA_PLUS_WARM_START_STOPS} stops because its bounded neighbourhood is built from the verified OR-Tools fleet route.`)
      setIsOptimizing(false)
      return
    }
    if (solver.id === 'qaoa_plus_qudora' && vehicles.length > 4) {
      setOptimizeError('QAOA+ warm-start evidence supports up to 4 vehicles because the bounded quantum sandbox validates one seed route per vehicle.')
      setIsOptimizing(false)
      return
    }

    const demandById = new globalThis.Map(orders.map((order) => [order.id, Math.max(0, Number(order.weight) || 0)]))
    const payload = {
      depot: { name: depot.name, lat: depot.lat, lon: depot.lon },
      stops: stops.map((stop) => ({ name: stop.name, lat: stop.lat, lon: stop.lon, demand: demandById.get(stop.id) || 0 })),
      vehicles: vehicles.length > 1
        ? vehicles.map((vehicle) => ({ id: vehicle.id, name: vehicle.name, capacity: Number(vehicle.capacity) || 0 }))
        : undefined,
      algorithms: solver.algorithms,
    }

    try {
      setQuantumWarmStart(null)
      setOptimizationProgress({ percent: 18, stage: 'Submitting classical fleet route', detail: 'Creating the asynchronous OR-Tools CVRP run.' })
      const submit = await fetch('/api/v1/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!submit.ok) {
        throw new Error(`Optimize failed (${submit.status})`)
      }
      const { run_id: runId } = await submit.json() as { run_id: string }
      setOptimizationProgress({ percent: 30, stage: 'Optimizing road route', detail: `Run ${runId.slice(0, 8)} is queued. Polling verified API status.` })

      let completed = false
      for (let attempt = 0; attempt < 90; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000))
        if (attempt > 0 && attempt % 5 === 0) {
          setOptimizationProgress({ percent: Math.min(62, 30 + attempt * 2), stage: 'Waiting for verified route result', detail: `Polling the API for run ${runId.slice(0, 8)}. No mock result is shown.` })
        }
        const statusRes = await fetch(`/api/v1/optimize/${runId}`)
        if (!statusRes.ok) {
          throw new Error(`Status poll failed (${statusRes.status})`)
        }
        const statusBody = await statusRes.json() as {
          status: string
          error_message?: string | null
          results?: Array<{
            algorithm: string
            tour: number[]
            distance_meters: number
            execution_time_ms: number
            is_valid: boolean
            approximation_ratio?: number | null
          }>
          quantum_jobs?: Array<{
            job_id: string
            algorithm: string
            backend_name: string
            status: string
            qpu_time_seconds?: number | null
          }>
          stops_count: number
          distance_metric?: string | null
          fleet_routes?: OptimizedFleetRoute[]
        }
        if (statusBody.status === 'FAILED') {
          throw new Error(statusBody.error_message || 'Optimization failed')
        }
        if (statusBody.status === 'COMPLETED') {
          const rows = (statusBody.results || []).map((row) => ({
            algorithm: row.algorithm,
            distanceMeters: row.distance_meters,
            executionTimeMs: row.execution_time_ms,
            isValid: row.is_valid,
            approximationRatio: row.approximation_ratio ?? null,
          }))
          setComparisonRows(rows)
          setQuantumJobs((statusBody.quantum_jobs || []).map((job) => ({
            jobId: job.job_id,
            algorithm: job.algorithm,
            backendName: job.backend_name,
            status: job.status,
            qpuTimeSeconds: job.qpu_time_seconds ?? null,
          })))
          setRunEvidence({
            runId,
            stopsCount: statusBody.stops_count,
            distanceMetric: statusBody.distance_metric ?? null,
            solverLabel: solver.label,
            quantumRequested: solver.algorithms.includes('qaoa') || solver.id === 'qaoa_plus_qudora',
            vehiclesUsed: (statusBody.fleet_routes || []).length || 1,
          })
          const fleetRoutes = statusBody.fleet_routes || []
          if (fleetRoutes.length > 0) {
            applyOptimizedFleetRoutes(fleetRoutes)
          } else {
            // A single-vehicle TSP run must render the exact tour returned by
            // the API, rather than the old frontend-only two-truck preview.
            const mapResult = (statusBody.results || []).find((row) => row.algorithm.startsWith('OR-Tools')) || statusBody.results?.[0]
            const vehicle = vehicles[0] || { id: 'truck-1', name: 'Truck 1', capacity: '—' }
            applyOptimizedFleetRoutes(mapResult ? [{
              vehicle_id: vehicle.id,
              vehicle_name: vehicle.name,
              capacity: Number(vehicle.capacity) || 0,
              load: Array.from(demandById.values()).reduce((sum, demand) => sum + demand, 0),
              route: mapResult.tour,
              distance_meters: mapResult.distance_meters,
            }] : [])
          }
          if (solver.id === 'qaoa_plus_qudora') {
            try {
              const routeSeed = fleetRoutes.length > 0
                ? fleetRoutes.map((route) => route.route)
                : [(statusBody.results || []).find((row) => row.algorithm.startsWith('OR-Tools'))?.tour]
              if (routeSeed.some((route) => !route || route.length < 2)) throw new Error('OR-Tools did not return a valid fleet seed for the QAOA+ warm-start')
              const locations = [depot, ...stops]
              const matrix = locations.map((from) => locations.map((to) => haversineMeters(from, to)))
              const activeVehicles = vehicles.slice(0, 4)
              if (routeSeed.length !== activeVehicles.length) throw new Error('The classical seed route count does not match the configured fleet')
              setOptimizationProgress({ percent: 72, stage: 'Building bounded QAOA+ neighbourhood', detail: `OR-Tools produced the fleet seed. Encoding at most 8 local moves, not all ${stops.length} stops.` })
              setOptimizationProgress({ percent: 84, stage: 'Running QAOA+ on QUDORA', detail: 'Transpiling the bounded circuit and waiting for the Qamelion cloud result.' })
              const warmStartRes = await fetch('/api/v1/quantum/warm-start', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                matrix,
                demands: [0, ...stops.map((stop) => demandById.get(stop.id) || 0)],
                capacities: activeVehicles.map((vehicle) => Number(vehicle.capacity) || 0),
                starting_nodes: activeVehicles.map(() => 0),
                routes: Object.fromEntries(routeSeed.map((route, index) => [String(index), route])),
                problem_type: 'cvrp',
                executor: 'qudora',
                qudora_backend: 'Qamelion',
                shots: 64,
                maxiter: 8,
                max_candidates: 8,
                neighborhood_size: 8,
                random_seed: 42,
              }),
            })
              if (!warmStartRes.ok) throw new Error(`QUDORA QAOA+ warm-start failed (${warmStartRes.status})`)
              const warmStart = await warmStartRes.json() as { result: Record<string, unknown> }
              const result = warmStart.result
              setQuantumWarmStart({
              algorithm: String(result.algorithm || 'QAOA+ XY warm-start'),
              executor: String(result.executor || 'qudora'),
              backend: result.backend == null ? null : String(result.backend),
              jobIds: Array.isArray(result.job_ids) ? result.job_ids.map(String) : [],
              valid: Boolean(result.valid),
              accepted: Boolean(result.accepted),
              acceptanceReason: result.acceptance_reason == null ? null : String(result.acceptance_reason),
              initialCost: Number(result.initial_cost || 0),
              finalCost: Number(result.final_cost || 0),
              improvementPercent: Number(result.improvement_percent || 0),
              feasibleSampleRate: result.feasible_sample_rate == null ? null : Number(result.feasible_sample_rate),
              shots: result.shots == null ? null : Number(result.shots),
              nQubits: Number(result.n_qubits || 0),
              circuitDepth: result.circuit_depth == null ? null : Number(result.circuit_depth),
              })
              setOptimizationProgress({ percent: 96, stage: 'QAOA+ evidence verified', detail: 'Received the QUDORA result and recorded its execution evidence.' })
            } catch (warmStartError) {
              setQuantumWarmStart({
                algorithm: 'QAOA+ XY warm-start', executor: 'qudora', backend: null, jobIds: [], valid: false,
                accepted: false, acceptanceReason: null, initialCost: 0, finalCost: 0, improvementPercent: 0,
                feasibleSampleRate: null, shots: null, nQubits: 0, circuitDepth: null,
                error: warmStartError instanceof Error ? warmStartError.message : 'QUDORA warm-start unavailable.',
              })
            }
          }
          completed = true
          break
        }
      }
      if (!completed) {
        throw new Error('Optimization timed out while waiting for results')
      }
      setOptimizationProgress({ percent: 100, stage: 'Verified result ready', detail: 'Opening the route result and execution evidence.' })
      setCurrentScreen('results')
    } catch (error) {
      setComparisonRows([])
      setQuantumJobs([])
      setRunEvidence(null)
      setOptimizeError(error instanceof Error ? `${error.message}. No benchmark result was created.` : 'Optimization unavailable. No benchmark result was created.')
    } finally {
      setIsOptimizing(false)
    }
  }, [solverId, depot, stops, orders, vehicles, applyOptimizedFleetRoutes])

  useEffect(() => {
    if (!rerouteAfterStateChange || isOptimizing) return
    setRerouteAfterStateChange(false)
    void runOptimization()
  }, [rerouteAfterStateChange, isOptimizing, runOptimization])

  const addPlannerDeliveryPoint = useCallback(() => {
    if (stops.length >= MAX_CLASSICAL_DEMO_STOPS) {
      setOptimizeError(`The classical demo is capped at ${MAX_CLASSICAL_DEMO_STOPS} stops.`)
      return
    }
    const nextNode = Math.max(0, ...orders.map((order) => Number(order.id.replace('N', '')) || 0)) + 1
    const id = `N${nextNode}`
    setOrders((currentOrders) => [
      ...currentOrders,
      { id, address: '', weight: '', startTime: '09:00', endTime: '10:00' },
    ])
    addStopAuto(id)
  }, [addStopAuto, orders, stops.length])

  const applyDemoPreset = useCallback((presetId: DemoPresetId) => {
    const preset = getDemoPreset(presetId)
    replaceStops(preset.stops.map(({ weight: _weight, startTime: _startTime, endTime: _endTime, ...stop }) => stop))
    setOrders(preset.stops.map(({ id, name, weight, startTime, endTime }) => ({
      id,
      address: name,
      weight,
      startTime,
      endTime,
    })))
    setVehicles(preset.stops.length <= 3
      ? initialVehicles
      : [
          { id: 'truck-1', name: 'Truck 1', capacity: '70' },
          { id: 'truck-2', name: 'Truck 2', capacity: '70' },
          { id: 'truck-3', name: 'Truck 3', capacity: '70' },
        ])
    setNewStopIds(new Set())
    setOptimizeError(null)
    if (preset.stops.length > MAX_QAOA_STOPS && getSolverOption(solverId).algorithms.includes('qaoa')) {
      setSolverId('or_tools')
    }
  }, [replaceStops, solverId])

  const removePlannerDeliveryPoint = useCallback((id: string) => {
    removeStop(id)
  }, [removeStop])

  const updateAffectedAddress = ({ address, lat, lon }: { address: string; lat: number; lon: number }) => {
    setOrders((currentOrders) => currentOrders.map((order) => (
      order.id === 'N4' ? { ...order, address } : order
    )))
    updateStopLocation('N4', address, lat, lon)
    setChangeAddressOpen(false)
    setRerouteAfterStateChange(true)
  }

  const handleUpdateStopLocation = useCallback((id: string, name: string, lat: number, lon: number) => {
    setOrders((currentOrders) => currentOrders.map((order) => (
      order.id === id ? { ...order, address: name } : order
    )))
    updateStopLocation(id, name, lat, lon)
  }, [updateStopLocation])

  const addLiveOrder = useCallback((draft: NewOrderDraft, shouldReRoute: boolean) => {
    const nextNode = Math.max(0, ...orders.map((order) => Number(order.id.replace('N', '')) || 0)) + 1
    const newId = `N${nextNode}`
    setOrders((currentOrders) => [
      ...currentOrders,
      {
        id: newId,
        address: draft.address,
        weight: draft.weight,
        startTime: draft.startTime,
        endTime: draft.endTime,
      },
    ])
    addStopAuto(newId, draft.address || undefined)
    setNewStopIds((prev) => new Set(prev).add(newId))
    setAddNewOrderOpen(false)
    if (shouldReRoute) {
      setRerouteAfterStateChange(true)
    }
  }, [orders, addStopAuto])

  const handleMapClick = useCallback((latlng: { lat: number; lon: number }) => {
    const nextNode = Math.max(0, ...orders.map((order) => Number(order.id.replace('N', '')) || 0)) + 1
    const newId = `N${nextNode}`
    setOrders((currentOrders) => [
      ...currentOrders,
      {
        id: newId,
        address: `Map pin (${latlng.lat.toFixed(4)}, ${latlng.lon.toFixed(4)})`,
        weight: '10',
        startTime: '09:00',
        endTime: '11:00',
      },
    ])
    addStop(latlng.lat, latlng.lon, `Map Stop ${nextNode}`)
    setNewStopIds((prev) => new Set(prev).add(newId))
  }, [orders, addStop])

  return (
    <main className={`app theme-${theme} font-${fontScale}`}>
      <ApplicationHeader onOpenSettings={() => setSettingsOpen(true)} onGoHome={() => setCurrentScreen('overview')} />

      <div className="screen-transition" key={currentScreen}>
      {currentScreen === 'overview' && (
        <>
          <section className="workspace" id="overview" aria-labelledby="page-title">
            <div className="page-intro">
              <div>
                <p className="eyebrow">Operations center</p>
                <h1 id="page-title">Operations Overview</h1>
                <p className="subtitle">Monitor current deliveries, fleet capacity, and route status.</p>
              </div>
              <div className="page-actions">
                <button className="settings-button" onClick={() => setCurrentScreen('benchmark')}>
                  <BarChart3 size={16} /> Benchmark
                </button>
                <button className="route-action" onClick={handleStartRouting}>
                  Start Routing <Navigation size={16} />
                </button>
              </div>
            </div>
            <section className="metric-grid" aria-label="Today operations summary">
              {overviewMetrics.map(({ Icon, ...metric }) => (
                <article className="metric" key={metric.label}>
                  <div className="metric-label"><Icon size={17} /><span>{metric.label}</span></div>
                  <strong>{metric.value}{metric.unit && <span>{metric.unit}</span>}</strong>
                  <small className={metric.status}><b>{metric.emphasis}</b> {metric.detail}</small>
                </article>
              ))}
            </section>
            <section className="main-grid">
              <article className="panel history-chart-card">
                <div className="panel-heading">
                  <div>
                    <p className="section-label">Latest route geometry</p>
                    <h2>Cumulative route preview by vehicle</h2>
                  </div>
                </div>
                {runEvidence && routePreviewDistances.length > 0 ? (
                  <>
                    <div className="history-chart" role="img" aria-label="Cumulative map route-preview distance in vehicle dispatch order for the latest verified run">
                      <svg viewBox="0 0 700 230" preserveAspectRatio="none" aria-hidden="true">
                        <line x1="24" y1="30" x2="676" y2="30" />
                        <line x1="24" y1="90" x2="676" y2="90" />
                        <line x1="24" y1="150" x2="676" y2="150" />
                        <line x1="24" y1="210" x2="676" y2="210" />
                        {cumulativeRoutePreviewPoints.length === 1 && <line className="delivery-line" x1="84" y1={210 - (cumulativeRoutePreviewPoints[0].cumulativeMeters / maxCumulativePreviewDistance) * 160} x2="616" y2={210 - (cumulativeRoutePreviewPoints[0].cumulativeMeters / maxCumulativePreviewDistance) * 160} />}
                        <polyline className="delivery-line" points={cumulativeRoutePreviewPoints.map((point) => `${point.x},${210 - (point.cumulativeMeters / maxCumulativePreviewDistance) * 160}`).join(' ')} />
                        {cumulativeRoutePreviewPoints.map((point) => <circle className="delivery-point" cx={point.x} cy={210 - (point.cumulativeMeters / maxCumulativePreviewDistance) * 160} r="2.8" key={point.label} />)}
                      </svg>
                      <div className="chart-labels">{cumulativeRoutePreviewPoints.map((point) => <span key={point.label}>{point.label}</span>)}</div>
                    </div>
                    <div className="chart-legend"><span><i className="delivery-key" /> Cumulative map-preview distance: {cumulativeRoutePreviewPoints.map((point) => `${point.label} ${(point.cumulativeMeters / 1000).toFixed(2)} km`).join(' · ')}</span></div>
                  </>
                ) : (
                  <div className="empty-state overview-empty-state" role="status"><Map size={20} /><div><h2>No verified route yet</h2><p>Load a demo scenario in Route Planner, then run optimization to populate this chart.</p></div></div>
                )}
              </article>
              <article className="panel historical-data-card">
                <div className="panel-heading">
                  <div>
                    <p className="section-label">Run evidence</p>
                    <h2>Latest API result</h2>
                  </div>
                </div>
                {runEvidence ? <>
                  <div className="history-summary"><strong>{bestDistanceMeters == null ? '—' : `${(bestDistanceMeters / 1000).toFixed(2)}`}<span>{bestDistanceMeters == null ? '' : ' km'}</span></strong><p>solver objective</p></div>
                  <div className="history-records">
                    <div className="history-record"><span>Run</span><div><b>{runEvidence.runId.slice(0, 8)}</b><small>{runEvidence.distanceMetric || 'distance basis unavailable'}</small></div></div>
                    <div className="history-record"><span>Mode</span><div><b>{runEvidence.solverLabel}</b><small>{runEvidence.quantumRequested ? 'quantum path requested' : 'classical-only run'}</small></div></div>
                    <div className="history-record"><span>Evidence</span><div><b>{quantumEvidenceCount} quantum job record(s)</b><small>{quantumEvidenceCount ? 'traceable job IDs available' : 'no quantum job was requested or returned'}</small></div></div>
                  </div>
                </> : <div className="empty-state overview-empty-state" role="status"><TriangleAlert size={20} /><div><h2>No API evidence yet</h2><p>This dashboard intentionally does not invent operational history.</p></div></div>}
              </article>
            </section>
            <section className="bottom-grid">
              <article className="panel activity-card">
                <div className="panel-heading">
                  <div>
                    <p className="section-label">Workflow status</p>
                    <h2>Latest verified update</h2>
                  </div>
                  <span className={`listener-status ${runEvidence ? '' : 'is-idle'}`}><i /> {runEvidence ? 'Verified run available' : 'Waiting for first run'}</span>
                </div>
                <div className="activity-item">
                  <time>{runEvidence ? 'DONE' : 'READY'}</time>
                  <span className={`activity-mark ${runEvidence ? 'delivered' : 'tracking'}`}>{runEvidence ? <PackageCheck size={15} /> : <Navigation size={15} />}</span>
                  <p><b>{runEvidence ? `${runEvidence.solverLabel} completed` : 'Configure a route scenario'}</b><small>{runEvidence ? `${runEvidence.stopsCount} stops · ${runEvidence.runId}` : 'Use Route Planner to load a preset or add delivery points.'}</small></p>
                </div>
              </article>
            </section>
          </section>
        </>
      )}

      {currentScreen === 'planner' && (
        <RoutePlanner
          orders={orders}
          setOrders={setOrders}
          vehicles={vehicles}
          setVehicles={setVehicles}
          isOptimizing={isOptimizing}
          solverId={solverId}
          onSolverChange={setSolverId}
          onNavigate={setCurrentScreen}
          canViewResults={runEvidence != null}
          canViewLive={canOpenLive}
          onOpenRoutingDetails={() => setRoutingDetailsOpen(true)}
          onRunOptimization={() => { void runOptimization() }}
          optimizeError={optimizeError}
          onAddDeliveryPoint={addPlannerDeliveryPoint}
          onRemoveDeliveryPoint={removePlannerDeliveryPoint}
          onRenameDeliveryPoint={renameStop}
          onApplyDemoPreset={applyDemoPreset}
          depot={depot}
          stops={stops}
          truckRoutes={truckRoutes}
          onUpdateStopLocation={handleUpdateStopLocation}
          onMapClick={handleMapClick}
        />
      )}
      {currentScreen === 'results' && (
        <div className="planner-shell">
          <WorkflowSidebar currentScreen="results" onNavigate={setCurrentScreen} canViewResults={runEvidence != null} canViewLive={canOpenLive} onOpenRoutingDetails={() => setRoutingDetailsOpen(true)} />
          <InitialRoutingResults
            isOptimizing={isOptimizing}
            onEditSetup={() => setCurrentScreen('planner')}
            onReRoute={() => { void runOptimization() }}
            onStartOperational={() => { if (canOpenLive) setCurrentScreen('live') }}
            depot={depot}
            stops={stops}
            truckRoutes={truckRoutes}
            totalDistance={totalDistance}
            solverLabel={selectedSolver.label}
            comparisonRows={comparisonRows}
            quantumJobs={quantumJobs}
            quantumWarmStart={quantumWarmStart}
            runEvidence={runEvidence}
            optimizeError={optimizeError}
          />
        </div>
      )}
      {currentScreen === 'live' && (
        <div className="planner-shell">
          <WorkflowSidebar currentScreen="live" onNavigate={setCurrentScreen} canViewResults={runEvidence != null} canViewLive={canOpenLive} onOpenRoutingDetails={() => setRoutingDetailsOpen(true)} />
          <LiveDeliveryAndRouting
            onChangeAddress={() => setChangeAddressOpen(true)}
            onAddNewOrder={() => setAddNewOrderOpen(true)}
            onEndDelivery={() => setCurrentScreen('overview')}
            onViewLogDetails={() => setRoutingDetailsOpen(true)}
            depot={depot}
            stops={stops}
            truckRoutes={truckRoutes}
            totalDistance={totalDistance}
            solverObjectiveMeters={comparisonRows.length ? Math.min(...comparisonRows.map((row) => row.distanceMeters)) : null}
            distanceMetric={runEvidence?.distanceMetric ?? null}
            runId={runEvidence?.runId ?? null}
            onMapClick={handleMapClick}
            newStopIds={newStopIds}
          />
        </div>
      )}
      {currentScreen === 'benchmark' && (
        <BenchmarkAnalysis
          rows={comparisonRows}
          quantumJobs={quantumJobs}
          quantumWarmStart={quantumWarmStart}
          runEvidence={runEvidence}
          onBack={() => setCurrentScreen('overview')}
        />
      )}
      </div>

      {isOptimizing && <OptimizationLoading solverLabel={selectedSolver.label} progress={optimizationProgress} />}
      {settingsOpen && (
        <SettingsModal
          solverId={solverId}
          onSolverChange={setSolverId}
          theme={theme}
          onThemeChange={setTheme}
          fontScale={fontScale}
          onFontScaleChange={setFontScale}
          quantumConnection={quantumConnection}
          isCheckingQuantumConnection={isCheckingQuantumConnection}
          onCheckQuantumConnection={() => { void checkQuantumConnection() }}
          qudoraConnection={qudoraConnection}
          isCheckingQudoraConnection={isCheckingQudoraConnection}
          onCheckQudoraConnection={() => { void checkQudoraConnection() }}
          onClearAppData={() => { void clearAppData() }}
          isClearingAppData={isClearingAppData}
          onSave={handleSaveSettings}
          onClose={() => setSettingsOpen(false)}
        />
      )}
      {routingDetailsOpen && (
        <RoutingDetailsModal
          onClose={() => setRoutingDetailsOpen(false)}
          solverLabel={selectedSolver.label}
          comparisonRows={comparisonRows}
          runEvidence={runEvidence}
        />
      )}
      {changeAddressOpen && <ChangeAddressModal onClose={() => setChangeAddressOpen(false)} onUpdate={updateAffectedAddress} />}
      {addNewOrderOpen && <AddNewOrderModal onClose={() => setAddNewOrderOpen(false)} onAdd={addLiveOrder} />}
    </main>
  )
}

export default App
