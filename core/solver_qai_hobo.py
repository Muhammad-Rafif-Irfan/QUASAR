import time
import uuid
import numpy as np
from qiskit import QuantumCircuit
from core.base_solver import BaseQuantumSolver


class QaiHoboSolver(BaseQuantumSolver):
    def __init__(self, distance_matrix, sampler, pass_manager=None, is_simulator=False, job_callback=None, backend_name=None):
        """
        Core QAI+HOBO solver used by the FastAPI optimization pipeline.

        job_callback(event, payload) is optional — backend uses it to write QuantumJob rows.
        Events: "job_start" | "job_complete" | "job_failed"
        """
        super().__init__(distance_matrix)
        self.sampler = sampler
        self.pm = pass_manager
        self.is_simulator = is_simulator
        self.job_callback = job_callback
        self.backend_name = backend_name or (
            "Local Statevector Simulator" if is_simulator else "IBM Quantum"
        )
        self.B = max(1, int(np.ceil(np.log2(self.num_nodes))))

    def hobo_decode(self, bitstring):
        """HOBO decoder to convert a bitstring into a route sequence."""
        bits = list(reversed(bitstring))
        pos = {
            c: sum(
                int(bits[c * self.B + b]) * (2 ** b)
                for b in range(self.B)
                if c * self.B + b < len(bits)
            )
            % self.num_nodes
            for c in range(self.num_nodes)
        }

        ordered = [None] * self.num_nodes
        for c, p in sorted(pos.items(), key=lambda item: item[1]):
            if ordered[p] is None:
                ordered[p] = c
            else:
                empty = [i for i in range(self.num_nodes) if ordered[i] is None]
                if empty:
                    ordered[empty[0]] = c

        ordered = [c for c in ordered if c is not None]
        if 0 in ordered:
            ordered.remove(0)

        return [0] + ordered + [0]

    def build_qai_circuit(self, temp, warm_start_route):
        """Circuit builder using a dynamic warm_start_route parameter."""
        qc = QuantumCircuit(self.num_nodes * self.B)
        qc.h(range(self.num_nodes * self.B))

        if warm_start_route:
            for seq, city in enumerate(warm_start_route[:-1]):
                pos_ratio = seq / max(self.num_nodes - 1, 1)
                for b in range(self.B):
                    qc.rz(pos_ratio * np.pi * (b + 1) / self.B, city * self.B + b)

        gamma = (1.0 - temp) * np.pi * 0.5 + 0.1
        qc.rx(temp * np.pi, range(self.num_nodes * self.B))
        for i in range((self.num_nodes * self.B) - 1):
            qc.cx(i, i + 1)
            qc.rz(gamma, i + 1)
            qc.cx(i, i + 1)

        qc.measure_all()
        return qc

    def _extract_counts(self, result):
        data = result[0].data
        for attr_name in dir(data):
            attr = getattr(data, attr_name, None)
            if attr and hasattr(attr, "get_counts"):
                return attr.get_counts()
        return data.meas.get_counts()

    def solve(self, warm_start_route=None):
        """Main execution entry for the Backend API."""
        t0_wall = time.time()
        suhu_list = [0.8, 0.4, 0.1]

        for i, temp in enumerate(suhu_list):
            job_id_placeholder = (
                f"sim-qai-{i + 1}-{uuid.uuid4().hex[:8]}" if self.is_simulator else "PENDING"
            )
            job_ctx = {
                "job_id": job_id_placeholder,
                "algorithm": f"QAI-HOBO-Temp-{temp}",
                "backend_name": self.backend_name,
                "temp": temp,
            }
            if self.job_callback:
                self.job_callback("job_start", job_ctx)

            try:
                qc = self.build_qai_circuit(temp, warm_start_route)
                if self.is_simulator or self.pm is None:
                    job = self.sampler.run([qc])
                else:
                    isa_qc = self.pm.run(qc)
                    job = self.sampler.run([isa_qc])
                    if hasattr(job, "job_id"):
                        try:
                            job_ctx["job_id"] = job.job_id()
                        except Exception:
                            pass

                # Blocking wait — FastAPI BackgroundTasks isolate this from the request thread.
                result = job.result()

                quantum_seconds = 0.0
                if not self.is_simulator:
                    try:
                        quantum_seconds = job.metrics().get("usage", {}).get("quantum_seconds", 0)
                    except Exception:
                        pass
                self.qpu_seconds += quantum_seconds

                counts = self._extract_counts(result)
                best_bits = max(counts, key=counts.get)
                tour = self.hobo_decode(best_bits)
                dist = self.calculate_distance(tour)

                if dist < self.best_dist:
                    self.best_dist = dist
                    self.best_tour = tour

                job_ctx["qpu_time_seconds"] = quantum_seconds
                if self.job_callback:
                    self.job_callback("job_complete", job_ctx)

            except Exception as e:
                if self.job_callback:
                    self.job_callback("job_failed", job_ctx)
                raise e

        self.wall_clock_time = time.time() - t0_wall

        return {
            "best_tour": self.best_tour,
            "best_distance": self.best_dist if self.best_tour else float("inf"),
            "qpu_seconds": round(self.qpu_seconds, 3),
            "wall_clock_time": round(self.wall_clock_time, 3),
        }
