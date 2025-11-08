# main.py
from __future__ import annotations

from typing import Dict, Optional, List

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware  # ⬅️ NEW

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
from backend.config import GRAPH_PICKLE_PATH
from backend.live_weather import update_graph_weather


app = FastAPI(
    title="AI Captain Route Optimization API",
    version="0.1.0",
    description="API for maritime route optimization considering weather, piracy and other risk layers.",
)

# ───────────────────────────────
# CORS (allow your local frontends)
# ───────────────────────────────
ALLOWED_ORIGINS = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,   # during dev you could use ["*"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PORTS: Dict[str, Port] = {}
GRAPH = None
PIRACY_LAYER: Optional[RiskLayer] = None
WEATHER_LAYER: Optional[RiskLayer] = None


def init_app():
    global PORTS, GRAPH, PIRACY_LAYER, WEATHER_LAYER

    PORTS = load_ports_from_wpi()

    if GRAPH_PICKLE_PATH.exists():
        from backend.graph_builder import load_graph as _load_graph
        GRAPH = _load_graph()
    else:
        lat_range = (-10.0, 35.0)
        lon_range = (30.0, 65.0)
        GRAPH, PIRACY_LAYER, WEATHER_LAYER = build_grid_graph(lat_range, lon_range)
        save_graph(GRAPH)

    if PIRACY_LAYER is None or WEATHER_LAYER is None:
        PIRACY_LAYER = load_piracy_zones()
        WEATHER_LAYER = load_weather_zones()

    try:
        update_graph_weather(GRAPH)
    except Exception as exc:
        print(f"[WARN] Could not update live weather on startup: {exc}")


@app.on_event("startup")
async def startup_event():
    init_app()


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

    if WEATHER_LAYER and (type_list is None or "weather" in type_list):
        layers.append(WEATHER_LAYER)

    # TODO: filter by bbox if provided

    return RiskLayersResponse(layers=layers)


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
