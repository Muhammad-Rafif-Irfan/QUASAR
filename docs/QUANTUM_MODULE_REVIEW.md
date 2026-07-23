# Experimental IBM SDVRP / CVRP modules

The package `research/ibm_sdvrp/` (`hamiltonian`, `ibm_connection`,
`ibm_qaoa`, `ibm_qaoa_plus`, `ibm_falqon`, `ibm_gas`, `gas_oracle`,
`validation`, smoke helpers) holds research modules from the
quantum-algorithm workstream. They are intentionally not wired into the
FastAPI production pipeline yet.

## Security

- Run hardware experiments only with `IBM_QUANTUM_TOKEN` set in the
  environment.
- Never put a token in source code, payload fixtures, logs, or commits.
- Any token previously shared in plaintext must be revoked and replaced.

## Current status

Validated locally / in unit tests:

- CVRP/SDVRP Hamiltonian with depot start/return, slack, and delivery bits
- Bitstring decode + feasibility checks
- Exhaustive 2–3 node CVRP enumeration (`tests/test_cvrp_enumeration.py`)
- True GAS energy-threshold oracle truth table (`tests/test_gas_oracle.py`)
- Stronger `parse_payload` validation including `max_circuit_depth`

Still research / demo constraints:

1. Keep live demo quantum scope to small CVRP; dynamic SDVRP stays classical.
2. GAS needs ancilla qubits beyond laptop Aer capacity — keep it out of live
   demo and mark smoke as skipped.
3. QAOA+ W-state + XY mixer is improved but still a heuristic ansatz; do not
   claim hard feasibility preservation for every constraint.
4. Do not accept IBM credentials in API request payloads for production.
5. Pin tested `qiskit` / `qiskit-ibm-runtime` versions before deployment.
6. Wire runners behind a feature flag only after Aer smoke asserts
   `valid is True` on the target CVRP fixture.

## Acceptance criteria before backend claims

- Agree on one demo model first: CVRP (quantum) vs dynamic SDVRP (classical).
- Keep exhaustive energy/decoder tests green in CI.
- Report qubit count, depth, feasibility rate, route cost, and OR-Tools
  baseline for any pitch slide.
- Prefer simulator live + pre-recorded QPU evidence over live IBM queues.
