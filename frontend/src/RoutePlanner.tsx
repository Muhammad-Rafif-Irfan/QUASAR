import type { Dispatch, SetStateAction } from 'react'
import { ArrowLeft, PackageCheck, Plus, Trash2, Truck, Upload } from 'lucide-react'
import { SOLVER_OPTIONS, getSolverOption } from './solvers'
import { demoPresets, type DemoPresetId, ALL_AVAILABLE_LOCATIONS, type MapLocation, type TruckRoute } from './useRouteSimulation'
import LiveMap from './LiveMap'

export type Order = {
  id: string
  address: string
  weight: string
  startTime: string
  endTime: string
}

export type Vehicle = {
  id: string
  name: string
  capacity: string
}

type RoutePlannerProps = {
  orders: Order[]
  setOrders: Dispatch<SetStateAction<Order[]>>
  vehicles: Vehicle[]
  setVehicles: Dispatch<SetStateAction<Vehicle[]>>
  isOptimizing: boolean
  solverId: string
  onSolverChange: (id: string) => void
  onBack: () => void
  onRunOptimization: () => void
  optimizeError: string | null
  onAddDeliveryPoint: () => void
  onRemoveDeliveryPoint: (id: string) => void
  onRenameDeliveryPoint: (id: string, name: string) => void
  onApplyDemoPreset: (id: DemoPresetId) => void
  depot: MapLocation
  stops: MapLocation[]
  truckRoutes: TruckRoute[]
  onUpdateStopLocation: (id: string, name: string, lat: number, lon: number) => void
  onMapClick: (latlng: { lat: number; lon: number }) => void
}

export const initialOrders: Order[] = [
  { id: 'N1', address: 'Pleiku Airport', weight: '12', startTime: '09:00', endTime: '10:00' },
  { id: 'N2', address: 'Biển Hồ Pleiku', weight: '38', startTime: '09:00', endTime: '10:00' },
  { id: 'N3', address: 'Chùa Minh Đạo, Diên Phú', weight: '24', startTime: '10:00', endTime: '11:00' },
]

export const initialVehicles: Vehicle[] = [
  { id: 'truck-1', name: 'Truck 1', capacity: '100' },
]

