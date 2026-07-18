# Experimental IBM SDVRP modules

The files `hamiltonian.py`, `ibm_connection.py`, `ibm_qaoa.py`,
`ibm_qaoa_plus.py`, `ibm_falqon.py`, and `ibm_gas.py` are a research
submission from the quantum-algorithm workstream. They are intentionally not
wired into the FastAPI production pipeline yet.

## Security

- Run hardware experiments only with `IBM_QUANTUM_TOKEN` set in the
  environment.
- Never put a token in source code, payload fixtures, logs, or commits.
- Any token previously shared in plaintext must be revoked and replaced.

## Correctness blockers

These items must be resolved and covered by exhaustive small-instance tests
before the modules can produce benchmark claims:

1. `starting_nodes` is parsed but not encoded in the Hamiltonian. Depot start,
   depot return, and vehicle-specific route constraints are therefore absent.
2. The current binary variables only represent visits. They do not represent
   delivered quantity, so the formulation cannot model split delivery as
   documented.
3. The linear "at least once" node term rewards repeated visits rather than
   penalizing them. The capacity term enforces equality instead of an
   inequality with slack variables.
4. Squared binary terms are passed through the pair-product helper with the
   same qubit twice, and capacity cross terms can be counted more than once.
5. Manual Pauli-term circuits must consistently translate Qiskit's
   big-endian Pauli labels to qubit indices and measured bitstrings.
6. The GAS circuit does not implement an energy-threshold oracle. Filtering
   Hamiltonian terms by coefficient is not equivalent to marking basis states
   whose total objective value is below the threshold.
7. QAOA+ starts from `|+>` and its partial XY mixer does not preserve all
   position and visit constraints claimed by the module.
8. Results return only a bitstring. Route decoding, constraint validation,
   objective recomputation, and best-feasible-sample selection are required.
9. FALQON applies an observable layout obtained from a dummy circuit instead
   of the transpiled circuit being evaluated. QAOA runners also transpile once
   for a layout and then transpile each bound circuit again.

## Runtime integration safeguards

- Do not accept IBM credentials in API request payloads. Read them only from
  the deployment secret environment.
- Pin a tested `qiskit`/`qiskit-ibm-runtime` version pair before CI or
  deployment.
- Move these root modules into an importable package before backend use.
- Add backend allowlisting and verify operational status, simulator policy,
  qubit capacity, and the intended IBM instance/CRN.
- Enforce server-side limits for qubits, shots, layers, optimizer evaluations,
  total submitted jobs, and estimated budget.
- Add timeout, cancellation, retry, and persisted job-state handling around
  every `job.result()` call.
- Use a Runtime session or batch where appropriate; one remote job per COBYLA
  evaluation and many jobs per FALQON layer can otherwise cause long queues
  and uncontrolled cost.
- Keep hardware tests manual. CI must use local or mocked primitives and scan
  these modules for lint, security issues, and leaked secrets.

## Acceptance criteria

- Agree on one model first: TSP, CVRP, or SDVRP.
- Define one canonical `x[i,t,v]`/bitstring ordering and route decoder.
- Compare every basis-state energy against a direct classical objective for
  two-node and three-node fixtures.
- Verify the exact optimum and all feasibility constraints by exhaustive
  enumeration before using Aer or IBM hardware.
- Run local noisy/noiseless simulation before submitting QPU jobs.
- Report qubit count, circuit depth after transpilation, two-qubit gate count,
  queue time, QPU time, feasibility rate, route cost, and classical baseline.

Until these criteria pass, the modules are suitable for collaborative
research only, not backend integration or performance claims.
