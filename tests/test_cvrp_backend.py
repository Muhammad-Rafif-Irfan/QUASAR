"""Focused tests for the production OR-Tools multi-vehicle CVRP path."""

import unittest

import numpy as np

from app.services.quantum_driver import solve_or_tools_cvrp


class CvrpBackendTests(unittest.TestCase):
    def test_routes_serve_every_stop_once_without_exceeding_capacity(self):
        # depot + four deliveries; values are meters and deliberately asymmetric
        matrix = np.array([
            [0, 4, 8, 7, 3],
            [4, 0, 5, 6, 7],
            [8, 5, 0, 3, 6],
            [7, 6, 3, 0, 5],
            [3, 7, 6, 5, 0],
        ])
        routes, distance, elapsed_ms = solve_or_tools_cvrp(
            matrix,
            demands=[0, 4, 6, 3, 5],
            vehicles=[
                {"id": "truck-a", "name": "Truck A", "capacity": 10},
                {"id": "truck-b", "name": "Truck B", "capacity": 10},
            ],
        )

        self.assertGreater(distance, 0)
        self.assertGreaterEqual(elapsed_ms, 0)
        served = [node for route in routes for node in route["route"] if node != 0]
        self.assertEqual(sorted(served), [1, 2, 3, 4])
        for route in routes:
            self.assertEqual(route["route"][0], 0)
            self.assertEqual(route["route"][-1], 0)
            self.assertLessEqual(route["load"], route["capacity"])

