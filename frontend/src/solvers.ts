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
    label: 'QUBO + QAOA (quantum)',
    kind: 'quantum',
    algorithms: ['or_tools', 'qaoa'],
    description: 'Quantum QAOA with OR-Tools baseline for approximation ratio.',
  },
  {
    id: 'qai_hobo',
    label: 'QAI + HOBO (quantum)',
    kind: 'quantum',
    algorithms: ['or_tools', 'qai_hobo'],
    description: 'Quantum annealing-inspired HOBO with classical warm-start.',
  },
  {
    id: 'compare_all',
    label: 'Compare all (classical + quantum)',
    kind: 'hybrid',
    algorithms: ['nearest_neighbor', 'or_tools', 'qaoa', 'qai_hobo'],
    description: 'Run every solver and compare distance / time side by side.',
  },
]

export const DEFAULT_SOLVER_ID = 'compare_all'

export function getSolverOption(id: string): SolverOption {
  return SOLVER_OPTIONS.find((option) => option.id === id) ?? SOLVER_OPTIONS[SOLVER_OPTIONS.length - 1]
}
