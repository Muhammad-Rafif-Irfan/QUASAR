import time
import numpy as np
import osmnx as ox
import networkx as nx
import folium
import os
from scipy.optimize import minimize
import warnings
warnings.filterwarnings('ignore')

# Qiskit & IBM Runtime
from qiskit import QuantumCircuit
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler

try:
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp
except ImportError:
    print("WARNING: OR-Tools tidak tersedia.")

print("=================================================================")
print("🚀 ULTIMATE VQA BENCHMARK: QAOA vs QAI+HOBO (DENGAN PETA)")
print("Target Mesin : IBM Quantum (127-Qubit)")
print("Strategi     : Closed-Loop Hardware (Max 3 Iterasi)")
print("Kapasitas    : 8 Titik Pengiriman (N=8)")
print("=================================================================")

# =====================================================================
# 1. DATA SETUP & MAP FUNCTION (Da Nang - 8 Point)
# =====================================================================
print("\n[1] Loading Offline Map Da Nang...")
G = ox.load_graphml("danang_offline.graphml")

points = [
    {"name": "Depot Pusat",   "lat": 16.0544, "lon": 108.2022},
    {"name": "Pelabuhan",     "lat": 16.0650, "lon": 108.2200},
    {"name": "Pasar Con",     "lat": 16.0450, "lon": 108.2100},
    {"name": "Pantai",        "lat": 16.0500, "lon": 108.1900},
    {"name": "Bandara",       "lat": 16.0438, "lon": 108.1990},
    {"name": "Jembatan Naga", "lat": 16.0611, "lon": 108.2272},
    {"name": "Han Market",    "lat": 16.0680, "lon": 108.2241},
    {"name": "Lotte Mart",    "lat": 16.0333, "lon": 108.2211}
]
n = len(points)
nodes = [ox.distance.nearest_nodes(G, X=p["lon"], Y=p["lat"]) for p in points]

dist_matrix = np.zeros((n, n), dtype=int)
for i in range(n):
    for j in range(n):
        if i != j: dist_matrix[i][j] = nx.shortest_path_length(G, nodes[i], nodes[j], weight='length')

def tour_distance(tour):
    if len(tour) < 2: return 999999
    return sum(dist_matrix[tour[k]][tour[k + 1]] for k in range(len(tour) - 1))


os.makedirs('maps_ibm_vqa', exist_ok=True)

def render_map(route, filename, title, color):
    clat, clon = np.mean([p["lat"] for p in points]), np.mean([p["lon"] for p in points])
    m = folium.Map(location=[clat, clon], zoom_start=13, tiles='CartoDB positron')
    path_nodes = []
    for i in range(len(route) - 1):
        try: path_nodes.extend(nx.shortest_path(G, nodes[route[i]], nodes[route[i + 1]], weight='length'))
        except: continue
    if path_nodes:
        coords = [(G.nodes[nd]['y'], G.nodes[nd]['x']) for nd in path_nodes if nd in G.nodes]
        folium.PolyLine(coords, color=color, weight=5, opacity=0.8, tooltip=title).add_to(m)
    for i, p in enumerate(points):
        folium.Marker([p["lat"], p["lon"]], popup=p['name'], icon=folium.Icon(color='red' if i==0 else 'blue')).add_to(m)
    m.save(filename)

# =====================================================================
# 2. OR-TOOLS (CLASSICAL BASELINE)
# =====================================================================
print("\n[2] Running OR-Tools (Local)...")
manager = pywrapcp.RoutingIndexManager(n, 1, 0)
routing = pywrapcp.RoutingModel(manager)
routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(lambda i, j: dist_matrix[manager.IndexToNode(i)][manager.IndexToNode(j)]))
params = pywrapcp.DefaultRoutingSearchParameters()
params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
params.time_limit.seconds = 3

t0_ort = time.time()
assignment = routing.SolveWithParameters(params)
ort_tour = []
if assignment:
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        ort_tour.append(manager.IndexToNode(idx))
        idx = assignment.Value(routing.NextVar(idx))
    ort_tour.append(manager.IndexToNode(idx))
ort_dist = tour_distance(ort_tour)
ort_time = (time.time() - t0_ort) * 1000


render_map(ort_tour, "maps_ibm_vqa/1_OR_Tools.html", f"OR-Tools ({ort_dist}m)", "orange")
print(f"    ✅ OR-Tools Distance: {ort_dist} m | Map Saved!")

# =====================================================================
# 3. KONEKSI IBM QUANTUM
# =====================================================================
print("\n[3] Connecting to IBM Quantum Machine...")
service = QiskitRuntimeService(channel="ibm_quantum_platform")
backend = service.least_busy(operational=True, min_num_qubits=127)
pm = generate_preset_pass_manager(target=backend.target, optimization_level=3)
sampler = Sampler(mode=backend)
sampler.options.default_shots = 1024
print(f"    ✅ Connected to: {backend.name}")

# =====================================================================
# 4. QUBO+QAOA: TRUE HARDWARE LOOP (3 ITERATIONS)
# =====================================================================
print("\n[4] Executing QUBO+QAOA on IBM (COBYLA Loop - 3 Iterations)...")
qaoa_iter = 0
qaoa_best_tour = []
qaoa_best_dist = float('inf')
qaoa_total_qpu_time = 0

def build_qaoa(gamma, beta):
    qc = QuantumCircuit(n-1)
    qc.h(range(n-1))
    for i in range(n-1):
        for j in range(i+1, n-1):
            qc.cx(i, j)
            qc.rz(gamma, j)
            qc.cx(i, j)
    qc.rx(beta, range(n-1))
    qc.measure_all()
    return qc

