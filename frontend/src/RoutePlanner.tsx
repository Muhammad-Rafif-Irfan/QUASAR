import type { Dispatch, SetStateAction } from 'react'
import { ArrowLeft, Database, PackageCheck, Plus, Settings, Trash2, Truck, Upload } from 'lucide-react'
import { DATASETS } from './datasets'

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
  onBack: () => void
  onOpenSettings: () => void
  onRunOptimization: () => void
  activeDataset: string
  onDatasetChange: (key: string) => void
}

// Initial mock data is owned by App so it survives navigation to Screen 03.
export const initialOrders: Order[] = DATASETS[0].orders
export const initialVehicles: Vehicle[] = [
  { id: 'truck-1', name: 'Truck 1', capacity: '250' },
  { id: 'truck-2', name: 'Truck 2', capacity: '300' },
  { id: 'truck-3', name: 'Truck 3', capacity: '200' },
]

function RoutePlanner({ orders, setOrders, vehicles, setVehicles, isOptimizing, onBack, onOpenSettings, onRunOptimization, activeDataset, onDatasetChange }: RoutePlannerProps) {
  const totalDemand = orders.reduce((total, order) => total + (Number(order.weight) || 0), 0)
  const totalCapacity = vehicles.reduce((total, vehicle) => total + (Number(vehicle.capacity) || 0), 0)

  const currentDatasetInfo = DATASETS.find((d) => d.key === activeDataset)

  const updateOrder = (id: string, field: keyof Order, value: string) => {
    setOrders((currentOrders) => currentOrders.map((order) => order.id === id ? { ...order, [field]: value } : order))
  }

  const addDeliveryPoint = () => {
    const nextNode = Math.max(0, ...orders.map((order) => Number(order.id.replace(/[^0-9]/g, '')) || 0)) + 1
    const prefix = activeDataset === 'demo' ? 'N' : 'R'
    setOrders((currentOrders) => [...currentOrders, { id: `${prefix}${nextNode}`, address: '', weight: '', startTime: '09:00', endTime: '10:00' }])
  }

  const removeOrder = (id: string) => {
    setOrders((currentOrders) => currentOrders.filter((order) => order.id !== id))
  }

  const updateVehicle = (id: string, field: keyof Vehicle, value: string) => {
    setVehicles((currentVehicles) => currentVehicles.map((vehicle) => vehicle.id === id ? { ...vehicle, [field]: value } : vehicle))
  }

  const addVehicle = () => {
    const nextVehicle = vehicles.length + 1
    setVehicles((currentVehicles) => [...currentVehicles, { id: `truck-${Date.now()}`, name: `Truck ${nextVehicle}`, capacity: '' }])
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
        <div className="planner-sidebar-footer"><button type="button" className="planner-nav-item planner-settings-link" onClick={onOpenSettings}><Settings size={15} /> Settings</button></div>
      </aside>

      <section className="workspace planner-workspace" aria-labelledby="route-planner-title">
        <div className="planner-intro">
          <div><p className="eyebrow">Route setup</p><h1 id="route-planner-title">Route Planner</h1><p className="subtitle">Configure delivery orders, time windows, and fleet capacity before running the optimization.</p></div>
        </div>

        {/* Dataset Selector */}
        <div className="dataset-selector">
          <div className="dataset-selector__label"><Database size={15} /><span>Dataset</span></div>
          <div className="dataset-selector__options">
            {DATASETS.map((ds) => (
              <button
                key={ds.key}
                type="button"
                className={`dataset-option ${activeDataset === ds.key ? 'dataset-option--active' : ''}`}
                onClick={() => onDatasetChange(ds.key)}
              >
                <strong>{ds.label}</strong>
                <small>{ds.description}</small>
              </button>
            ))}
          </div>
          {currentDatasetInfo && (
            <p className="dataset-source">Source: {currentDatasetInfo.source}</p>
          )}
        </div>

        <section className="planner-grid">
          <article className="panel planner-panel">
            <div className="planner-panel-heading"><div><p className="section-label">Order data</p><h2>Delivery points</h2></div><PackageCheck size={17} /></div>
            <div className="planner-table planner-orders" role="table" aria-label="Order data">
              <div className="planner-table-head" role="row"><span>Node</span><span>Address</span><span>Weight</span><span>Start</span><span>End</span><span aria-label="Actions" /></div>
              {orders.map((order) => <div className="planner-table-row" role="row" key={order.id}><strong>{order.id}</strong><input aria-label={`${order.id} address`} placeholder="Address / location" value={order.address} onChange={(event) => updateOrder(order.id, 'address', event.target.value)} /><label><input aria-label={`${order.id} package weight`} type="number" min="0" value={order.weight} onChange={(event) => updateOrder(order.id, 'weight', event.target.value)} /><span>kg</span></label><input aria-label={`${order.id} time-window start`} type="time" value={order.startTime} onChange={(event) => updateOrder(order.id, 'startTime', event.target.value)} /><input aria-label={`${order.id} time-window end`} type="time" value={order.endTime} onChange={(event) => updateOrder(order.id, 'endTime', event.target.value)} /><button type="button" className="row-remove" onClick={() => removeOrder(order.id)} aria-label={`Remove ${order.id}`}><Trash2 size={15} /></button></div>)}
            </div>
            <div className="planner-panel-actions"><button type="button" className="settings-button" onClick={addDeliveryPoint}><Plus size={15} /> Add delivery point</button><button type="button" className="settings-button"><Upload size={15} /> Import order CSV</button></div>
          </article>

          <article className="panel planner-panel">
            <div className="planner-panel-heading"><div><p className="section-label">Fleet data</p><h2>Available vehicles</h2></div><Truck size={17} /></div>
            <div className="planner-table planner-vehicles" role="table" aria-label="Fleet data">
              <div className="planner-table-head" role="row"><span>Vehicle</span><span>Capacity</span><span aria-label="Actions" /></div>
              {vehicles.map((vehicle) => <div className="planner-table-row" role="row" key={vehicle.id}><input aria-label={`${vehicle.name} name`} value={vehicle.name} onChange={(event) => updateVehicle(vehicle.id, 'name', event.target.value)} /><label><input aria-label={`${vehicle.name} capacity`} type="number" min="0" value={vehicle.capacity} onChange={(event) => updateVehicle(vehicle.id, 'capacity', event.target.value)} /><span>kg</span></label><button type="button" className="row-remove" onClick={() => removeVehicle(vehicle.id)} aria-label={`Remove ${vehicle.name}`}><Trash2 size={15} /></button></div>)}
            </div>
            <div className="planner-panel-actions"><button type="button" className="settings-button" onClick={addVehicle}><Plus size={15} /> Add vehicle</button><button type="button" className="settings-button"><Upload size={15} /> Import vehicle CSV</button></div>
          </article>
        </section>

        <section className="planner-summary" aria-label="Route planning summary"><span><b>{orders.length}</b> delivery points</span><span><b>{vehicles.length}</b> vehicles</span><span><b>{totalDemand} kg</b> total demand</span><span><b>{totalCapacity} kg</b> total capacity</span></section>

        <div className="planner-footer-actions"><button type="button" className="settings-button" onClick={onBack}><ArrowLeft size={16} /> Back</button><button type="button" className="route-action" onClick={onRunOptimization} disabled={isOptimizing}>{isOptimizing ? 'Optimizing routes...' : 'Run Optimization'}</button></div>
      </section>
    </div>
  )
}

export default RoutePlanner
