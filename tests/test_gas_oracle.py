"""Deterministic reference tests for the GAS energy-threshold oracle."""

import unittest

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import SparsePauliOp, Statevector

from core.gas_oracle import (
    ThresholdOracleError,
    build_threshold_oracle,
    evaluate_ising_energy,
)


class GasThresholdOracleTests(unittest.TestCase):
    def setUp(self):
        # H = Z_1 + 2 Z_0 + 0.5 Z_1 Z_0
        # Energies in Qiskit big-endian bitstring order:
        # 00 ->  3.5, 01 -> -1.5, 10 -> 0.5, 11 -> -2.5.
        self.operator = SparsePauliOp.from_list([
            ("ZI", 1.0),
            ("IZ", 2.0),
            ("ZZ", 0.5),
        ])

    def _phase_for(self, oracle, bitstring: str) -> complex:
        circuit = QuantumCircuit(oracle.circuit.num_qubits)
        for qubit, bit in enumerate(reversed(bitstring)):
            if bit == "1":
                circuit.x(qubit)
        circuit.compose(oracle.circuit, inplace=True)
        state = Statevector.from_instruction(circuit)

        basis_index = int(bitstring, 2)
        self.assertAlmostEqual(float(abs(state.data[basis_index]) ** 2), 1.0, places=12)
        self.assertAlmostEqual(float(np.sum(np.abs(state.data) ** 2)), 1.0, places=12)
        return state.data[basis_index]

    def test_energy_matches_expected_big_endian_values(self):
        expected = {"00": 3.5, "01": -1.5, "10": 0.5, "11": -2.5}
        for bitstring, energy in expected.items():
            self.assertAlmostEqual(evaluate_ising_energy(self.operator, bitstring), energy)

    def test_oracle_flips_only_states_below_threshold(self):
        oracle = build_threshold_oracle(self.operator, threshold=0.0, energy_scale=1)
        reference = self._phase_for(oracle, "00")

        for bitstring in ("00", "10"):
            self.assertAlmostEqual((self._phase_for(oracle, bitstring) / reference).real, 1.0, places=12)
        for bitstring in ("01", "11"):
            self.assertAlmostEqual((self._phase_for(oracle, bitstring) / reference).real, -1.0, places=12)

    def test_non_discriminating_threshold_is_rejected(self):
        with self.assertRaises(ThresholdOracleError):
            build_threshold_oracle(self.operator, threshold=-10.0, energy_scale=1)
        with self.assertRaises(ThresholdOracleError):
            build_threshold_oracle(self.operator, threshold=10.0, energy_scale=1)

    def test_negative_quadratic_term_keeps_its_truth_table(self):
        # This exercises the signed-QUBO rewrite used by the reversible
        # accumulator: -Z_1 Z_0 marks equal bits below threshold zero.
        operator = SparsePauliOp.from_list([("ZZ", -1.0)])
        oracle = build_threshold_oracle(operator, threshold=0.0, energy_scale=1)
        reference = self._phase_for(oracle, "01")

        for bitstring in ("01", "10"):
            self.assertAlmostEqual((self._phase_for(oracle, bitstring) / reference).real, 1.0, places=12)
        for bitstring in ("00", "11"):
            self.assertAlmostEqual((self._phase_for(oracle, bitstring) / reference).real, -1.0, places=12)


if __name__ == "__main__":
    unittest.main()
