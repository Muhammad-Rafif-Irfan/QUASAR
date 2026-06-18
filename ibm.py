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
from sklearn.cluster import KMeans

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
# 1. SETUP DATA & FUNGSI PETA (Da Nang - 30 Titik)
# =====================================================================
import random

print("\n[1] Memuat Peta Offline Da Nang...")
G = ox.load_graphml("danang_offline.graphml")

# Kita kunci seed-nya agar koordinat pelanggannya selalu sama setiap kali script dijalankan
random.seed(42) 

# Titik 0 (Depot) dan beberapa titik ikonik awal
points = [
    {"name": "Depot Pusat",   "lat": 16.0544, "lon": 108.2022},
    {"name": "Pelabuhan",     "lat": 16.0650, "lon": 108.2200},
    {"name": "Bandara",       "lat": 16.0438, "lon": 108.1990},
    {"name": "Jembatan Naga", "lat": 16.0611, "lon": 108.2272}
]

# Generate otomatis 26 titik pengiriman pelanggan (Total 30 titik)
for i in range(5, 31):
    points.append({
        "name": f"Customer {i}",
        # Disebar secara acak dalam radius ~4.5 km dari Depot Pusat
        "lat": 16.0544 + random.uniform(-0.04, 0.04), 
        "lon": 108.2022 + random.uniform(-0.04, 0.04)
    })

n = len(points)
print(f"    ✅ Total Lokasi: {n} Titik (1 Depot + {n-1} Customer)")

print("    ⏳ Memetakan koordinat ke jalan raya terdekat (Ini butuh beberapa detik)...")
nodes = [ox.distance.nearest_nodes(G, X=p["lon"], Y=p["lat"]) for p in points]

dist_matrix = np.zeros((n, n), dtype=int)
for i in range(n):
    for j in range(n):
        if i != j: 
            try:
                dist_matrix[i][j] = nx.shortest_path_length(G, nodes[i], nodes[j], weight='length')
            except nx.NetworkXNoPath:
                # Berjaga-jaga jika ada titik yang terisolasi di peta offline
                dist_matrix[i][j] = 999999 

def tour_distance(tour):
    if len(tour) < 2: return 999999
    return sum(dist_matrix[tour[k]][tour[k + 1]] for k in range(len(tour) - 1))

# Siapkan folder untuk menyimpan peta
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
        # Depot berwarna merah, sisa customer berwarna biru
        folium.Marker([p["lat"], p["lon"]], popup=p['name'], icon=folium.Icon(color='red' if i==0 else 'blue')).add_to(m)
    m.save(filename)

# =====================================================================
# 2. OR-TOOLS (CLASSICAL BASELINE)
# =====================================================================
print("\n[2] Menjalankan OR-Tools (Lokal)...")
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

# Render Peta OR-Tools
render_map(ort_tour, "maps_ibm_vqa/1_OR_Tools.html", f"OR-Tools ({ort_dist}m)", "orange")
print(f"    ✅ Jarak OR-Tools: {ort_dist} m | Peta Disimpan!")

# =====================================================================
# 3. KONEKSI IBM QUANTUM
# =====================================================================
print("\n[3] Menghubungkan ke Mesin IBM Quantum...")
service = QiskitRuntimeService(channel="ibm_quantum_platform")
backend = service.least_busy(operational=True, min_num_qubits=127)
pm = generate_preset_pass_manager(target=backend.target, optimization_level=3)
sampler = Sampler(mode=backend)
sampler.options.default_shots = 1024



print(f"    ✅ Terhubung ke: {backend.name}")

# =====================================================================
# 4. QUBO+QAOA: TRUE HARDWARE LOOP (3 ITERASI)
# =====================================================================
print("\n[4] Eksekusi QUBO+QAOA di IBM (COBYLA Loop - 3 Iterasi)...")
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
    print(f"    ⏳ [Iterasi QAOA {qaoa_iter}/3] Mengirim ke IBM...")
    isa_qc = pm.run(build_qaoa(params[0], params[1]))
    
    job = sampler.run([isa_qc])
    print(f"       Job ID: {job.job_id()} -> Menunggu hasil cloud...")
    
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
    print(f"       -> Jarak ditemukan: {dist} m")
    
    if dist < qaoa_best_dist:
        qaoa_best_dist = dist
        qaoa_best_tour = tour
    return dist

t0_qaoa = time.time()
minimize(qaoa_obj, [0.5, 0.5], method='COBYLA', options={'maxiter': 3}) # Diubah ke 3
time_qaoa = time.time() - t0_qaoa

