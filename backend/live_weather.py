from __future__ import annotations

from typing import Optional, Tuple, Dict
import math
import logging

import networkx as nx
import requests

from backend.config import (
    WEATHER_API_BASE_URL,
    WEATHER_CELL_SIZE_DEG,
    WAVE_HEIGHT_THRESHOLDS_M,
    WIND_SPEED_THRESHOLD_MS,
    WEATHER_WAVE_WEIGHT,
    WEATHER_WIND_WEIGHT,
)

logger = logging.getLogger(__name__)

MAX_WEATHER_CELLS = 10000


def _cell_for_latlon(lat: float, lon: float) -> Tuple[float, float]:
    """Bucket coordinates into cells to reduce API calls."""
    cell_lat = round(lat / WEATHER_CELL_SIZE_DEG) * WEATHER_CELL_SIZE_DEG
    cell_lon = round(lon / WEATHER_CELL_SIZE_DEG) * WEATHER_CELL_SIZE_DEG
    return cell_lat, cell_lon


def _first_valid_float(seq) -> Optional[float]:
    """Return the first element in seq that can be cast to float; else None."""
    if not seq:
        return None
    for x in seq:
        if x is None:
            continue
        try:
            return float(x)
        except (TypeError, ValueError):
            continue
    return None


def fetch_wave_wind_for_cell(cell_lat: float, cell_lon: float) -> Tuple[Optional[float], Optional[float]]:
    """
    Fetch wave height (m) and 10m wind speed (m/s) at the cell center using Open-Meteo Marine.
    """
    params = {
        "latitude": cell_lat,
        "longitude": cell_lon,
        "hourly": "wave_height,wind_speed_10m",
        "forecast_hours": 1,
        "cell_selection": "sea",
    }
    try:
        resp = requests.get(WEATHER_API_BASE_URL, params=params, timeout=10)
        if resp.status_code == 429:
            logger.warning(f"[weather] Rate limit (429) for cell ({cell_lat}, {cell_lon})")
            return None, None
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"[weather] Error fetching marine data for cell ({cell_lat}, {cell_lon}): {exc}")
        return None, None

    hourly = data.get("hourly", {})
    wave = hourly.get("wave_height")
    wind = hourly.get("wind_speed_10m")

    wave_val = _first_valid_float(wave)
    wind_val = _first_valid_float(wind)

    return wave_val, wind_val


def continuous_weather_penalty(wave_m: Optional[float], wind_ms: Optional[float]) -> float:
    """
    Smooth penalty (>=0):
      - starts increasing when waves exceed threshold_1
      - starts increasing when wind exceeds WIND_SPEED_THRESHOLD_MS
    """
    penalty = 0.0
    # Waves
    wave_thr_start, _ = WAVE_HEIGHT_THRESHOLDS_M
    if wave_m is not None and wave_m > wave_thr_start:
        penalty += WEATHER_WAVE_WEIGHT * (wave_m - wave_thr_start)
    # Wind
    if wind_ms is not None and wind_ms > WIND_SPEED_THRESHOLD_MS:
        penalty += WEATHER_WIND_WEIGHT * (wind_ms - WIND_SPEED_THRESHOLD_MS)

    # Guard against NaNs/infs
    if not math.isfinite(penalty) or penalty < 0:
        return 0.0
    return penalty


def update_graph_weather(G: nx.Graph) -> None:
    """
    Updates per-node 'weather_risk' as a continuous penalty using wave + wind.
    Routing already averages node risks along edges, so no other changes needed.
    """
    # 1) Group nodes into cells to minimize API calls
    cells: Dict[Tuple[float, float], list[str]] = {}
    for node_id, data in G.nodes(data=True):
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            continue
        cell = _cell_for_latlon(lat, lon)
        cells.setdefault(cell, []).append(node_id)

    # 2) Randomize and cap number of cells (demo/perf)
    cell_items = list(cells.items())

    logger.info(f"[weather] Updating weather risk (wave+wind continuous) for {len(cell_items)} cells")

    # 3) Fetch per-cell; assign penalty to nodes in that cell
    for (cell_lat, cell_lon), node_ids in cell_items:
        wave_m, wind_ms = fetch_wave_wind_for_cell(cell_lat, cell_lon)
        penalty = continuous_weather_penalty(wave_m, wind_ms)
        for node_id in node_ids:
            G.nodes[node_id]["weather_risk"] = penalty

    logger.info("[weather] Weather risk update complete")

def _circle_polygon_latlon(center_lat: float, center_lon: float, radius_deg: float, n: int = 28):
    import math
    pts = []
    for i in range(n+1):
        a = 2*math.pi * i / n
        pts.append([center_lat + radius_deg*math.sin(a),
                    center_lon + radius_deg*math.cos(a)])
    return pts

def build_weather_risk_layer(G: nx.Graph, max_cells: int = 300, scale: float = 18.0):
    from backend.models import RiskLayer, RiskFeature
    from backend.config import WEATHER_CELL_SIZE_DEG

    # Aggregate risk by fetch cell
    buckets = {}  # (clat, clon) -> [risk...]
    for _, d in G.nodes(data=True):
        lat, lon = d.get("lat"), d.get("lon")
        if lat is None or lon is None:
            continue
        risk = float(d.get("weather_risk", 0.0))
        key = (
            round(lat / WEATHER_CELL_SIZE_DEG) * WEATHER_CELL_SIZE_DEG,
            round(lon / WEATHER_CELL_SIZE_DEG) * WEATHER_CELL_SIZE_DEG,
        )
        buckets.setdefault(key, []).append(risk)

    cells = []
    for (clat, clon), vals in buckets.items():
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        if avg <= 0.0:        
            continue
        cells.append((avg, clat, clon))

    cells.sort(reverse=True)
    cells = cells[:max_cells]

    radius_deg = WEATHER_CELL_SIZE_DEG / 2.2
    features = []
    for avg, clat, clon in cells:
        sev = int(min(5, max(1, round(avg * scale))))  # map risk→1..5 (no forced 1 for zero because we filtered)
        poly = _circle_polygon_latlon(clat, clon, radius_deg, n=28)
        features.append(
            RiskFeature(
                id=f"wx_{clat:.2f}_{clon:.2f}",
                polygon=poly,
                riskLevel=None,
                severity=sev,
            )
        )

    return RiskLayer(
        type="weather",  
        name="Live Weather (aggregated, circular)",
        features=features,
    )
