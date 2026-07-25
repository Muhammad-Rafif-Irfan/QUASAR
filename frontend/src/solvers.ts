/** Solver catalog shown in Settings / Route Planner dropdowns. */

export type SolverKind = 'classical' | 'quantum' | 'hybrid'

export type SolverOption = {
  id: string
  label: string
  kind: SolverKind
  /** API algorithm keys sent to POST /api/v1/optimize */
  algorithms: string[]
  description: string
}

export const MAX_QAOA_STOPS = 3
export const MAX_CLASSICAL_DEMO_STOPS = 15

export const SOLVER_OPTIONS: SolverOption[] = [
  {
    id: 'nearest_neighbor',
    label: 'Nearest Neighbor (classical)',
    kind: 'classical',
    algorithms: ['nearest_neighbor'],
    description: 'Greedy TSP heuristic — fast baseline for comparison.',
  },
  {
    id: 'or_tools',
    label: 'OR-Tools Guided Local Search (classical)',
    kind: 'classical',
    algorithms: ['or_tools'],
    description: 'Google OR-Tools metaheuristic — production classical solver.',
  },
  {
    id: 'qaoa',
    label: `QAOA cost Hamiltonian (≤${MAX_QAOA_STOPS} stops)`,
    kind: 'quantum',
    algorithms: ['or_tools', 'qaoa'],
    description: `Verified small-instance QAOA: phase separator encodes actual route costs; limited to ${MAX_QAOA_STOPS} stops.`,
  },
  {
    id: 'compare_all',
    label: 'Compare verified solvers',
    kind: 'hybrid',
    algorithms: ['nearest_neighbor', 'or_tools', 'qaoa'],
    description: 'Compare classical baselines with the verified small-instance QAOA path.',
  },
]

export const DEFAULT_SOLVER_ID = 'compare_all'

export function getSolverOption(id: string): SolverOption {
  return SOLVER_OPTIONS.find((option) => option.id === id) ?? SOLVER_OPTIONS[SOLVER_OPTIONS.length - 1]
}
