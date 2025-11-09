from __future__ import annotations

from typing import Dict, Optional, List

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.models import (
    HealthResponse,
    PortsListResponse,
    PortsSearchResponse,
    Port,
    ErrorResponse,
    RouteRequest,
    RouteResponse,
    RiskLayersResponse,
    RiskLayer,
)
from backend.data_sources import (
    load_ports_from_wpi,
    load_piracy_zones,
    load_weather_zones,
)
from backend.graph_builder import load_graph, build_grid_graph, save_graph
from backend.routing import compute_route
from backend.config import GRAPH_PICKLE_PATH, AIS_LAT_RANGE, AIS_LON_RANGE
from backend.live_weather import update_graph_weather, build_weather_risk_layer
from backend.ais_traffic import update_graph_traffic_from_ais, build_traffic_layer_from_graph
from backend.geopolitics import load_geopolitics_config, apply_geopolitics_to_graph
from backend.safety_layer import build_safety_layer_from_graph






app = FastAPI(
    title="AI Captain Route Optimization API",
    version="0.1.0",
    description="API for maritime route optimization considering weather, piracy and other risk layers.",
)

# ───────────────────────────────
# CORS (allow local frontends)
# ───────────────────────────────
origins = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────
# Globals
# ───────────────────────────────
PORTS: Dict[str, Port] = {}
GRAPH = None
PIRACY_LAYER: Optional[RiskLayer] = None
WEATHER_LAYER: Optional[RiskLayer] = None
TRAFFIC_LAYER: Optional[RiskLayer] = None
WEATHER_LIVE_LAYER: Optional[RiskLayer] = None
GEOPOL_LAYER: Optional[RiskLayer] = None
SAFETY_LAYER: Optional[RiskLayer] = None



# ───────────────────────────────
# Init app (load graph, layers, live weather)
# ───────────────────────────────
def init_app():
    global PORTS, GRAPH, PIRACY_LAYER, WEATHER_LAYER, WEATHER_LIVE_LAYER, GEOPOL_LAYER, SAFETY_LAYER

    PORTS = load_ports_from_wpi()

    if GRAPH_PICKLE_PATH.exists():
        GRAPH = load_graph()
    else:
        lat_range = (-10.0, 35.0)
        lon_range = (30.0, 65.0)
        GRAPH, PIRACY_LAYER, WEATHER_LAYER = build_grid_graph(lat_range, lon_range)
        save_graph(GRAPH)

    if PIRACY_LAYER is None or WEATHER_LAYER is None:
        PIRACY_LAYER = load_piracy_zones()
        WEATHER_LAYER = load_weather_zones()

    # Geopolitics: capa + aplicar al grafo
    try:
        geop_layer, _, _ = load_geopolitics_config()
        GEOPOL_LAYER = geop_layer
        apply_geopolitics_to_graph(GRAPH)
        print("[INFO] Geopolitics layer loaded and applied to graph.")
    except Exception as exc:
        print(f"[WARN] Could not load/apply geopolitics config: {exc}")
        GEOPOL_LAYER = None

    try:
        update_graph_weather(GRAPH)
        WEATHER_LIVE_LAYER = build_weather_risk_layer(GRAPH)
        print("[INFO] Live weather layer built successfully.")
    except Exception as exc:
        print(f"[WARN] Could not update live weather on startup: {exc}")


    

