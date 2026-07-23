# QUASAR

## Purpose

This document explains how a user moves through the final team wireframe. The Excalidraw file is the visual source of truth; this file explains what each button is intended to do when the frontend is implemented.

## Main numbered flow

1. **01. Operations Overview**
   - The user sees live fleet status, vehicle usage, packages delivered, recent activities, and active event/listener status.
   - Click **Start Routing** to open the initial routing setup.

2. **02. Route Planner**
   - The user edits User Input A (order data) and User Input B (fleet data), reviews vehicle loads, imports data, and adds delivery points.
   - Click **Start Operational** to begin the live delivery/routing state.

3. **03. Initial Routing Results**
   - The system shows parsing, coordinates, weights, time windows, cost matrix, the three subproblems, OR-Tools warm start, QUBO/HOBO encoding, and FALCON quantum optimization.
   - This screen explains how the route is produced and re-optimized.

4. **04. Live Delivery and Routing**
   - The user monitors moving vehicles, baseline versus updated routes, split delivery, capacity overflow, affected nodes, and route broadcast.
   - Click **Re-Route** when a route needs to be recalculated.
   - Click **View log details** or **View Quantum Details** to inspect the execution evidence.

5. **05. Routing Details Modal**
   - The user inspects the algorithm, backend, core, iterations, execution time, validity, objective value, and updated nodes.

## Button behavior

| Button | What happens after the click | Resulting state |
| --- | --- | --- |
| **Start Routing** | Loads the initial order and fleet setup. | Route Planner |
| **Start Operational** | Starts live delivery monitoring and the five-minute event cycle. | Live Delivery and Routing |
| **Edit Setup** | Returns to editable User Input A/B. | Route Planner |
| **Re-Route** | Runs the optimization pipeline again for affected nodes. | Initial Routing Results, then updated live route |
| **Add new order** | Opens the new-order form and inserts a delivery node into the event listener. | Add New Order supporting state |
| **Add Emergency Order** | Opens the new-order form with an urgent-event context. | Add New Order supporting state |
| **Change Address** | Opens the address form and prepares a coordinate/cost-matrix update. | Change Address supporting state |
| **Road Newly Inaccessible** / **Road Closure** | Applies a road event and starts partial re-routing. | Initial Routing Results |
| **Settings** | Opens operational and quantum configuration. | Settings supporting state |
| **Import order CSV** | Reloads the order dataset. | Route Planner |
| **+ Add delivery point** | Adds a new delivery node to the order data. | Route Planner |
| **Add Order** | Saves the new order without immediately starting a reroute. | Route Planner / event queue |
| **Add + Re-Route** | Saves the new order and sends it through partial re-optimization. | Initial Routing Results |
| **Update Address** | Saves the new address and recalculates the affected coordinates/matrix. | Change Address -> route update |
| **Cancel** | Closes the current supporting state without applying the change. | Previous screen |
| **Save Settings** | Applies the selected settings and returns to the live UI. | Live Delivery and Routing |
| **View log details** / **View Quantum Details** | Opens execution evidence. | Routing Details Modal |
| **Next 5-minute cycle** | Refreshes truck positions, live status, event data, and updated routes. | Live Delivery and Routing |

## Supporting states below the numbered screens

These are intentionally not numbered 06, 07, or 08. They are temporary/supporting UI states opened from buttons in the main flow.

- **Settings:** Parameter Beta 0.27, Number of layer 5, Default Solver QAOA+, Quantum Backend AerSimulator / IBM QPU, and Parameter Alpha 0.73. **Save Settings** applies the configuration; **Cancel** closes it.
- **Change Address:** current address, new address, reason, affected node, and time window. **Update Address** applies the change; **Cancel** closes it. **Re-Route** is then available from the main routing state.
- **Add New Order:** customer address, package weight, time window, priority, and vehicle assignment. **Add Order** queues it; **Add + Re-Route** queues it and starts a partial route update.

## Dynamic rule

New orders, address changes, and road events should update the affected part of the route rather than rebuild the entire route unnecessarily. The updated matrix/routes are broadcast to vehicles and become the input for the next five-minute cycle.
