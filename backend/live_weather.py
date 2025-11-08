# live_weather.py
from __future__ import annotations

from typing import Optional, Tuple, Dict
import math
import logging
import random  

import networkx as nx
import requests

from backend.config import (
    WEATHER_API_BASE_URL,
    WEATHER_CELL_SIZE_DEG,
    WAVE_HEIGHT_THRESHOLDS_M,
)

logger = logging.getLogger(__name__)

MAX_WEATHER_CELLS = 50


def _cell_for_latlon(lat: float, lon: float) -> Tuple[float, float]:
    """
    Groups coordinates in cells of size WEATHER_CELL_SIZE_DEG to reduce the number of calls to the API
    """
    cell_lat = round(lat / WEATHER_CELL_SIZE_DEG) * WEATHER_CELL_SIZE_DEG
    cell_lon = round(lon / WEATHER_CELL_SIZE_DEG) * WEATHER_CELL_SIZE_DEG
    return cell_lat, cell_lon


def fetch_wave_height_for_cell(cell_lat: float, cell_lon: float) -> Optional[float]:
    """
    Calls the API Marine from Open-Meteo to fethc the wave height in the middle of the cell. 
    """
    params = {
        "latitude": cell_lat,
        "longitude": cell_lon,
        "hourly": "wave_height",
        "forecast_hours": 1,
        "cell_selection": "sea",
    }

    try:
        resp = requests.get(WEATHER_API_BASE_URL, params=params, timeout=10)
       
        if resp.status_code == 429:
            logger.warning(
                f"[weather] Rate limit (429) for cell ({cell_lat}, {cell_lon})"
            )
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(
            f"[weather] Error fetching marine data for cell ({cell_lat}, {cell_lon}): {exc}"
        )
        return None

    hourly = data.get("hourly", {})
    wave_heights = hourly.get("wave_height")
    if not wave_heights:
        return None

    try:
        return float(wave_heights[0])
    except Exception:
        return None


def wave_height_to_risk(wave_height_m: Optional[float]) -> int:
    """
    Converts wave height (m) into a discrete risk level:
      0 = good
      1 = moderate
      2 = severe
    """
    if wave_height_m is None or math.isnan(wave_height_m):
        return 0

    t1, t2 = WAVE_HEIGHT_THRESHOLDS_M
    if wave_height_m < t1:
        return 0
    elif wave_height_m < t2:
        return 1
    else:
        return 2


def update_graph_weather(G: nx.Graph) -> None:


    cells: Dict[Tuple[float, float], list[str]] = {}
    for node_id, data in G.nodes(data=True):
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            continue
        cell = _cell_for_latlon(lat, lon)
        cells.setdefault(cell, []).append(node_id)

    cell_items = list(cells.items())
    random.shuffle(cell_items)  

  
    cell_items = cell_items[:MAX_WEATHER_CELLS]

    logger.info(f"[weather] Updating weather risk for {len(cell_items)} cells")

    for (cell_lat, cell_lon), node_ids in cell_items:
        wave_height = fetch_wave_height_for_cell(cell_lat, cell_lon)
        risk = wave_height_to_risk(wave_height)

        for node_id in node_ids:
            G.nodes[node_id]["weather_risk"] = risk

    logger.info("[weather] Weather risk update finished")
