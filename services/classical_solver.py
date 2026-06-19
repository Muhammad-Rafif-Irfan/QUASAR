from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import time

class ORToolsSolver:
    def __init__(self, distance_matrix):
        self.distance_matrix = distance_matrix
        self.num_nodes = len(distance_matrix)

    def solve(self):
        """Running OR-Tools to get an initial guess (Warm-Start)"""
        manager = pywrapcp.RoutingIndexManager(self.num_nodes, 1, 0)
        routing = pywrapcp.RoutingModel(manager)
        
        # Distance Callback
        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return self.distance_matrix[from_node][to_node]
            
        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
        # Search Parameter
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
        search_parameters.time_limit.seconds = 3

        t0 = time.time()
        solution = routing.SolveWithParameters(search_parameters)
        
        ort_tour = []
        if solution:
            index = routing.Start(0)
            while not routing.IsEnd(index):
                ort_tour.append(manager.IndexToNode(index))
                index = solution.Value(routing.NextVar(index))
            ort_tour.append(manager.IndexToNode(index))
            
        execution_time = time.time() - t0
        
        return ort_tour, execution_time
