import os
import math
import numpy as np
import osmnx as ox
import networkx as nx
import folium

# Configure OSMnx timeouts to fail quickly when offline
try:
    ox.settings.timeout = 5
    ox.settings.requests_timeout = 5
    ox.settings.max_retries = 1
except AttributeError:
    try:
        ox.config(timeout=5, max_retries=1)
    except Exception:
        pass

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """
    Computes the great-circle distance between two points in meters.
    """
    R = 6371000.0  # radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) *
         math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return int(R * c)

def calculate_distance_matrix(depot: dict, stops: list[dict]) -> tuple[np.ndarray, nx.MultiDiGraph, list]:
    """
    Downloads OSM drive graph around coordinates and calculates the distance matrix.
    Falls back to Haversine distance if no path is found or OSMnx network error occurs.
    """
    points = [depot] + stops
    n = len(points)
    
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    
    # 0.02 degree padding around bounding box (approx. 2.2km)
    buffer = 0.02
    north = max(lats) + buffer
    south = min(lats) - buffer
    east = max(lons) + buffer
    west = min(lons) - buffer
    
    try:
        # Fetch OSM graph dynamically
        try:
            # Try newer OSMnx API
            G = ox.graph_from_bbox(bbox=(north, south, east, west), network_type='drive')
        except TypeError:
            # Try older OSMnx API
            G = ox.graph_from_bbox(north, south, east, west, network_type='drive')
            
        # Snap coordinates to nearest nodes
        nodes = []
        for p in points:
            node = ox.nearest_nodes(G, X=p["lon"], Y=p["lat"])
            nodes.append(node)
            
        dist_matrix = np.zeros((n, n), dtype=int)
        for i in range(n):
            for j in range(n):
                if i != j:
                    try:
                        dist_matrix[i][j] = nx.shortest_path_length(G, nodes[i], nodes[j], weight='length')
                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        # Fallback to Haversine
                        dist_matrix[i][j] = haversine_distance(points[i]["lat"], points[i]["lon"], points[j]["lat"], points[j]["lon"])
                else:
                    dist_matrix[i][j] = 0
                    
        return dist_matrix, G, nodes
    except Exception as e:
        print(f"WARNING: OSMnx routing failed ({e}). Falling back to pure Haversine distance matrix.")
        dist_matrix = np.zeros((n, n), dtype=int)
        for i in range(n):
            for j in range(n):
                if i != j:
                    dist_matrix[i][j] = haversine_distance(points[i]["lat"], points[i]["lon"], points[j]["lat"], points[j]["lon"])
                else:
                    dist_matrix[i][j] = 0
        return dist_matrix, None, None

def render_map(route: list[int], points: list[dict], G: nx.MultiDiGraph, nodes: list, filename: str, title: str, color: str):
    """
    Generates interactive HTML maps for a route using Folium.
    If OSM graph G is unavailable, draws straight lines between consecutive locations.
    """
    clat = float(np.mean([p["lat"] for p in points]))
    clon = float(np.mean([p["lon"] for p in points]))
    m = folium.Map(location=[clat, clon], zoom_start=13, tiles='CartoDB positron')
    
    path_nodes = []
    if G is not None and nodes is not None:
        for i in range(len(route) - 1):
            try:
                path_nodes.extend(nx.shortest_path(G, nodes[route[i]], nodes[route[i + 1]], weight='length'))
            except Exception:
                continue
                
    if path_nodes:
        coords = [(G.nodes[nd]['y'], G.nodes[nd]['x']) for nd in path_nodes if nd in G.nodes]
        folium.PolyLine(coords, color=color, weight=5, opacity=0.8, tooltip=title).add_to(m)
    else:
        # Fallback: draw straight lines between consecutive points
        coords = [(points[idx]["lat"], points[idx]["lon"]) for idx in route]
        folium.PolyLine(coords, color=color, weight=5, opacity=0.8, tooltip=title).add_to(m)
        
    for i, p in enumerate(points):
        folium.Marker(
            [p["lat"], p["lon"]],
            popup=p['name'],
            icon=folium.Icon(color='red' if i == 0 else 'blue')
        ).add_to(m)
        
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    m.save(filename)
