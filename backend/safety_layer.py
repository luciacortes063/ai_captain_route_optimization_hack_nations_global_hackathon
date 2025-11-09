# backend/safety_layer.py
from __future__ import annotations

from typing import Dict, Tuple, List
import math

from backend.models import RiskLayer, RiskFeature
from backend.config import GRID_LAT_STEP, GRID_LON_STEP


def _cell_for_latlon(lat: float, lon: float) -> Tuple[float, float]:
    """
    Snap (lat, lon) to the graph's grid so we can paint each grid cell
    as a small rectangle on the safety map.
    """
    cell_lat = round(lat / GRID_LAT_STEP) * GRID_LAT_STEP
    cell_lon = round(lon / GRID_LON_STEP) * GRID_LON_STEP
    return cell_lat, cell_lon


def build_safety_layer_from_graph(G) -> RiskLayer:
    """
    Build an aggregated "safety map" layer from node attributes:
      - piracy_risk
      - weather_risk
      - depth_penalty
      - traffic_risk
      - geo_base_risk

    Returns a RiskLayer(type="safety") with severity 1..5 for ALL sea cells
    (not only where risk > 0).
    """

    # 1) Aggregate raw risk per grid cell (include zeros to cover all sea)
    buckets: Dict[Tuple[float, float], List[float]] = {}

    for _, data in G.nodes(data=True):
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            continue

        piracy = float(data.get("piracy_risk", 0.0))
        weather = float(data.get("weather_risk", 0.0))
        depth = float(data.get("depth_penalty", 0.0))
        traffic = float(data.get("traffic_risk", 0.0))
        geo = float(data.get("geo_base_risk", 0.0))

        # Weighted combination (tune as needed):
        # - heavier weight on piracy/geopolitics
        # - medium weight on traffic/depth
        # - weather smoothed down
        risk_raw = (
            piracy * 3.0 +
            geo * 3.0 +
            traffic * 2.0 +
            depth * 2.0 +
            weather * 0.5
        )

        if not math.isfinite(risk_raw):
            continue

        cell = _cell_for_latlon(float(lat), float(lon))
        buckets.setdefault(cell, []).append(risk_raw)

    if not buckets:
        return RiskLayer(type="safety", name="Aggregated Safety Map", features=[])

    # 2) Mean risk per cell + track global min/max for normalization
    cell_scores: Dict[Tuple[float, float], float] = {}
    max_score = -1e9
    min_score = 1e9

    for cell, vals in buckets.items():
        avg = sum(vals) / len(vals)
        cell_scores[cell] = avg
        if avg > max_score:
            max_score = avg
        if avg < min_score:
            min_score = avg

    # 3) Build rectangular polygons for a heatmap effect
    half_lat = GRID_LAT_STEP / 2.0
    half_lon = GRID_LON_STEP / 2.0

    features: List[RiskFeature] = []
    idx = 0

    if max_score <= min_score:
        # Edge case: uniform risk → assign mid severity (3) everywhere
        for (cell_lat, cell_lon) in cell_scores.keys():
            lat_min = cell_lat - half_lat
            lat_max = cell_lat + half_lat
            lon_min = cell_lon - half_lon
            lon_max = cell_lon + half_lon

            polygon = [
                [lat_min, lon_min],
                [lat_min, lon_max],
                [lat_max, lon_max],
                [lat_max, lon_min],
                [lat_min, lon_min],
            ]
            features.append(
                RiskFeature(
                    id=f"safety_{idx}",
                    polygon=polygon,
                    riskLevel=None,
                    severity=3,
                )
            )
            idx += 1
    else:
        # Map min..max → severity 1..5 (linear)
        span = max_score - min_score
        for (cell_lat, cell_lon), score in cell_scores.items():
            norm = (score - min_score) / span  # 0..1
            sev = 1 + int(round(norm * 4.0))
            if sev < 1:
                sev = 1
            if sev > 5:
                sev = 5

            lat_min = cell_lat - half_lat
            lat_max = cell_lat + half_lat
            lon_min = cell_lon - half_lon
            lon_max = cell_lon + half_lon

            polygon = [
                [lat_min, lon_min],
                [lat_min, lon_max],
                [lat_max, lon_max],
                [lat_max, lon_min],
                [lat_min, lon_min],
            ]
            features.append(
                RiskFeature(
                    id=f"safety_{idx}",
                    polygon=polygon,
                    riskLevel=None,
                    severity=sev,
                )
            )
            idx += 1

    return RiskLayer(
    type="safety",
    name="Aggregated Safety Map",
    features=features,
)
