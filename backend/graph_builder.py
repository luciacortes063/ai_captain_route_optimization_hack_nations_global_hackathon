# backend/graph_builder.py
from __future__ import annotations

from typing import Dict, Tuple

import networkx as nx
import numpy as np
from shapely.geometry import Point, Polygon

from backend.config import (
    GRID_LAT_STEP,
    GRID_LON_STEP,
    GRAPH_PICKLE_PATH,
)
from backend.data_sources import (
    load_bathymetry,
    load_piracy_zones,
    load_weather_zones,
    is_shallow,
    is_land,
)
from backend.models import RiskLayer
from backend.geopolitics import load_geopolitics_config
from haversine import haversine


def build_risk_polygons():
    """
    Precompute shapely polygons + levels for piracy and weather layers.
    Note: input polygons are [lat, lon]; shapely expects [lon, lat].
    """
    piracy_layer: RiskLayer = load_piracy_zones()
    weather_layer: RiskLayer = load_weather_zones()

    piracy_polygons = [
        (Polygon([[lon, lat] for lat, lon in feature.polygon]), feature.riskLevel or 3)
        for feature in piracy_layer.features
    ]
    weather_polygons = [
        (Polygon([[lon, lat] for lat, lon in feature.polygon]), feature.severity or 2)
        for feature in weather_layer.features
    ]

    return piracy_layer, weather_layer, piracy_polygons, weather_polygons


def compute_node_risks(
    lat: float,
    lon: float,
    piracy_polygons,
    weather_polygons,
    bathy_ds,
) -> Tuple[int, int, float]:
    """
    Return (piracy_risk, weather_risk, depth_penalty) for a single node.
    - piracy/weather: max value among polygons containing the point
    - depth_penalty: 1.0 if shallow, else 0.0
    """
    point = Point(lon, lat)

    piracy_risk = 0
    for poly, level in piracy_polygons:
        if poly.contains(point):
            piracy_risk = max(piracy_risk, level)

    weather_risk = 0
    for poly, sev in weather_polygons:
        if poly.contains(point):
            weather_risk = max(weather_risk, sev)

    shallow = is_shallow(bathy_ds, lat, lon)
    depth_penalty = 1.0 if shallow else 0.0

    return piracy_risk, weather_risk, depth_penalty


def build_grid_graph(
    lat_range: Tuple[float, float],
    lon_range: Tuple[float, float],
) -> Tuple[nx.Graph, RiskLayer, RiskLayer]:
    """
    Build a sea-grid graph with node attributes:
      - piracy_risk, weather_risk, depth_penalty
      - geo_base_risk, geo_target_flags (ISO3 → extra risk)
    Edges carry geodesic distance in nautical miles.
    """

    G = nx.Graph()
    bathy_ds = load_bathymetry()
    piracy_layer, weather_layer, piracy_polygons, weather_polygons = build_risk_polygons()

    # Geopolitics polygons + risk metadata
    geopolitics_layer, geopolitics_polygons, _aliases = load_geopolitics_config()

    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range

    lat_values = np.arange(lat_min, lat_max + GRID_LAT_STEP, GRID_LAT_STEP)
    lon_values = np.arange(lon_min, lon_max + GRID_LON_STEP, GRID_LON_STEP)

    # ── Nodes: only water cells; attach risks
    for lat in lat_values:
        for lon in lon_values:
            # skip land cells early
            if is_land(bathy_ds, float(lat), float(lon)):
                continue

            piracy_risk, weather_risk, depth_penalty = compute_node_risks(
                float(lat),
                float(lon),
                piracy_polygons,
                weather_polygons,
                bathy_ds,
            )

            point = Point(float(lon), float(lat))

            # Geopolitics at node: max base risk + max per-target extra
            geo_base_risk = 0.0
            geo_target_flags: Dict[str, float] = {}
            for poly, base_risk, target_flags, *_ in geopolitics_polygons:
                if poly.contains(point):
                    if base_risk > geo_base_risk:
                        geo_base_risk = base_risk
                    for iso3, extra in target_flags.items():
                        prev = geo_target_flags.get(iso3, 0.0)
                        if extra > prev:
                            geo_target_flags[iso3] = float(extra)

            node_id = f"{lat:.3f},{lon:.3f}"
            G.add_node(
                node_id,
                lat=float(lat),
                lon=float(lon),
                piracy_risk=piracy_risk,
                weather_risk=weather_risk,
                depth_penalty=depth_penalty,
                geo_base_risk=geo_base_risk,
                geo_target_flags=geo_target_flags,
            )

    # ── Edges: 4-neighborhood (N/S/E/W) with geodesic distance in NM
    for lat in lat_values:
        for lon in lon_values:
            node_id = f"{lat:.3f},{lon:.3f}"
            if node_id not in G.nodes:
                continue

            neighbors = [
                (lat + GRID_LAT_STEP, lon),
                (lat - GRID_LAT_STEP, lon),
                (lat, lon + GRID_LON_STEP),
                (lat, lon - GRID_LON_STEP),
            ]
            for n_lat, n_lon in neighbors:
                n_id = f"{n_lat:.3f},{n_lon:.3f}"
                if n_id in G.nodes:
                    p1 = (lat, lon)
                    p2 = (n_lat, n_lon)
                    dist_km = haversine(p1, p2)
                    dist_nm = dist_km * 0.539957
                    G.add_edge(node_id, n_id, distance_nm=dist_nm)

    return G, piracy_layer, weather_layer


def save_graph(G: nx.Graph):
    """Persist graph to disk (pickle)."""
    import pickle

    GRAPH_PICKLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GRAPH_PICKLE_PATH, "wb") as f:
        pickle.dump(G, f)


def load_graph() -> nx.Graph:
    """Load graph from disk (pickle)."""
    import pickle

    with open(GRAPH_PICKLE_PATH, "rb") as f:
        G: nx.Graph = pickle.load(f)
    return G
