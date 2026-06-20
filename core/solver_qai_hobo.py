import time
import numpy as np
from qiskit import QuantumCircuit
from core.base_solver import BaseQuantumSolver

class QaiHoboSolver(BaseQuantumSolver):
    def __init__(self, distance_matrix, sampler, pass_manager):
        super().__init__(distance_matrix)
        self.sampler = sampler  # SamplerV2 dari Qiskit Runtime
        self.pm = pass_manager
        self.B = max(1, int(np.ceil(np.log2(self.num_nodes))))

    def hobo_decode(self, bitstring):
        """HOBO decoder to convert a bitstring into a route sequence."""
        bits = list(reversed(bitstring))
        pos = {c: sum(int(bits[c*self.B + b]) * (2**b) for b in range(self.B) if c*self.B+b < len(bits)) % self.num_nodes for c in range(self.num_nodes)}
        
        ordered = [None] * self.num_nodes
        for c, p in sorted(pos.items(), key=lambda item: item[1]):
            if ordered[p] is None: 
                ordered[p] = c
            else:
                empty = [i for i in range(self.num_nodes) if ordered[i] is None]
                if empty: ordered[empty[0]] = c
                
        ordered = [c for c in ordered if c is not None]
        if 0 in ordered: ordered.remove(0)
        
        return [0] + ordered + [0]

    def build_qai_circuit(self, temp, warm_start_route):
        """A circuit builder that now uses a dynamic warm_start_route parameter."""
        qc = QuantumCircuit(self.num_nodes * self.B)
        qc.h(range(self.num_nodes * self.B))
        
        # Encoding Warm-Start
        if warm_start_route:
            for seq, city in enumerate(warm_start_route[:-1]):
                pos_ratio = seq / max(self.num_nodes - 1, 1)
                for b in range(self.B): 
                    qc.rz(pos_ratio * np.pi * (b + 1) / self.B, city * self.B + b)
                    
        # Entanglement & Mixing
        gamma = (1.0 - temp) * np.pi * 0.5 + 0.1
        qc.rx(temp * np.pi, range(self.num_nodes * self.B))
        for i in range((self.num_nodes * self.B)-1):
            qc.cx(i, i+1)
            qc.rz(gamma, i+1)
            qc.cx(i, i+1)
            
        qc.measure_all()
        return qc

    def solve(self, warm_start_route=None):
        """The main function of execution for the Backend API."""
        t0_wall = time.time()  # Mulai menghitung Wall-Clock Time
        suhu_list = [0.8, 0.4, 0.1]
        
        for temp in suhu_list:
            isa_qc = self.pm.run(self.build_qai_circuit(temp, warm_start_route))
            job = self.sampler.run([isa_qc])
            
            # NOTE: This is still a blocking call, Kenneth will later change it
            # to an Asynchronous Celery/Task Queue on the Backend side.
            result = job.result() 
            
            # [AUDIT FIX] Pure QPU Time Extraction from IBM
            try:
                self.qpu_seconds += job.metrics().get("usage", {}).get("quantum_seconds", 0)
            except:
                pass
                
            counts = result[0].data.meas.get_counts()
            best_bits = max(counts, key=counts.get)
            tour = self.hobo_decode(best_bits)
            
            # Calculating distance (automatically validated by BaseQuantumSolver)
            dist = self.calculate_distance(tour)
            
            if dist < self.best_dist:
                self.best_dist = dist
                self.best_tour = tour

        # Calculating total time (including cloud queue)
        self.wall_clock_time = time.time() - t0_wall
        
        return {
            "best_tour": self.best_tour,
            "best_distance": self.best_dist,
            "qpu_seconds": round(self.qpu_seconds, 3),
            "wall_clock_time": round(self.wall_clock_time, 3)
        }
