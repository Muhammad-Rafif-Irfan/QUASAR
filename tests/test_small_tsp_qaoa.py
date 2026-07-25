"""Regression tests for the bounded, cost-Hamiltonian QAOA encoding."""

import unittest

import numpy as np
from qiskit.primitives import StatevectorSampler

from core.small_tsp_qaoa import (
    best_feasible_sample,
    build_qaoa_circuit,
    cost_spectrum,
    expectation_from_counts,
    required_qubits,
)


class SmallTspQaoaTests(unittest.TestCase):
    def setUp(self):
        self.matrix = np.array([
            [0, 10, 15, 20],
            [10, 0, 35, 25],
            [15, 35, 0, 30],
            [20, 25, 30, 0],
        ])

    def test_cost_spectrum_matches_explicit_feasible_tours(self):
        tours, costs = cost_spectrum(self.matrix)
        self.assertEqual(required_qubits(4), 3)
        self.assertEqual(len(tours), 6)
        self.assertEqual(len(costs), 8)
        self.assertEqual(min(costs[:6]), 80.0)
        self.assertGreater(costs[6], max(costs[:6]))
        self.assertGreater(costs[7], max(costs[:6]))

    def test_sampled_circuit_uses_only_the_encoded_cost_spectrum(self):
        tours, costs = cost_spectrum(self.matrix)
        circuit = build_qaoa_circuit(costs, gamma=0.02, beta=0.4)
        result = StatevectorSampler(default_shots=256, seed=7).run([circuit]).result()
        counts = result[0].data.meas.get_counts()
        expected = expectation_from_counts(counts, costs)
        tour, distance, probability = best_feasible_sample(counts, tours, costs)

        self.assertGreaterEqual(expected, min(costs))
        self.assertLessEqual(expected, max(costs))
        self.assertEqual(tour[0], 0)
        self.assertEqual(tour[-1], 0)
        self.assertIn(distance, costs[:len(tours)])
        self.assertGreater(probability, 0.0)


if __name__ == "__main__":
    unittest.main()