# Render Peta QAOA
render_map(qaoa_best_tour, "maps_ibm_vqa/2_QAOA_Hardware.html", f"QAOA ({qaoa_best_dist}m)", "red")

# ---------------------------------------------------------
# A. CLUSTERING: Memecah Peta Besar Menjadi Sub-Zona Kecil
# ---------------------------------------------------------
# Misal sekarang kamu punya N = 16 titik. 
# Kita pecah menjadi K = 4 sub-zona (masing-masing zona berisi ~4 titik + 1 Depot)

koordinat = np.array([[p["lat"], p["lon"]] for p in points[1:]]) # Kecualikan Depot Pusat sementara
jumlah_cluster = 4 # Sesuaikan agar N per cluster tidak lebih dari 5-6 titik
kmeans = KMeans(n_clusters=jumlah_cluster, random_state=42).fit(koordinat)

sub_zones = {i: [0] for i in range(jumlah_cluster)} # Setiap zona WAJIB memiliki Depot (index 0)

# Masukkan sisa titik ke clusternya masing-masing
for idx, label in enumerate(kmeans.labels_):
    sub_zones[label].append(idx + 1) # +1 karena index 0 adalah Depot

print(f"\n[Dekomposisi Aktif] Peta dipecah menjadi {jumlah_cluster} Sub-Zona:")
for zona, titik_zona in sub_zones.items():
    print(f"    Zona {zona}: Titik {titik_zona}")

# =====================================================================
# 5. QAI+HOBO (HYBRID DIVIDE-AND-CONQUER + QEM)
# =====================================================================

print("\n[5] Eksekusi QAI+HOBO Hybrid (Dekomposisi & Error Mitigation)...")