@app.on_event("startup")
async def startup_event():
    global TRAFFIC_LAYER, SAFETY_LAYER

    # 1) Carga síncrona de todo (puertos, grafo, weather estática + live)
    init_app()

    # 2) Actualizar tráfico AIS y construir TRAFFIC_LAYER
    try:
        # Esto actualizará G.nodes[node]["traffic_risk"]
        await update_graph_traffic_from_ais(
            GRAPH,
            AIS_LAT_RANGE,
            AIS_LON_RANGE,
            duration_sec=60.0,   # ya lo tienes así por defecto, pero así es explícito
        )

        # Ahora construimos la capa agregada en forma de polígonos
        TRAFFIC_LAYER = build_traffic_layer_from_graph(GRAPH)
        print(f"[INFO] Traffic layer built. Features: {len(TRAFFIC_LAYER.features)}")

    except Exception as exc:
        print(f"[WARN] Could not update AIS traffic on startup: {exc}")
        TRAFFIC_LAYER = None

    try:
        SAFETY_LAYER = build_safety_layer_from_graph(GRAPH)
        print(f"[INFO] Safety layer built. Features: {len(SAFETY_LAYER.features)}")
    except Exception as exc:
        print(f"[WARN] Could not build safety layer: {exc}")
        SAFETY_LAYER = None


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    return HealthResponse(
        status="ok",
        graph_loaded=GRAPH is not None,
        version="0.1.0",
    )


@app.get("/ports", response_model=PortsListResponse, tags=["Ports"])
async def list_ports(
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
):
    ports_list: List[Port] = list(PORTS.values())
    total = len(ports_list)
    slice_ports = ports_list[offset : offset + limit]
    return PortsListResponse(
        ports=slice_ports,
        count=len(slice_ports),
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/ports/search", response_model=PortsSearchResponse, tags=["Ports"])
async def search_ports(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1),
):
    q_lower = q.lower()
    results: List[Port] = []
    for p in PORTS.values():
        if (
            q_lower in p.id.lower()
            or q_lower in p.name.lower()
            or q_lower in p.country.lower()
        ):
            results.append(p)
        if len(results) >= limit:
            break
    return PortsSearchResponse(ports=results)


@app.get(
    "/ports/{portId}",
    response_model=Port,
    responses={404: {"model": ErrorResponse}},
    tags=["Ports"],
)
async def get_port(portId: str):
    if portId not in PORTS:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                status="error",
                error="PORT_NOT_FOUND",
                message=f"Port with id '{portId}' not found",
            ).dict(),
        )
    return PORTS[portId]


@app.post(
    "/route",
    response_model=RouteResponse,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    tags=["Routing"],
)
async def route(request: RouteRequest):
    if GRAPH is None:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                status="error",
                error="GRAPH_NOT_LOADED",
                message="Routing graph is not loaded",
            ).dict(),
        )
    try:
        result = compute_route(GRAPH, request, PORTS)
        return result
    except ValueError as ve:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                status="error",
                error="INVALID_REQUEST",
                message=str(ve),
            ).dict(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                status="error",
                error="ROUTING_ERROR",
                message=str(e),
            ).dict(),
        )


@app.get("/risk-layers", response_model=RiskLayersResponse, tags=["Risk"])
async def risk_layers(
    types: Optional[str] = Query(
        None,
        description='Comma-separated list of risk layer types, e.g. "piracy,weather"',
    ),
    bbox: Optional[str] = Query(
        None,
        description='Optional bounding box "minLon,minLat,maxLon,maxLat".',
    ),
):
    type_list = None
    if types:
        type_list = [t.strip().lower() for t in types.split(",")]

    layers: List[RiskLayer] = []

    if PIRACY_LAYER and (type_list is None or "piracy" in type_list):
        layers.append(PIRACY_LAYER)

    # Serve the aggregated live weather layer as "weather"
    if WEATHER_LIVE_LAYER and (type_list is None or "weather" in type_list):
        layers.append(WEATHER_LIVE_LAYER)
    elif WEATHER_LAYER and (type_list is None or "weather" in type_list):
        layers.append(WEATHER_LAYER)

    # ⬇⬇⬇ NUEVO: capa de tráfico
    if TRAFFIC_LAYER and (type_list is None or "traffic" in type_list):
        layers.append(TRAFFIC_LAYER)

    if GEOPOL_LAYER and (type_list is None or "geopolitics" in type_list):
        layers.append(GEOPOL_LAYER)

    if SAFETY_LAYER and (type_list is None or "safety" in type_list):
        layers.append(SAFETY_LAYER)

    # TODO: filter by bbox if provided
    return RiskLayersResponse(layers=layers)



# ───────────────────────────────
# Run directly
# ───────────────────────────────

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
