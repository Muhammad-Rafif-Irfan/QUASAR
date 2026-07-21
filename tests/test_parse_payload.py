"""Unit tests for ibm_connection.parse_payload."""

import unittest

from ibm_connection import parse_payload


class ParsePayloadTests(unittest.TestCase):
    def test_accepts_minimal_valid_payload(self):
        parsed = parse_payload({
            "matrix": [[0, 10], [10, 0]],
            "demands": [0, 1],
            "capacities": [2],
            "starting_nodes": [0],
        })
        self.assertEqual(parsed["n_nodes"], 2)
        self.assertEqual(parsed["n_vehicles"], 1)
        self.assertIn("max_circuit_depth", parsed)
        self.assertIn("max_energy_scale", parsed)
        self.assertFalse(parsed["demand_priority"])

    def test_rejects_non_boolean_demand_priority(self):
        with self.assertRaises(ValueError):
            parse_payload({
                "matrix": [[0, 10], [10, 0]],
                "demands": [0, 1],
                "capacities": [2],
                "starting_nodes": [0],
                "demand_priority": 10.0,
            })

    def test_rejects_mismatched_starting_nodes(self):
        with self.assertRaises(ValueError):
            parse_payload({
                "matrix": [[0, 10], [10, 0]],
                "demands": [0, 1],
                "capacities": [1, 1],
                "starting_nodes": [0],
            })


if __name__ == "__main__":
    unittest.main()
