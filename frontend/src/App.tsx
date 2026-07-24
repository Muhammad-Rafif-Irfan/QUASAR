import { useState, useCallback, type FormEvent } from 'react'
import { Map, Navigation, PackageCheck, Route, Settings, TriangleAlert, Truck, type LucideIcon } from 'lucide-react'
import InitialRoutingResults from './InitialRoutingResults'
import LiveDeliveryAndRouting from './LiveDeliveryAndRouting'
import RoutePlanner, { initialOrders, initialVehicles, type Order, type Vehicle } from './RoutePlanner'
import RoutingDetailsModal from './RoutingDetailsModal'
import { AddNewOrderModal, ChangeAddressModal, type NewOrderDraft } from './SupportingStates'
import { useRouteSimulation } from './useRouteSimulation'

type Screen = 'overview' | 'planner' | 'results' | 'live'

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

// Metric card data for the Operations Overview page.
const metrics: Metric[] = [
  { label: 'Vehicles Used', value: '3', unit: '/4', detail: 'of fleet deployed', emphasis: '75%', Icon: Truck, status: 'good' },
  { label: 'Packages Delivered', value: '22', unit: '/31', detail: 'completed today', emphasis: '71%', Icon: PackageCheck, status: 'good' },
  { label: 'Active Routes', value: '3', detail: 'currently monitored', emphasis: '3 live', Icon: Map, status: 'neutral' },
  { label: 'Operational Events', value: '6', detail: 'event listener connected', emphasis: '2 urgent', Icon: TriangleAlert, status: 'alert' },
]

// Recent activity mock data shown in the Operations Overview panel.
const recentActivities: Activity[] = [
  { time: '10:32', title: 'Truck T3 completed route', detail: 'Returned to depot · 2h 15m · 3 deliveries', kind: 'delivered' },
  { time: '10:18', title: 'New order N9 received', detail: '42 Nguyễn Tri Phương, Thanh Khê · 15 kg', kind: 'tracking' },
  { time: '09:45', title: '8 packages delivered', detail: 'Truck T1 completed morning batch · 1h 52m', kind: 'delivered' },
  { time: '09:12', title: 'Truck T2 heading to 233 Ngô Quyền', detail: 'ETA 12 min · carrying 62 kg', kind: 'tracking' },
  { time: '08:40', title: '13 packages delivered', detail: 'Truck T1 returned to depot · 3h 26m', kind: 'delivered' },
  { time: '08:17', title: 'Route recalculated', detail: 'Added N5 to Truck T2 · total distance +2.3 km', kind: 'tracking' },
]

const deliveryTrend = [42, 56, 51, 68, 62, 78, 73, 81, 76, 88, 85, 92, 89, 95]
const routeTrend = [28, 35, 31, 47, 42, 54, 50, 58, 53, 62, 59, 67, 64, 71]
const historicalRecords = [
  { period: 'Today', deliveries: '22 delivered', routes: '3 active routes' },
  { period: 'Wed, 23 Jul', deliveries: '28 delivered', routes: '3 completed routes' },
  { period: 'Tue, 22 Jul', deliveries: '24 delivered', routes: '3 completed routes' },
  { period: 'Mon, 21 Jul', deliveries: '19 delivered', routes: '2 completed routes' },
  { period: 'Sun, 20 Jul', deliveries: '16 delivered', routes: '2 completed routes' },
  { period: 'Sat, 19 Jul', deliveries: '11 delivered', routes: '1 completed route' },
]

type SettingsModalProps = {
  onSave: (event: FormEvent<HTMLFormElement>) => void
  onClose: () => void
}

function ApplicationHeader() {
  return <header className="topbar"><a className="brand" href="#overview" aria-label="Quasar home"><svg width="20" height="20" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="15" cy="15" r="9" stroke="currentColor" strokeWidth="2.2"/><path d="M21.5 21.5L27 27" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/><path d="M10.5 12.5C13.2 13.4 15.5 15.6 18.5 18.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/><circle cx="10" cy="12" r="1.6" fill="currentColor"/><circle cx="19" cy="19" r="1.6" fill="currentColor"/></svg><span>QUASAR</span></a><div className="topbar-meta"><span className="system-status">Connected</span><span>Tuesday, 14 May</span><button className="avatar" aria-label="Open profile">AK</button></div></header>
}