def qaoa_obj(params):
    global qaoa_iter, qaoa_best_dist, qaoa_best_tour, qaoa_total_qpu_time
    qaoa_iter += 1
    print(f"    ⏳ [Iteration QAOA {qaoa_iter}/3] Sending to IBM...")
    isa_qc = pm.run(build_qaoa(params[0], params[1]))
    
    job = sampler.run([isa_qc])
    print(f"       Job ID: {job.job_id()} -> Waiting for cloud results...")
    
    result = job.result()
    try:
        qaoa_total_qpu_time += job.metrics().get("usage", {}).get("quantum_seconds", 0)
    except:
        pass
    counts = result[0].data.meas.get_counts()
    
    best_bits = max(counts, key=counts.get)
    tour = [0] + [i+1 for i, b in enumerate(reversed(best_bits)) if b == '1']
    tour.extend([i for i in range(1, n) if i not in tour])
    tour.append(0)
    
    dist = tour_distance(tour)
    print(f"       -> Distance Found: {dist} m")
    
    if dist < qaoa_best_dist:
        qaoa_best_dist = dist
        qaoa_best_tour = tour
    return dist

t0_qaoa = time.time()
minimize(qaoa_obj, [0.5, 0.5], method='COBYLA', options={'maxiter': 3}) # Diubah ke 3
time_qaoa = time.time() - t0_qaoa

# Render Peta QAOA
render_map(qaoa_best_tour, "maps_ibm_vqa/2_QAOA_Hardware.html", f"QAOA ({qaoa_best_dist}m)", "red")

# =====================================================================
# 5. QAI+HOBO: TRUE HARDWARE LOOP (3 TEMPERATURES)
# =====================================================================
print("\n[5] Executing QAI+HOBO on IBM (Annealing Loop - 3 Temperatures)...")
B = max(1, int(np.ceil(np.log2(n))))
qai_best_tour = []
qai_best_dist = float('inf')
qai_total_qpu_time = 0

def hobo_decode(bitstring):
    bits = list(reversed(bitstring))
    pos = {c: sum(int(bits[c*B + b]) * (2**b) for b in range(B) if c*B+b < len(bits)) % n for c in range(n)}
    ordered = [None] * n
    for c, p in sorted(pos.items(), key=lambda item: item[1]):
        if ordered[p] is None: ordered[p] = c
        else:
            empty = [i for i in range(n) if ordered[i] is None]
            if empty: ordered[empty[0]] = c
    ordered = [c for c in ordered if c is not None]
    if 0 in ordered: ordered.remove(0)
    return [0] + ordered + [0]

def build_qai(temp):
    qc = QuantumCircuit(n * B)
    qc.h(range(n * B))
    for seq, city in enumerate(ort_tour[:-1]):
        pos_ratio = seq / max(n - 1, 1)
        for b in range(B): qc.rz(pos_ratio * np.pi * (b + 1) / B, city * B + b)
    gamma = (1.0 - temp) * np.pi * 0.5 + 0.1
    qc.rx(temp * np.pi, range(n * B))
    for i in range((n * B)-1):
        qc.cx(i, i+1)
        qc.rz(gamma, i+1)
        qc.cx(i, i+1)
    qc.measure_all()
    return qc

t0_qai = time.time()
suhu_list = [0.8, 0.4, 0.1] # Diubah ke 3 tahap suhu (panas, hangat, dingin)

for i, temp in enumerate(suhu_list):
    print(f"    ⏳ [Temperature QAI {i+1}/3] Sending to IBM...")
    isa_qc = pm.run(build_qai(temp))
    
    job = sampler.run([isa_qc])
    print(f"       Job ID: {job.job_id()} -> Waiting for cloud results...")
    
    result = job.result()
    try:
        qai_total_qpu_time += job.metrics().get("usage", {}).get("quantum_seconds", 0)
    except:
        pass
    counts = result[0].data.meas.get_counts()
    
    bits = max(counts, key=counts.get)
    tour = hobo_decode(bits)
    d = tour_distance(tour)
    print(f"       -> Distance Found: {d} m")
    
    if d < qai_best_dist:
        qai_best_dist = d
        qai_best_tour = tour
        
time_qai = time.time() - t0_qai

# Render Peta QAI+HOBO
render_map(qai_best_tour, "maps_ibm_vqa/3_QAI_HOBO_Hardware.html", f"QAI+HOBO ({qai_best_dist}m)", "green")

# =====================================================================
# 6. CETAK BENCHMARK FINAL
# =====================================================================
print("\n" + "="*85)
print(f"Validation Results TRUE-VQA IBM (N={n} Logistic Points)")
print("="*85)
print(f"{'Algorithm':<12} | {'Best Distance':<15} | {'Wall-Clock Total':<20} | {'Pure QPU Time IBM'}")
print("-" * 85)
print(f"{'OR-Tools':<12} | {ort_dist:<11} m | {ort_time:<15.1f} ms | N/A (Classical Local)")
print(f"{'QUBO+QAOA':<12} | {qaoa_best_dist:<11} m | {time_qaoa:<15.1f} s | {qaoa_total_qpu_time:.2f} s")
print(f"{'QAI+HOBO':<12} | {qai_best_dist:<11} m | {time_qai:<15.1f} s | {qai_total_qpu_time:.2f} s")
print("="*85)
print("✅ HTML Map generated inside the 'maps_ibm_vqa' folder!")