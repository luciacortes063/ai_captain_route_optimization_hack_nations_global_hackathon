from __future__ import annotations

from typing import Dict, Tuple, Optional
import asyncio
import json
import logging
import time

import networkx as nx
import websockets  # pip install websockets

from backend.config import (
    TRAFFIC_CELL_SIZE_DEG,
    AISSTREAM_API_KEY,
)
from backend.models import RiskLayer, RiskFeature


logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"


def _cell_for_latlon(lat: float, lon: float) -> Tuple[float, float]:
    """
    Agrupa coordenadas en celdas de tamaño TRAFFIC_CELL_SIZE_DEG.
    """
    cell_lat = round(lat / TRAFFIC_CELL_SIZE_DEG) * TRAFFIC_CELL_SIZE_DEG
    cell_lon = round(lon / TRAFFIC_CELL_SIZE_DEG) * TRAFFIC_CELL_SIZE_DEG
    return cell_lat, cell_lon


def vessel_count_to_risk(count: Optional[int]) -> int:
    if count is None or count <= 0:
        return 0
    if count < 3:  
        return 1
    elif count < 10:   
        return 2
    else:              
        return 3


async def _collect_traffic_snapshot_async(
    lat_range: Tuple[float, float],
    lon_range: Tuple[float, float],
    duration_sec: float = 60.0,
) -> Dict[Tuple[float, float], int]:

    if not AISSTREAM_API_KEY:
        logger.warning("[traffic] AISSTREAM_API_KEY not set; skipping AIS traffic snapshot.")
        return {}

    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range


    bbox = [[lat_max, lon_min], [lat_min, lon_max]]

    subscribe_message = {
        "APIKey": AISSTREAM_API_KEY,
        "BoundingBoxes": [bbox],
        "FilterMessageTypes": [
            "PositionReport",
            "ExtendedClassBPositionReport",
            "StandardClassBPositionReport",
        ],
    }

    logger.info(f"[traffic] Connecting to AISStream for bbox {bbox} ...")

    mmsi_to_cell: Dict[str, Tuple[float, float]] = {}

    start_time = time.time()

    try:
        async with websockets.connect(AISSTREAM_URL) as websocket:
            await websocket.send(json.dumps(subscribe_message))

            while True:
                now = time.time()
                if now - start_time > duration_sec:
                    break

                try:
                    message_json = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                except asyncio.TimeoutError:

                    continue

                message = json.loads(message_json)
                msg_type = message.get("MessageType")

                if msg_type not in (
                    "PositionReport",
                    "ExtendedClassBPositionReport",
                    "StandardClassBPositionReport",
                ):
                    continue

                metadata = message.get("MetaData", {}) or {}
                lat = metadata.get("latitude")
                lon = metadata.get("longitude")
                mmsi = metadata.get("MMSI")

                if lat is None or lon is None or mmsi is None:
                    continue

                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                except (TypeError, ValueError):
                    continue

                if not (lat_min <= lat_f <= lat_max and lon_min <= lon_f <= lon_max):
                    continue

                cell = _cell_for_latlon(lat_f, lon_f)
                mmsi_str = str(mmsi)
                mmsi_to_cell[mmsi_str] = cell

    except Exception as exc:
        logger.warning(f"[traffic] Error while collecting AIS traffic snapshot: {exc}")
        return {}

    # Contar cuántos MMSI distintos hay en cada celda
    cell_counts: Dict[Tuple[float, float], int] = {}
    for cell in mmsi_to_cell.values():
        cell_counts[cell] = cell_counts.get(cell, 0) + 1

    logger.info(
        f"[traffic] Snapshot collected: {len(mmsi_to_cell)} unique ships "
        f"in {len(cell_counts)} cells."
    )
    return cell_counts


async def update_graph_traffic_from_ais(
    G: nx.Graph,
    lat_range: Tuple[float, float],
    lon_range: Tuple[float, float],
    duration_sec: float = 60.0,
) -> None:

    logger.info("[traffic] Starting AIS traffic snapshot to update graph...")
    cell_counts = await _collect_traffic_snapshot_async(lat_range, lon_range, duration_sec)

    if not cell_counts:
        logger.info("[traffic] No traffic data collected; leaving traffic_risk at default (0).")
        for node_id in G.nodes:
            if "traffic_risk" not in G.nodes[node_id]:
                G.nodes[node_id]["traffic_risk"] = 0
        return

    updated_nodes = 0
    for node_id, data in G.nodes(data=True):
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            continue
        cell = _cell_for_latlon(float(lat), float(lon))
        count = cell_counts.get(cell, 0)
        risk = vessel_count_to_risk(count)
        G.nodes[node_id]["traffic_risk"] = risk
        updated_nodes += 1

    logger.info(f"[traffic] Updated traffic_risk for {updated_nodes} nodes.")


def build_traffic_layer_from_graph(G: nx.Graph) -> RiskLayer:
    """
    Construye un RiskLayer 'traffic' a partir de traffic_risk en los nodos del grafo.
    Cada celda de tráfico es un rectángulo (polígono) alrededor del centro de la celda.
    """
    # 1) Agrupar por celda y quedarnos con el riesgo máximo de esa celda
    cell_risks: Dict[Tuple[float, float], int] = {}

    for node_id, data in G.nodes(data=True):
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            continue

        cell = _cell_for_latlon(float(lat), float(lon))
        risk = int(data.get("traffic_risk", 0))
        if risk <= 0:
            continue

        prev = cell_risks.get(cell, 0)
        if risk > prev:
            cell_risks[cell] = risk

    features: list[RiskFeature] = []
    half = TRAFFIC_CELL_SIZE_DEG / 2.0
    idx = 0

    # 2) Crear un polígono rectangular por celda con riesgo > 0
    for (cell_lat, cell_lon), risk in cell_risks.items():
        lat_min = cell_lat - half
        lat_max = cell_lat + half
        lon_min = cell_lon - half
        lon_max = cell_lon + half

        polygon = [
            [lat_min, lon_min],
            [lat_min, lon_max],
            [lat_max, lon_max],
            [lat_max, lon_min],
            [lat_min, lon_min],
        ]

        features.append(
            RiskFeature(
                id=f"traffic_{idx}",
                polygon=polygon,
                riskLevel=risk,
                severity=None,
            )
        )
        idx += 1

    return RiskLayer(
        type="traffic",
        name="Live vessel traffic density",
        features=features,
    )
