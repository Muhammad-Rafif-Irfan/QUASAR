import { useState, useCallback, useEffect, type FormEvent } from 'react'
import { BarChart3, Map, Navigation, PackageCheck, Route, Settings, TriangleAlert, Truck, type LucideIcon } from 'lucide-react'
import BenchmarkAnalysis from './BenchmarkAnalysis'
import InitialRoutingResults, { type QuantumJob } from './InitialRoutingResults'
import LiveDeliveryAndRouting from './LiveDeliveryAndRouting'
import RoutePlanner, { initialOrders, initialVehicles, type Order, type Vehicle } from './RoutePlanner'
import RoutingDetailsModal from './RoutingDetailsModal'
import { AddNewOrderModal, ChangeAddressModal, type NewOrderDraft } from './SupportingStates'
import { getDemoPreset, useRouteSimulation, type DemoPresetId, type OptimizedFleetRoute } from './useRouteSimulation'
import {
  DEFAULT_SOLVER_ID,
  MAX_CLASSICAL_DEMO_STOPS,
  MAX_QAOA_STOPS,
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

type Metric = {
  label: string
  value: string
  unit?: string
  detail: string
  emphasis: string
  Icon: LucideIcon
  status: 'neutral' | 'good' | 'warning' | 'alert'
}

type Activity = {
  time: string
  title: string
  detail: string
  kind: 'delivered' | 'tracking'
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
}

// Metric card data for the Operations Overview page.
const metrics: Metric[] = [
  { label: 'Vehicles Used', value: '2', unit: '/4', detail: 'of fleet deployed', emphasis: '50%', Icon: Truck, status: 'neutral' },
  { label: 'Packages Delivered', value: '18', unit: '/24', detail: 'completed today', emphasis: '75%', Icon: PackageCheck, status: 'good' },
  { label: 'Active Routes', value: '3', detail: 'currently monitored', emphasis: '2 live', Icon: Map, status: 'neutral' },
  { label: 'Operational Events', value: '4', detail: 'event listener connected', emphasis: '1 urgent', Icon: TriangleAlert, status: 'alert' },
]

const recentActivities: Activity[] = [
  { time: '08:40', title: '13 packages delivered', detail: 'Truck T1 returned to depot · 3h 26m', kind: 'delivered' },
  { time: '08:17', title: 'Truck T2 heading to Grand Avenue', detail: 'ETA 8 min', kind: 'tracking' },
]

const deliveryTrend = [42, 56, 51, 68, 62, 78, 73]
const routeTrend = [28, 35, 31, 47, 42, 54, 50]
const historicalRecords = [
  { period: 'Today', deliveries: '18 delivered', routes: '3 active routes' },
  { period: 'Mon, 13 May', deliveries: '16 delivered', routes: '2 completed routes' },
  { period: 'Sun, 12 May', deliveries: '14 delivered', routes: '2 completed routes' },
  { period: 'Sat, 11 May', deliveries: '11 delivered', routes: '1 completed route' },
]

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
  onSave: (event: FormEvent<HTMLFormElement>) => void
  onClose: () => void
}

