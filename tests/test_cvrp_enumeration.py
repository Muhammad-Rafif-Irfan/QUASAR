"""Exhaustive CVRP reference cases for the routing Hamiltonian.

These tests deliberately use only tiny instances.  Enumerating every
bitstring gives CI an independent ground truth for the encoding, decoder, and
energy evaluator without making any claim that production GAS enumerates its
search space.
"""

import unittest

import numpy as np

from core.gas_oracle import evaluate_ising_energy
from hamiltonian import build_ising, decode_bitstring


def _feasible_states(matrix: np.ndarray, demands: np.ndarray, capacity: float):
    """Return all feasible states and energies for a deliberately tiny CVRP."""
    n_nodes = len(demands)
    ising = build_ising(
        matrix,
        demands,
        np.array([capacity]),
        n_nodes,
        1,
        [0],
        alpha=1.0,
        beta=0.5,
        lambda_scale=10.0,
        demand_priority=False,
    )
    feasible = []
    for value in range(1 << ising.num_qubits):
        bitstring = format(value, f"0{ising.num_qubits}b")
        decoded = decode_bitstring(
            bitstring, n_nodes, 1, [0], demands, np.array([capacity])
        )
        if decoded["valid"]:
            feasible.append((
                evaluate_ising_energy(ising, bitstring),
                bitstring,
                decoded["routes"],
            ))
    return ising, feasible


class CvrpEnumerationSmokeTests(unittest.TestCase):
    def test_two_node_cvrp_has_one_known_feasible_route(self):
        matrix = np.array([[0.0, 10.0], [10.0, 0.0]])
        demands = np.array([0.0, 3.0])

        ising, feasible = _feasible_states(matrix, demands, capacity=5.0)

        self.assertEqual(ising.num_qubits, 9)
        self.assertEqual(len(feasible), 1)
        energy, _, routes = feasible[0]
        self.assertEqual(routes, {"0": [0, 1, 0]})
        self.assertAlmostEqual(energy, 34.5)

    def test_three_node_cvrp_has_the_two_expected_orderings(self):
        matrix = np.array([
            [0.0, 4.0, 7.0],
            [4.0, 0.0, 3.0],
            [7.0, 3.0, 0.0],
        ])
        demands = np.array([0.0, 2.0, 3.0])

        ising, feasible = _feasible_states(matrix, demands, capacity=5.0)

        self.assertEqual(ising.num_qubits, 15)
        self.assertEqual(len(feasible), 2)
        self.assertEqual({tuple(routes["0"]) for _, _, routes in feasible}, {
            (0, 1, 2, 0),
            (0, 2, 1, 0),
        })
        self.assertTrue(all(abs(energy - 33.0) < 1e-9 for energy, _, _ in feasible))


if __name__ == "__main__":
    unittest.main()