function SettingsModal({ onSave, onClose }: SettingsModalProps) {
  return <div className="modal-backdrop" role="presentation"><form className="settings-modal" aria-modal="true" aria-labelledby="settings-title" onSubmit={onSave}><div className="settings-modal__heading"><div><p className="section-label">Settings</p><h2 id="settings-title">Operational configuration</h2></div><button type="button" className="modal-close" onClick={onClose} aria-label="Close settings">&times;</button></div><p className="settings-copy">Update solver and backend preferences for the operations workspace.</p><div className="settings-fields"><label>Default solver<select defaultValue="QAOA+" aria-label="Default solver"><option>CLASSIC</option><option>QAOA</option><option>QAOA+</option><option>FALQON</option></select></label><label>Number of layers<input defaultValue="5" inputMode="numeric" /></label><label>Quantum backend<select defaultValue="AerSimulator" aria-label="Quantum backend"><option>AerSimulator</option><option>IBM QPU</option></select></label><label>Parameter alpha<input defaultValue="0.73" inputMode="decimal" /></label><label>Parameter beta<input defaultValue="0.27" inputMode="decimal" /></label></div><div className="settings-actions"><button type="submit" className="save-settings">Save Settings</button><button type="button" className="cancel-settings" onClick={onClose}>Cancel</button></div></form></div>
}

function OptimizationLoading() {
  return <div className="optimization-overlay" role="status" aria-live="polite"><div><Route size={20} /><strong>Optimizing routes...</strong><span>Preparing the mock routing result.</span></div></div>
}

