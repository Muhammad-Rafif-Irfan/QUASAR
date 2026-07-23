# QUASAR
## Source of truth

- Team wireframe: quasar-dashboard-wireframe.excalidraw
- SVG preview: quasar-dashboard-wireframe.svg
- User interaction explanation: user-flow.md

The Excalidraw file in this workspace is copied directly from the team's final quasar-draft2.excalidraw. The Markdown files explain the intended interaction behavior; they do not replace the editable canvas.

## Scope

This is a low-fidelity grayscale wireframe for the Dynamic SDVRP dashboard. It documents the user-facing screens, operational states, button destinations, and the hybrid classical-quantum routing flow. It is not React code and does not implement live data or click handlers.

## Numbered screens

| Screen | Role | Required content |
| --- | --- | --- |
| 01. Operations Overview | Entry point and fleet summary | QUASAR title, Start Routing, vehicle usage, delivered packages, history, live map, active events, listener status, recent activities |
| 02. Route Planner | Configure an initial or updated route | User Input A order data, User Input B fleet data, vehicle loads, delivery points, Import vehicle CSV, event triggers, Start Operational |
| 03. Initial Routing Results | Explain the optimization pipeline | Parser/event listener, coordinates, weights, time windows, data per window, cost matrix, start optimization, vehicle count, route sequencing, load distribution, OR-Tools warm start, QUBO/HOBO, FALCON |
| 04. Live Delivery and Routing | Show the operational result | Live route map, moving vehicles, split delivery, overflow resolution, result tabs, Core 1/Core 2, virtual-node stitching, Dijkstra/A*, optimized routes output, updated matrix/routes, Change Address, View log details |
| 05. Routing Details Modal | Provide judge-facing execution evidence | Algorithm, backend, core, iterations, execution time, validity, objective value, updated nodes |

## Unnumbered supporting UI states

The following boxes are placed below the numbered screens and are not part of the 01-05 sequence:

### Settings

- Opened by the Settings button.
- Fields shown in the final draft: Parameter Beta 0.27, Number of layer 5, Default Solver QAOA+, Quantum Backend AerSimulator / IBM QPU, Parameter Alpha 0.73.
- **Save Settings** returns to the live dashboard with the selected configuration.
- **Cancel** closes the state without applying changes.

### Change Address

- Opened by Change Address.
- Captures current address, new address, reason, affected node, and time window.
- **Update Address** recalculates coordinates and the affected cost-matrix region.
- **Cancel** closes the form. Re-Route is initiated from the main routing state after the update is confirmed.

### Add New Order

- Opened by Add new order or Add Emergency Order.
- Captures customer address, package weight, time window, priority, and vehicle assignment.
- **Add Order** inserts the order into the event queue.
- **Add + Re-Route** inserts the order and starts partial re-optimization.

## Button-to-screen contract

The frontend implementation should use the following destinations:

- Start Routing -> Route Planner.
- Start Operational -> Live Delivery and Routing.
- Edit Setup -> Route Planner.
- Re-Route -> Initial Routing Results -> Live Delivery and Routing.
- Add new order/Add Emergency Order -> Add New Order -> Event listener.
- Change Address -> Change Address -> coordinate/cost-matrix update.
- Road Newly Inaccessible/Road Closure -> Initial Routing Results.
- Settings -> Settings -> Save/Cancel.
- View log details/View Quantum Details -> Routing Details Modal.
- Import order CSV and + Add delivery point -> Route Planner.
- Next 5-minute cycle -> refresh the live delivery state.

## Diagram alignment

The wireframe represents the team diagram in this order:

1. Order data and fleet data enter the system.
2. Parser and event listener prepare coordinates, weights, time windows, and data per window.
3. The cost matrix feeds Start Optimization.
4. Vehicle count, route sequencing, and load distribution are solved with an OR-Tools warm start.
5. The problem is encoded as QUBO/HOBO and sent to FALCON through the selected backend.
6. The system produces optimized routes, including split delivery and dynamic knapsack overflow handling.
7. New orders, address changes, and road events update affected nodes only.
8. Updated matrix/routes are broadcast to vehicles and refreshed on the next five-minute cycle.

## Handoff notes

- Keep the final screen names and button labels from the team draft unless the team explicitly changes them.
- Treat the supporting states as modal/route states, not additional numbered screens.
- Keep the split-delivery explanation visible in the live result so judges can see why the route changed.
- The arrows in Excalidraw describe intended navigation; they are not executable interactions until the frontend is implemented.
