"""
routing.py — Dynamic Distance Matrix Engine for QUASAR

This module is responsible for:
  1. Downloading real-world road network data via OSMnx.
  2. Snapping GPS coordinates to the nearest road-network nodes.
  3. Computing an NxN shortest-path distance matrix (weight='length', meters).
  4. Falling back to Haversine (great-circle) distances when OSMnx is unavailable.
  5. Rendering interactive Folium maps for solved routes.

The primary public API consumed by the optimization pipeline is:
  - calculate_distance_matrix(depot, stops) -> (matrix, G, nodes)
  - compute_distance_matrix(locations)      -> List[List[float]]
  - render_map(route, points, G, nodes, filename, title, color)
"""

import os
import logging
from typing import List, Dict, Tuple, Optional

import numpy as np
import networkx as nx
import folium

# ---------------------------------------------------------------------------
# Logger setup — all routing events flow through this single logger.
# ---------------------------------------------------------------------------
logger = logging.getLogger("quasar.routing")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s | %(name)s | %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# OSMnx import & configuration
# Timeout is set aggressively low (5 s) so the system fails fast and
# switches to the Haversine fallback without blocking the async pipeline.
# ---------------------------------------------------------------------------
try:
    import osmnx as ox

    OSMNX_AVAILABLE = True
    try:
        # OSMnx >= 1.9 exposes settings as module-level attributes
        ox.settings.timeout = 5
        ox.settings.requests_timeout = 5
        ox.settings.max_retries = 1
    except AttributeError:
        try:
            # Older API
            ox.config(timeout=5, max_retries=1)
        except Exception:
            pass
except ImportError:
    OSMNX_AVAILABLE = False
    logger.warning("osmnx is not installed — road-network routing is disabled.")

# ---------------------------------------------------------------------------
# Haversine library import (used as the fallback distance calculator)
# ---------------------------------------------------------------------------
try:
    from haversine import haversine, Unit

    HAVERSINE_LIB_AVAILABLE = True
except ImportError:
    HAVERSINE_LIB_AVAILABLE = False
    logger.info(
        "haversine library not installed; using built-in great-circle formula."
    )

# ===================================================================== #
#                        DISTANCE FUNCTIONS                             #
# ===================================================================== #


def _haversine_builtin(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Pure-Python fallback for great-circle distance (meters).

    Uses the standard Haversine formula so that the module can still work
    even if the ``haversine`` pip package is missing.
    """
    import math

    R = 6_371_000.0  # Earth's mean radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Compute great-circle distance in **meters** between two GPS points.

    Prefers the ``haversine`` pip package (faster C-accelerated path) and
    falls back to the built-in Python implementation automatically.

    Returns
    -------
    float
        Distance in meters.
    """
    if HAVERSINE_LIB_AVAILABLE:
        return haversine((lat1, lon1), (lat2, lon2), unit=Unit.METERS)
    return _haversine_builtin(lat1, lon1, lat2, lon2)


# ===================================================================== #
#                     HAVERSINE DISTANCE MATRIX                         #
# ===================================================================== #


def _build_haversine_matrix(points: List[Dict]) -> List[List[float]]:
    """
    Build an NxN distance matrix using Haversine (great-circle) distances.

    Parameters
    ----------
    points : list[dict]
        Each dict must contain 'lat' and 'lon' keys.

    Returns
    -------
    list[list[float]]
        NxN matrix where element [i][j] is the distance in meters.
    """
    n = len(points)
    matrix: List[List[float]] = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_distance(
                points[i]["lat"], points[i]["lon"],
                points[j]["lat"], points[j]["lon"],
            )
            matrix[i][j] = d
            matrix[j][i] = d  # symmetric

    return matrix


# ===================================================================== #
#                  OSMnx ROAD-NETWORK DISTANCE MATRIX                   #
# ===================================================================== #


def _download_graph(
    points: List[Dict],
    buffer_deg: float = 0.02,
) -> "nx.MultiDiGraph":
    """
    Download the OSM drive network covering all *points* with a bounding-box
    buffer of *buffer_deg* degrees (~2.2 km at mid-latitudes).

    Raises
    ------
    RuntimeError
        If osmnx is not installed.
    Exception
        Any network/API error propagated from OSMnx.
    """
    if not OSMNX_AVAILABLE:
        raise RuntimeError("osmnx is not installed")

    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]

    north = max(lats) + buffer_deg
    south = min(lats) - buffer_deg
    east = max(lons) + buffer_deg
    west = min(lons) - buffer_deg

    logger.info(
        "Downloading OSM drive graph — bbox N=%.4f S=%.4f E=%.4f W=%.4f",
        north, south, east, west,
    )

    # Handle both old and new OSMnx API signatures
    try:
        G = ox.graph_from_bbox(
            bbox=(north, south, east, west), network_type="drive"
        )
    except TypeError:
        G = ox.graph_from_bbox(north, south, east, west, network_type="drive")

    logger.info(
        "Graph loaded — %d nodes, %d edges.",
        G.number_of_nodes(),
        G.number_of_edges(),
    )
    return G