// Screen 01 page component: Operations Overview.
function App() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Preserved planner data stays in App while the user visits Screen 03 and returns.
  const [orders, setOrders] = useState<Order[]>(initialOrders)
  const [vehicles, setVehicles] = useState<Vehicle[]>(initialVehicles)
  const [currentScreen, setCurrentScreen] = useState<Screen>('overview')
  const [isOptimizing, setIsOptimizing] = useState(false)
  const [routingDetailsOpen, setRoutingDetailsOpen] = useState(false)
  const [changeAddressOpen, setChangeAddressOpen] = useState(false)
  const [addNewOrderOpen, setAddNewOrderOpen] = useState(false)

  // Route simulation state — shared across Screen 03 and Screen 04
  const { depot, stops, truckRoutes, totalDistance, addStop, addStopAuto } = useRouteSimulation()

  // Track newly added stop IDs for distinct marker styling
  const [newStopIds, setNewStopIds] = useState<Set<string>>(new Set())

  // Page navigation remains simple local React state; no router is used.
  const handleStartRouting = () => {
    setCurrentScreen('planner')
  }

  const handleSaveSettings = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSettingsOpen(false)
  }

  // Loading simulation: wait one second before opening the same mock result.
  const runOptimization = () => {
    setIsOptimizing(true)
    window.setTimeout(() => {
      setIsOptimizing(false)
      setCurrentScreen('results')
    }, 1000)
  }

  const updateAffectedAddress = (address: string) => {
    setOrders((currentOrders) => currentOrders.map((order) => order.id === 'N4' ? { ...order, address } : order))
    setChangeAddressOpen(false)
  }

  const addLiveOrder = useCallback((draft: NewOrderDraft, shouldReRoute: boolean) => {
    const nextNode = Math.max(0, ...orders.map((order) => Number(order.id.replace('N', '')) || 0)) + 1
    const newId = `N${nextNode}`
    setOrders((currentOrders) => [...currentOrders, { id: newId, address: draft.address, weight: draft.weight, startTime: draft.startTime, endTime: draft.endTime }])

    // Also add the stop to the map simulation
    addStopAuto(newId, draft.address || undefined)
    setNewStopIds((prev) => new Set(prev).add(newId))

    setAddNewOrderOpen(false)
    if (shouldReRoute) runOptimization()
  }, [orders, addStopAuto])

  const handleMapClick = useCallback((latlng: { lat: number; lon: number }) => {
    const nextNode = Math.max(0, ...orders.map((order) => Number(order.id.replace('N', '')) || 0)) + 1
    const newId = `N${nextNode}`
    setOrders((currentOrders) => [...currentOrders, {
      id: newId,
      address: `Map pin (${latlng.lat.toFixed(4)}, ${latlng.lon.toFixed(4)})`,
      weight: '10',
      startTime: '09:00',
      endTime: '11:00',
    }])
    addStop(latlng.lat, latlng.lon, `Map Stop ${nextNode}`)
    setNewStopIds((prev) => new Set(prev).add(newId))
  }, [orders, addStop])

  return (
    <main className="app">
      <ApplicationHeader />

      {currentScreen === 'overview' && <>
        <section className="workspace" id="overview" aria-labelledby="page-title">
          <div className="page-intro"><div><p className="eyebrow">Operations center</p><h1 id="page-title">Operations Overview</h1><p className="subtitle">Monitor current deliveries, fleet capacity, and route status.</p></div><div className="page-actions"><button className="settings-button" onClick={() => setSettingsOpen(true)}><Settings size={16} /> Settings</button><button className="route-action" onClick={handleStartRouting}>Start Routing <Navigation size={16} /></button></div></div>
          <section className="metric-grid" aria-label="Today operations summary">{metrics.map(({ Icon, ...metric }) => <article className="metric" key={metric.label}><div className="metric-label"><Icon size={17} /><span>{metric.label}</span></div><strong>{metric.value}{metric.unit && <span>{metric.unit}</span>}</strong><small className={metric.status}><b>{metric.emphasis}</b> {metric.detail}</small></article>)}</section>
          <section className="main-grid"><article className="panel history-chart-card"><div className="panel-heading"><div><p className="section-label">Delivery performance</p><h2>Delivery activity over time</h2></div></div><div className="history-chart" role="img" aria-label="Seven-day chart of delivered packages and completed routes"><svg viewBox="0 0 700 230" preserveAspectRatio="none" aria-hidden="true"><line x1="24" y1="30" x2="676" y2="30" /><line x1="24" y1="90" x2="676" y2="90" /><line x1="24" y1="150" x2="676" y2="150" /><line x1="24" y1="210" x2="676" y2="210" /><polyline className="delivery-line" points={deliveryTrend.map((value, index) => `${34 + index * 104},${210 - value * 2.1}`).join(' ')} /><polyline className="routes-line" points={routeTrend.map((value, index) => `${34 + index * 104},${210 - value * 2.1}`).join(' ')} />{deliveryTrend.map((value, index) => <circle className="delivery-point" cx={34 + index * 104} cy={210 - value * 2.1} r="2.25" key={`delivery-${index}`} />)}{routeTrend.map((value, index) => <circle className="routes-point" cx={34 + index * 104} cy={210 - value * 2.1} r="2.25" key={`route-${index}`} />)}</svg><div className="chart-labels"><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Today</span></div></div><div className="chart-legend"><span><i className="delivery-key" /> Delivered packages</span><span><i className="routes-key" /> Completed routes</span></div></article><article className="panel historical-data-card"><div className="panel-heading"><div><p className="section-label">Historical data</p><h2>Delivery record</h2></div></div><div className="history-summary"><strong>94.8<span>%</span></strong><p>average on-time delivery</p></div><div className="history-records">{historicalRecords.map((record) => <div className="history-record" key={record.period}><span>{record.period}</span><div><b>{record.deliveries}</b><small>{record.routes}</small></div></div>)}</div></article></section>
          <section className="bottom-grid"><article className="panel activity-card"><div className="panel-heading"><div><p className="section-label">Recent activity</p><h2>Latest updates</h2></div><span className="listener-status"><i /> Live updates active</span></div>{recentActivities.map((activity) => <div className="activity-item" key={activity.time}><time>{activity.time}</time><span className={`activity-mark ${activity.kind}`}>{activity.kind === 'delivered' ? <PackageCheck size={15} /> : <Navigation size={15} />}</span><p><b>{activity.title}</b><small>{activity.detail}</small></p></div>)}</article></section>
        </section>
      </>}

      {currentScreen === 'planner' && <RoutePlanner orders={orders} setOrders={setOrders} vehicles={vehicles} setVehicles={setVehicles} isOptimizing={isOptimizing} onBack={() => setCurrentScreen('overview')} onOpenSettings={() => setSettingsOpen(true)} onRunOptimization={runOptimization} />}
      {currentScreen === 'results' && <InitialRoutingResults isOptimizing={isOptimizing} onEditSetup={() => setCurrentScreen('planner')} onReRoute={runOptimization} onStartOperational={() => setCurrentScreen('live')} depot={depot} stops={stops} truckRoutes={truckRoutes} totalDistance={totalDistance} />}
      {currentScreen === 'live' && <LiveDeliveryAndRouting onChangeAddress={() => setChangeAddressOpen(true)} onAddNewOrder={() => setAddNewOrderOpen(true)} onEndDelivery={() => setCurrentScreen('overview')} onViewLogDetails={() => setRoutingDetailsOpen(true)} depot={depot} stops={stops} truckRoutes={truckRoutes} totalDistance={totalDistance} onMapClick={handleMapClick} newStopIds={newStopIds} />}

      {isOptimizing && <OptimizationLoading />}
      {settingsOpen && <SettingsModal onSave={handleSaveSettings} onClose={() => setSettingsOpen(false)} />}
      {routingDetailsOpen && <RoutingDetailsModal onClose={() => setRoutingDetailsOpen(false)} />}
      {changeAddressOpen && <ChangeAddressModal onClose={() => setChangeAddressOpen(false)} onUpdate={updateAffectedAddress} />}
      {addNewOrderOpen && <AddNewOrderModal onClose={() => setAddNewOrderOpen(false)} onAdd={addLiveOrder} />}
    </main>
  )
}

export default App
