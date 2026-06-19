from abc import ABC, abstractmethod
import time

class BaseQuantumSolver(ABC):
    def __init__(self, distance_matrix):
        """
        Blueprint for all Quantum Solvers (QAI, QAOA, dll).
        """
        self.distance_matrix = distance_matrix
        self.num_nodes = len(distance_matrix)
        
        # State Tracking 
        self.best_tour = []
        self.best_dist = float('inf')
        self.qpu_seconds = 0.0         # Murni waktu komputasi mesin IBM
        self.wall_clock_time = 0.0     # Total waktu termasuk antrean Cloud & latensi jaringan

    def validate_tour(self, tour):
        """
        [AUDIT FIX] Prevent defective tours (missing/duplicate cities) from slipping through the benchmark.
        """
        # Rule 1: Must end at the depot (number of stops + 1)
        if len(tour) != self.num_nodes + 1:
            return False
            
       # Rule 2: Must start and return to the Depot (node 0)
        if tour[0] != 0 or tour[-1] != 0:
            return False
            
        # Rule 3: Must visit every city exactly once
        middle_stops = tour[1:-1]
        if len(set(middle_stops)) != self.num_nodes - 1:
            return False
            
        return True

    def calculate_distance(self, tour):
        """
        Calculating distance. If the route is invalid, give an infinite penalty.
        """
        if not self.validate_tour(tour):
            return 999999  # Penalty

        dist = 0
        for i in range(len(tour) - 1):
            dist += self.distance_matrix[tour[i]][tour[i+1]]
        return dist

    @abstractmethod
    def solve(self, warm_start_route=None):
        """
        Fungsi abstrak yang WAJIB diimplementasikan oleh kelas turunannya.
        """
        pass