# --- B. CLUSTERING (MEMECAH PETA) ---
# Memecah titik (selain depot 0) menjadi beberapa zona kecil
jumlah_cluster = max(1, (n - 1) // 4) # Paksa maksimal ~4 titik per zona agar QPU tidak stres
koordinat = np.array([[p["lat"], p["lon"]] for p in points[1:]])
kmeans = KMeans(n_clusters=jumlah_cluster, random_state=42, n_init='auto').fit(koordinat)

sub_zones = {i: [0] for i in range(jumlah_cluster)} # Index 0 (Depot) wajib ada di tiap zona
for idx, label in enumerate(kmeans.labels_):
    sub_zones[label].append(idx + 1)

print(f"    ✅ Peta dipecah menjadi {jumlah_cluster} Sub-Zona:")
for z, t in sub_zones.items():
    print(f"       Zona {z}: {t}")

# --- C. FUNGSI PEMBANTU UNTUK SUB-ZONA ---
def hobo_decode_sub(bitstring, sub_n, sub_B):
    bits = list(reversed(bitstring))
    pos = {c: sum(int(bits[c*sub_B + b]) * (2**b) for b in range(sub_B) if c*sub_B+b < len(bits)) % sub_n for c in range(sub_n)}
    ordered = [None] * sub_n
    for c, p in sorted(pos.items(), key=lambda item: item[1]):
        if ordered[p] is None: ordered[p] = c
        else:
            empty = [i for i in range(sub_n) if ordered[i] is None]
            if empty: ordered[empty[0]] = c
    ordered = [c for c in ordered if c is not None]
    if 0 in ordered: ordered.remove(0)
    return [0] + ordered + [0]

def build_qai_sub(temp, sub_n, sub_B, sub_ort_tour):
    qc = QuantumCircuit(sub_n * sub_B)
    qc.h(range(sub_n * sub_B))
    # Warm-start menyontek rute lokal
    for seq, city in enumerate(sub_ort_tour[:-1]):
        pos_ratio = seq / max(sub_n - 1, 1)
        for b in range(sub_B): qc.rz(pos_ratio * np.pi * (b + 1) / sub_B, city * sub_B + b)
    
    gamma = (1.0 - temp) * np.pi * 0.5 + 0.1
    qc.rx(temp * np.pi, range(sub_n * sub_B))
    
    # Interaksi dangkal (Shallow circuit) agar terhindar dari noise
    for i in range((sub_n * sub_B)-1):
        qc.cx(i, i+1)
        qc.rz(gamma, i+1)
        qc.cx(i, i+1)
    qc.measure_all()
    return qc

# --- D. LOOP EKSEKUSI QPU PER ZONA ---
t0_qai = time.time()
qai_total_qpu_time = 0
global_qai_routes = {}
total_qai_hybrid_distance = 0
suhu_list = [0.8, 0.4, 0.1] 

for zona, titik_global in sub_zones.items():
    sub_n = len(titik_global)
    sub_B = max(1, int(np.ceil(np.log2(sub_n))))
    print(f"\n    ⏳ [Zona {zona}] Mempersiapkan {sub_n} titik untuk QPU...")
    
    # 1. Buat Matriks Jarak Lokal
    sub_dist_matrix = np.zeros((sub_n, sub_n), dtype=int)
    for i in range(sub_n):
        for j in range(sub_n):
            sub_dist_matrix[i][j] = dist_matrix[titik_global[i]][titik_global[j]]
            
    # 2. Bantuan OR-Tools Lokal (Sebagai Warm-Start Sirkuit QAI)
    manager_sub = pywrapcp.RoutingIndexManager(sub_n, 1, 0)
    routing_sub = pywrapcp.RoutingModel(manager_sub)
    routing_sub.SetArcCostEvaluatorOfAllVehicles(routing_sub.RegisterTransitCallback(lambda i, j: sub_dist_matrix[manager_sub.IndexToNode(i)][manager_sub.IndexToNode(j)]))
    params_sub = pywrapcp.DefaultRoutingSearchParameters()
    params_sub.time_limit.seconds = 1
    assign_sub = routing_sub.SolveWithParameters(params_sub)
    sub_ort_tour = []
    idx = routing_sub.Start(0)
    while not routing_sub.IsEnd(idx):
        sub_ort_tour.append(manager_sub.IndexToNode(idx))
        idx = assign_sub.Value(routing_sub.NextVar(idx))
    sub_ort_tour.append(manager_sub.IndexToNode(idx))

    # 3. Eksekusi QAI Annealing Loop
    sub_qai_best_tour = []
    sub_qai_best_dist = float('inf')
    
    for i, temp in enumerate(suhu_list):
        print(f"       -> [Suhu {temp}] Mengirim ke IBM...")
        isa_qc = pm.run(build_qai_sub(temp, sub_n, sub_B, sub_ort_tour))
        job = sampler.run([isa_qc])
        result = job.result()
        
        try: qai_total_qpu_time += job.metrics().get("usage", {}).get("quantum_seconds", 0)
        except: pass
        
        counts = result[0].data.meas.get_counts()
        bits = max(counts, key=counts.get)
        local_tour = hobo_decode_sub(bits, sub_n, sub_B)
        
        # Hitung Jarak Lokal
        d = sum(sub_dist_matrix[local_tour[k]][local_tour[k+1]] for k in range(len(local_tour)-1))
        if d < sub_qai_best_dist:
            sub_qai_best_dist = d
            sub_qai_best_tour = local_tour
            
    # 4. Petakan indeks lokal kembali ke ID global di peta
    global_tour_mapped = [titik_global[idx] for idx in sub_qai_best_tour]
    global_qai_routes[zona] = global_tour_mapped
    total_qai_hybrid_distance += sub_qai_best_dist
    print(f"       ✅ Rute Optimal Zona {zona}: {global_tour_mapped} | Jarak: {sub_qai_best_dist}m")

time_qai = time.time() - t0_qai

# Output akhir untuk ditampilkan di terminal atau peta
qai_best_dist = total_qai_hybrid_distance
print(f"\n    🏆 TOTAL JARAK SELURUH ZONA (QAI+HOBO Hybrid): {qai_best_dist}m")
# =====================================================================
# 6. CETAK BENCHMARK FINAL
# =====================================================================
print("\n" + "="*85)
print(f"🏆 HASIL VALIDASI TRUE-VQA IBM (N={n} Titik Logistik)")
print("="*85)
print(f"{'Algoritma':<12} | {'Jarak Terbaik':<15} | {'Wall-Clock Total':<20} | {'Waktu Murni QPU IBM'}")
print("-" * 85)
print(f"{'OR-Tools':<12} | {ort_dist:<11} m | {ort_time:<15.1f} ms | N/A (Klasik Lokal)")
print(f"{'QUBO+QAOA':<12} | {qaoa_best_dist:<11} m | {time_qaoa:<15.1f} dtk | {qaoa_total_qpu_time:.2f} dtk")
print(f"{'QAI+HOBO':<12} | {qai_best_dist:<11} m | {time_qai:<15.1f} dtk | {qai_total_qpu_time:.2f} dtk")
print("="*85)
print("✅ Peta HTML telah di-generate di dalam folder 'maps_ibm_vqa'!")
print("Siap untuk dipresentasikan ke dewan juri.")