function ApplicationHeader({ onOpenSettings }: { onOpenSettings: () => void }) {
  const currentDate = new Intl.DateTimeFormat('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  }).format(new Date())

  return (
    <header className="topbar">
      <a className="brand" href="#overview" aria-label="Quasar home">
        <svg width="20" height="20" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="15" cy="15" r="9" stroke="currentColor" strokeWidth="2.2" />
          <path d="M21.5 21.5L27 27" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
          <path d="M10.5 12.5C13.2 13.4 15.5 15.6 18.5 18.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <circle cx="10" cy="12" r="1.6" fill="currentColor" />
          <circle cx="19" cy="19" r="1.6" fill="currentColor" />
        </svg>
        <span>QUASAR</span>
      </a>
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

function SettingsModal({ solverId, onSolverChange, theme, onThemeChange, fontScale, onFontScaleChange, quantumConnection, isCheckingQuantumConnection, onCheckQuantumConnection, onSave, onClose }: SettingsModalProps) {
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
        <p className="settings-copy">
          Choose a classical heuristic, a quantum solver, or run a full side-by-side comparison.
        </p>
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
          <label>
            Number of layers
            <input defaultValue="5" inputMode="numeric" />
          </label>
          <label>
            Quantum backend
            <input defaultValue="AerSimulator / IBM QPU" />
          </label>
          <label>
            Parameter alpha
            <input defaultValue="0.73" inputMode="decimal" />
          </label>
          <label>
            Parameter beta
            <input defaultValue="0.27" inputMode="decimal" />
          </label>
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

function OptimizationLoading({ solverLabel }: { solverLabel: string }) {
  return (
    <div className="optimization-overlay" role="status" aria-live="polite">
      <div>
        <Route size={20} />
        <strong>Optimizing routes...</strong>
        <span>Running {solverLabel}. Waiting for verified API results; no simulated fallback is shown.</span>
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
  const [orders, setOrders] = useState<Order[]>(initialOrders)
  const [vehicles, setVehicles] = useState<Vehicle[]>(initialVehicles)
  const [currentScreen, setCurrentScreen] = useState<Screen>('overview')
  const [isOptimizing, setIsOptimizing] = useState(false)
  const [routingDetailsOpen, setRoutingDetailsOpen] = useState(false)
  const [changeAddressOpen, setChangeAddressOpen] = useState(false)
  const [addNewOrderOpen, setAddNewOrderOpen] = useState(false)
  const [comparisonRows, setComparisonRows] = useState<ComparisonRow[]>([])
  const [runEvidence, setRunEvidence] = useState<RunEvidence | null>(null)
  const [quantumJobs, setQuantumJobs] = useState<QuantumJob[]>([])
  const [optimizeError, setOptimizeError] = useState<string | null>(null)

  const {
    depot,
    stops,
    truckRoutes,
    totalDistance,
    addStop,
    addStopAuto,
    renameStop,
    removeStop,
    replaceStops,
    applyOptimizedFleetRoutes,
  } = useRouteSimulation()
  const [newStopIds, setNewStopIds] = useState<Set<string>>(new Set())
  const selectedSolver = getSolverOption(solverId)

  useEffect(() => {
    localStorage.setItem('quasar-theme', theme)
    localStorage.setItem('quasar-font-scale', fontScale)
  }, [theme, fontScale])

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

  const runOptimization = useCallback(async () => {
    setIsOptimizing(true)
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
      const submit = await fetch('/api/v1/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!submit.ok) {
        throw new Error(`Optimize failed (${submit.status})`)
      }
      const { run_id: runId } = await submit.json() as { run_id: string }

      let completed = false
      for (let attempt = 0; attempt < 90; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000))
        const statusRes = await fetch(`/api/v1/optimize/${runId}`)
        if (!statusRes.ok) {
          throw new Error(`Status poll failed (${statusRes.status})`)
        }
        const statusBody = await statusRes.json() as {
          status: string
          error_message?: string | null
          results?: Array<{
            algorithm: string
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
          })
          applyOptimizedFleetRoutes(statusBody.fleet_routes || [])
          completed = true
          break
        }
      }
      if (!completed) {
        throw new Error('Optimization timed out while waiting for results')
      }
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

  const updateAffectedAddress = (address: string) => {
    setOrders((currentOrders) => currentOrders.map((order) => (
      order.id === 'N4' ? { ...order, address } : order
    )))
    setChangeAddressOpen(false)
  }

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
      void runOptimization()
    }
  }, [orders, addStopAuto, runOptimization])

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
      <ApplicationHeader onOpenSettings={() => setSettingsOpen(true)} />

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
              {metrics.map(({ Icon, ...metric }) => (
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
                    <p className="section-label">Delivery performance</p>
                    <h2>Delivery activity over time</h2>
                  </div>
                </div>
                <div className="history-chart" role="img" aria-label="Seven-day chart of delivered packages and completed routes">
                  <svg viewBox="0 0 700 230" preserveAspectRatio="none" aria-hidden="true">
                    <line x1="24" y1="30" x2="676" y2="30" />
                    <line x1="24" y1="90" x2="676" y2="90" />
                    <line x1="24" y1="150" x2="676" y2="150" />
                    <line x1="24" y1="210" x2="676" y2="210" />
                    <polyline className="delivery-line" points={deliveryTrend.map((value, index) => `${34 + index * 104},${210 - value * 2.1}`).join(' ')} />
                    <polyline className="routes-line" points={routeTrend.map((value, index) => `${34 + index * 104},${210 - value * 2.1}`).join(' ')} />
                    {deliveryTrend.map((value, index) => <circle className="delivery-point" cx={34 + index * 104} cy={210 - value * 2.1} r="2.25" key={`delivery-${index}`} />)}
                    {routeTrend.map((value, index) => <circle className="routes-point" cx={34 + index * 104} cy={210 - value * 2.1} r="2.25" key={`route-${index}`} />)}
                  </svg>
                  <div className="chart-labels"><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Today</span></div>
                </div>
                <div className="chart-legend">
                  <span><i className="delivery-key" /> Delivered packages</span>
                  <span><i className="routes-key" /> Completed routes</span>
                </div>
              </article>
              <article className="panel historical-data-card">
                <div className="panel-heading">
                  <div>
                    <p className="section-label">Historical data</p>
                    <h2>Delivery record</h2>
                  </div>
                </div>
                <div className="history-summary"><strong>94.8<span>%</span></strong><p>average on-time delivery</p></div>
                <div className="history-records">
                  {historicalRecords.map((record) => (
                    <div className="history-record" key={record.period}>
                      <span>{record.period}</span>
                      <div><b>{record.deliveries}</b><small>{record.routes}</small></div>
                    </div>
                  ))}
                </div>
              </article>
            </section>
            <section className="bottom-grid">
              <article className="panel activity-card">
                <div className="panel-heading">
                  <div>
                    <p className="section-label">Recent activity</p>
                    <h2>Latest updates</h2>
                  </div>
                  <span className="listener-status"><i /> Live updates active</span>
                </div>
                {recentActivities.map((activity) => (
                  <div className="activity-item" key={activity.time}>
                    <time>{activity.time}</time>
                    <span className={`activity-mark ${activity.kind}`}>
                      {activity.kind === 'delivered' ? <PackageCheck size={15} /> : <Navigation size={15} />}
                    </span>
                    <p><b>{activity.title}</b><small>{activity.detail}</small></p>
                  </div>
                ))}
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
          onBack={() => setCurrentScreen('overview')}
          onRunOptimization={() => { void runOptimization() }}
          optimizeError={optimizeError}
          onAddDeliveryPoint={addPlannerDeliveryPoint}
          onRemoveDeliveryPoint={removePlannerDeliveryPoint}
          onRenameDeliveryPoint={renameStop}
          onApplyDemoPreset={applyDemoPreset}
        />
      )}
      {currentScreen === 'results' && (
        <InitialRoutingResults
          isOptimizing={isOptimizing}
          onEditSetup={() => setCurrentScreen('planner')}
          onReRoute={() => { void runOptimization() }}
          onStartOperational={() => setCurrentScreen('live')}
          depot={depot}
          stops={stops}
          truckRoutes={truckRoutes}
          totalDistance={totalDistance}
          solverLabel={selectedSolver.label}
          comparisonRows={comparisonRows}
          quantumJobs={quantumJobs}
          runEvidence={runEvidence}
          optimizeError={optimizeError}
        />
      )}
      {currentScreen === 'live' && (
        <LiveDeliveryAndRouting
          onChangeAddress={() => setChangeAddressOpen(true)}
          onAddNewOrder={() => setAddNewOrderOpen(true)}
          onEndDelivery={() => setCurrentScreen('overview')}
          onViewLogDetails={() => setRoutingDetailsOpen(true)}
          depot={depot}
          stops={stops}
          truckRoutes={truckRoutes}
          totalDistance={totalDistance}
          onMapClick={handleMapClick}
          newStopIds={newStopIds}
        />
      )}
      {currentScreen === 'benchmark' && (
        <BenchmarkAnalysis
          rows={comparisonRows}
          quantumJobs={quantumJobs}
          runEvidence={runEvidence}
          onBack={() => setCurrentScreen('overview')}
        />
      )}
      </div>

      {isOptimizing && <OptimizationLoading solverLabel={selectedSolver.label} />}
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