def _snap_nodes(
    G: "nx.MultiDiGraph", points: List[Dict]
) -> List[int]:
    """
    Snap each GPS coordinate in *points* to the nearest node in graph *G*.

    Returns
    -------
    list[int]
        OSM node IDs corresponding to each input point.
    """
    nodes = []
    for p in points:
        node_id = ox.nearest_nodes(G, X=p["lon"], Y=p["lat"])
        nodes.append(node_id)
    return nodes


def _build_osmnx_matrix(
    G: "nx.MultiDiGraph",
    nodes: List[int],
    points: List[Dict],
) -> List[List[float]]:
    """
    Build the NxN distance matrix using NetworkX shortest-path lengths on
    the OSM road graph *G*.

    For any pair where no road path exists, the Haversine distance is used
    as a graceful per-cell fallback so the matrix is always complete.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        The OSM road-network graph.
    nodes : list[int]
        Snapped OSM node IDs for each location.
    points : list[dict]
        Original location dicts (used for Haversine fallback).

    Returns
    -------
    list[list[float]]
        NxN distance matrix in meters.
    """
    n = len(nodes)
    matrix: List[List[float]] = [[0.0] * n for _ in range(n)]

    logger.info("Computing %dx%d shortest-path distance matrix...", n, n)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            try:
                matrix[i][j] = float(
                    nx.shortest_path_length(
                        G, nodes[i], nodes[j], weight="length"
                    )
                )
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                # Per-cell fallback: no road connects these two nodes
                matrix[i][j] = haversine_distance(
                    points[i]["lat"], points[i]["lon"],
                    points[j]["lat"], points[j]["lon"],
                )
                logger.debug(
                    "No road path from node %s to %s — used Haversine (%.1f m).",
                    nodes[i], nodes[j], matrix[i][j],
                )

    logger.info("Distance matrix computation complete.")
    return matrix


# ===================================================================== #
#                         PUBLIC API                                     #
# ===================================================================== #


def compute_distance_matrix(
    locations: List[Dict],
) -> List[List[float]]:
    """
    High-level API: compute an NxN distance matrix from a flat list of
    location dictionaries.

    This is the **standalone** entry-point designed for direct consumption by
    optimization algorithms (OR-Tools, Qiskit QAOA, etc.).

    Parameters
    ----------
    locations : list[dict]
        A list of dicts, each containing at minimum ``'lat'`` and ``'lon'``
        keys (and optionally ``'name'``).
        Example::

            [
                {"name": "A", "lat": 16.0544, "lon": 108.2022},
                {"name": "B", "lat": 16.0650, "lon": 108.2200},
            ]

    Returns
    -------
    list[list[float]]
        A 2D list of shape NxN where element ``[i][j]`` is the distance in
        **meters** between ``locations[i]`` and ``locations[j]``.
        Diagonal entries are ``0.0``.

    Notes
    -----
    - Attempts real road-network routing via OSMnx first.
    - Falls back to Haversine great-circle distances on any failure
      (network timeout, missing library, API error, etc.).
    """
    n = len(locations)
    if n == 0:
        return []
    if n == 1:
        return [[0.0]]

    # --- Attempt OSMnx road-network routing ---
    if OSMNX_AVAILABLE:
        try:
            G = _download_graph(locations)
            nodes = _snap_nodes(G, locations)
            return _build_osmnx_matrix(G, nodes, locations)
        except Exception as exc:
            logger.warning(
                "OSMnx routing failed (%s). Falling back to Haversine.", exc
            )

    # --- Fallback: Haversine great-circle distances ---
    logger.info("Computing Haversine (great-circle) distance matrix for %d points.", n)
    return _build_haversine_matrix(locations)