function RoutePlanner({
  orders,
  setOrders,
  vehicles,
  setVehicles,
  isOptimizing,
  solverId,
  onSolverChange,
  onBack,
  onRunOptimization,
  optimizeError,
  onAddDeliveryPoint,
  onRemoveDeliveryPoint,
  onRenameDeliveryPoint,
  onApplyDemoPreset,
  depot,
  stops,
  truckRoutes,
  onUpdateStopLocation,
  onMapClick,
}: RoutePlannerProps) {
  const totalDemand = orders.reduce((total, order) => total + (Number(order.weight) || 0), 0)
  const totalCapacity = vehicles.reduce((total, vehicle) => total + (Number(vehicle.capacity) || 0), 0)
  const selectedSolver = getSolverOption(solverId)

  const handleAddressChange = (id: string, addressName: string) => {
    const loc = ALL_AVAILABLE_LOCATIONS.find((l) => l.name === addressName)
    if (loc) {
      onUpdateStopLocation(id, loc.name, loc.lat, loc.lon)
    }
  }

  const getAddressOptions = (currentAddress: string) => {
    const exists = ALL_AVAILABLE_LOCATIONS.some((l) => l.name === currentAddress)
    if (exists || !currentAddress) {
      return ALL_AVAILABLE_LOCATIONS
    }
    return [...ALL_AVAILABLE_LOCATIONS, { name: currentAddress, lat: 0, lon: 0 }]
  }

  const updateOrder = (id: string, field: keyof Order, value: string) => {
    setOrders((currentOrders) => currentOrders.map((order) => (
      order.id === id ? { ...order, [field]: value } : order
    )))
    if (field === 'address') onRenameDeliveryPoint(id, value)
  }

  const removeOrder = (id: string) => {
    setOrders((currentOrders) => currentOrders.filter((order) => order.id !== id))
    onRemoveDeliveryPoint(id)
  }

  const updateVehicle = (id: string, field: keyof Vehicle, value: string) => {
    setVehicles((currentVehicles) => currentVehicles.map((vehicle) => (
      vehicle.id === id ? { ...vehicle, [field]: value } : vehicle
    )))
  }

  const addVehicle = () => {
    const nextVehicle = vehicles.length + 1
    setVehicles((currentVehicles) => [
      ...currentVehicles,
      { id: `truck-${Date.now()}`, name: `Truck ${nextVehicle}`, capacity: '' },
    ])
  }

  const removeVehicle = (id: string) => {
    setVehicles((currentVehicles) => currentVehicles.filter((vehicle) => vehicle.id !== id))
  }

  return (
    <div className="planner-shell">
      <aside className="planner-sidebar" aria-label="Application navigation">
        <nav className="planner-nav" aria-label="QUASAR sections">
          <button type="button" className="planner-nav-item" onClick={onBack}>Overview</button>
          <button type="button" className="planner-nav-item is-active" aria-current="page">Route Planner</button>
          <button type="button" className="planner-nav-item" disabled>Initial Routing Results</button>
          <button type="button" className="planner-nav-item" disabled>Live Delivery and Routing</button>
          <button type="button" className="planner-nav-item" disabled>Routing Details Modal</button>
        </nav>
      </aside>

      <section className="workspace planner-workspace" aria-labelledby="route-planner-title">
        <div className="planner-intro">
          <div>
            <p className="eyebrow">Route setup</p>
            <h1 id="route-planner-title">Route Planner</h1>
            <p className="subtitle">Configure delivery orders, time windows, and fleet capacity before running the optimization.</p>
          </div>
        </div>

        <section className="planner-grid">
          <div className="planner-config-col">
            <article className="panel planner-panel">
              <div className="planner-panel-heading">
                <div>
                  <p className="section-label">Order data</p>
                  <h2>Delivery points</h2>
                </div>
                <PackageCheck size={17} />
              </div>
              <div className="planner-table planner-orders" role="table" aria-label="Order data">
                <div className="planner-table-head" role="row">
                  <span>Node</span><span>Address</span><span>Weight</span><span>Start</span><span>End</span><span aria-label="Actions" />
                </div>
                {orders.map((order) => (
                  <div className="planner-table-row" role="row" key={order.id}>
                    <strong>{order.id}</strong>
                    <select
                      aria-label={`${order.id} address`}
                      value={order.address || ""}
                      onChange={(event) => handleAddressChange(order.id, event.target.value)}
                    >
                      <option value="" disabled>Select address...</option>
                      {getAddressOptions(order.address).map((loc) => (
                        <option key={loc.name} value={loc.name}>
                          {loc.name}
                        </option>
                      ))}
                    </select>
                    <label>
                      <input aria-label={`${order.id} package weight`} type="number" min="0" value={order.weight} onChange={(event) => updateOrder(order.id, 'weight', event.target.value)} />
                      <span>kg</span>
                    </label>
                    <input aria-label={`${order.id} time-window start`} type="time" value={order.startTime} onChange={(event) => updateOrder(order.id, 'startTime', event.target.value)} />
                    <input aria-label={`${order.id} time-window end`} type="time" value={order.endTime} onChange={(event) => updateOrder(order.id, 'endTime', event.target.value)} />
                    <button type="button" className="row-remove" onClick={() => removeOrder(order.id)} aria-label={`Remove ${order.id}`}><Trash2 size={15} /></button>
                  </div>
                ))}
              </div>
              <div className="planner-panel-actions">
                <button type="button" className="settings-button" onClick={onAddDeliveryPoint}><Plus size={15} /> Add delivery point</button>
                <button type="button" className="settings-button"><Upload size={15} /> Import order CSV</button>
              </div>
            </article>

            <article className="panel planner-panel">
              <div className="planner-panel-heading">
                <div>
                  <p className="section-label">Fleet data</p><h2>Available vehicles</h2>
                </div>
                <Truck size={17} />
              </div>
              <div className="planner-table planner-vehicles" role="table" aria-label="Fleet data">
                <div className="planner-table-head" role="row"><span>Vehicle</span><span>Capacity</span><span aria-label="Actions" /></div>
                {vehicles.map((vehicle) => (
                  <div className="planner-table-row" role="row" key={vehicle.id}>
                    <input aria-label={`${vehicle.name} name`} value={vehicle.name} onChange={(event) => updateVehicle(vehicle.id, 'name', event.target.value)} />
                    <label>
                      <input aria-label={`${vehicle.name} capacity`} type="number" min="0" value={vehicle.capacity} onChange={(event) => updateVehicle(vehicle.id, 'capacity', event.target.value)} />
                      <span>kg</span>
                    </label>
                    <button type="button" className="row-remove" onClick={() => removeVehicle(vehicle.id)} aria-label={`Remove ${vehicle.name}`}><Trash2 size={15} /></button>
                  </div>
                ))}
              </div>
              <div className="planner-panel-actions">
                <button type="button" className="settings-button" onClick={addVehicle}><Plus size={15} /> Add vehicle</button>
                <button type="button" className="settings-button"><Upload size={15} /> Import vehicle CSV</button>
              </div>
            </article>
          </div>

          <article className="panel planner-panel planner-map-panel">
            <div className="planner-panel-heading">
              <div>
                <p className="section-label">Visual planning</p>
                <h2>Route setup map</h2>
              </div>
            </div>
            <div className="planner-map-wrapper">
              <LiveMap
                depot={depot}
                stops={stops}
                truckRoutes={[]}
                isLive={false}
                onMapClick={onMapClick}
              />
            </div>
          </article>
        </section>

        <section className="planner-presets panel" aria-labelledby="demo-preset-title">
          <div>
            <p className="section-label">Demo-ready data</p>
            <h2 id="demo-preset-title">Load a route scenario</h2>
            <p>Uses the bundled Pleiku geography; it replaces the current delivery points and fleet setup.</p>
          </div>
          <div className="planner-preset-actions">
            {demoPresets.map((preset) => (
              <button type="button" className="settings-button" key={preset.id} onClick={() => onApplyDemoPreset(preset.id)} disabled={isOptimizing}>
                <strong>{preset.label}</strong><span>{preset.detail}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="planner-summary" aria-label="Route planning summary">
          <span><b>{orders.length}</b> delivery points</span>
          <span><b>{vehicles.length}</b> vehicles</span>
          <span><b>{totalDemand} kg</b> total demand</span>
          <span><b>{totalCapacity} kg</b> total capacity</span>
        </section>

        <div className="planner-solver-bar">
          <label>
            Algorithm for this run
            <select
              value={solverId}
              onChange={(event) => onSolverChange(event.target.value)}
              aria-label="Algorithm for this run"
              disabled={isOptimizing}
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
          <p>{selectedSolver.description}</p>
        </div>

        <div className="planner-footer-actions">
          {optimizeError && <p className="optimize-warning planner-optimize-warning" role="alert">{optimizeError}</p>}
          <button type="button" className="settings-button" onClick={onBack}><ArrowLeft size={16} /> Back</button>
          <button type="button" className="route-action" onClick={onRunOptimization} disabled={isOptimizing}>
            {isOptimizing ? 'Optimizing routes...' : 'Run Optimization'}
          </button>
        </div>
      </section>
    </div>
  )
}

export default RoutePlanner