def calculate_distance_matrix(
    depot: Dict,
    stops: List[Dict],
) -> Tuple[np.ndarray, Optional["nx.MultiDiGraph"], Optional[List[int]]]:
    """
    Legacy API consumed by ``quantum_driver.run_optimization_pipeline``.

    Combines *depot* + *stops* into a single point list, computes the
    distance matrix, and also returns the OSM graph ``G`` and snapped
    ``nodes`` (needed later by ``render_map``).

    Parameters
    ----------
    depot : dict
        Depot location with 'name', 'lat', 'lon'.
    stops : list[dict]
        Delivery stop locations.

    Returns
    -------
    tuple[np.ndarray, networkx.MultiDiGraph | None, list[int] | None]
        ``(distance_matrix, G, nodes)``
        - ``distance_matrix``: NxN integer numpy array (meters).
        - ``G``: The OSM graph, or ``None`` if Haversine fallback was used.
        - ``nodes``: Snapped OSM node IDs, or ``None`` on fallback.
    """
    points = [depot] + stops
    n = len(points)

    # --- Attempt OSMnx road-network routing ---
    if OSMNX_AVAILABLE:
        try:
            G = _download_graph(points)
            nodes = _snap_nodes(G, points)
            raw_matrix = _build_osmnx_matrix(G, nodes, points)

            # Convert to integer numpy array for backward compatibility
            dist_matrix = np.array(raw_matrix, dtype=int)
            return dist_matrix, G, nodes

        except Exception as exc:
            logger.warning(
                "OSMnx routing failed (%s). Falling back to Haversine.", exc
            )

    # --- Fallback: Haversine great-circle distances ---
    logger.info(
        "Computing Haversine distance matrix for %d points (fallback).", n
    )
    raw_matrix = _build_haversine_matrix(points)
    dist_matrix = np.array(raw_matrix, dtype=int)
    return dist_matrix, None, None


# ===================================================================== #
#                         MAP RENDERING                                  #
# ===================================================================== #


def render_map(
    route: List[int],
    points: List[Dict],
    G: Optional["nx.MultiDiGraph"],
    nodes: Optional[List[int]],
    filename: str,
    title: str,
    color: str,
) -> None:
    """
    Generate an interactive HTML map for a solved route using Folium.

    When the OSM graph *G* is available, the actual road geometry is drawn.
    Otherwise, straight lines connect consecutive stops.

    Parameters
    ----------
    route : list[int]
        Ordered indices into *points* representing the tour.
    points : list[dict]
        Location dicts with 'name', 'lat', 'lon'.
    G : networkx.MultiDiGraph or None
        The OSM graph (``None`` if Haversine fallback was used).
    nodes : list[int] or None
        Snapped OSM node IDs corresponding to *points*.
    filename : str
        Output path for the HTML map file.
    title : str
        Tooltip / legend label for the route polyline.
    color : str
        CSS color string for the route polyline.
    """
    # Center the map on the geographic centroid of all points
    center_lat = float(np.mean([p["lat"] for p in points]))
    center_lon = float(np.mean([p["lon"] for p in points]))
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles="CartoDB positron",
    )

    # --- Draw route polyline ---
    road_coords: List[Tuple[float, float]] = []

    if G is not None and nodes is not None:
        # Trace actual road geometry through the OSM graph
        for k in range(len(route) - 1):
            try:
                path_nodes = nx.shortest_path(
                    G, nodes[route[k]], nodes[route[k + 1]], weight="length"
                )
                road_coords.extend(
                    (G.nodes[nd]["y"], G.nodes[nd]["x"])
                    for nd in path_nodes
                    if nd in G.nodes
                )
            except Exception:
                # If a segment fails, skip it gracefully
                continue

    if road_coords:
        folium.PolyLine(
            road_coords, color=color, weight=5, opacity=0.8, tooltip=title
        ).add_to(m)
    else:
        # Straight-line fallback between consecutive tour stops
        straight_coords = [
            (points[idx]["lat"], points[idx]["lon"]) for idx in route
        ]
        folium.PolyLine(
            straight_coords, color=color, weight=5, opacity=0.8, tooltip=title
        ).add_to(m)

    # --- Place markers for each location ---
    for i, p in enumerate(points):
        folium.Marker(
            location=[p["lat"], p["lon"]],
            popup=p["name"],
            icon=folium.Icon(color="red" if i == 0 else "blue"),
        ).add_to(m)

    # Ensure parent directories exist before saving
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    m.save(filename)
    logger.info("Map saved → %s", filename)
