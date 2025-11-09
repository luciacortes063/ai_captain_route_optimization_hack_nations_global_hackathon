# models.py
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(example="ok")
    graph_loaded: bool = Field(example=True)
    version: str = Field(example="0.1.0")


class Port(BaseModel):
    id: str
    name: str
    country: str
    latitude: float
    longitude: float


class PortsListResponse(BaseModel):
    ports: List[Port]
    count: int
    total: int
    limit: int
    offset: int


class PortsSearchResponse(BaseModel):
    ports: List[Port]


class ErrorResponse(BaseModel):
    status: str = "error"
    error: str
    message: str


class OriginDestination(BaseModel):
    type: Literal["port", "coordinates"]
    portId: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class RouteConstraints(BaseModel):
    maxDraftMeters: Optional[float] = None
    maxPiracyRisk: Optional[int] = None
    departureTime: Optional[str] = None  


class RouteRequest(BaseModel):
    origin: OriginDestination
    destination: OriginDestination
    mode: Literal["safe", "fast", "balanced"]
    constraints: Optional[RouteConstraints] = None


class RouteSummary(BaseModel):
    originPortId: Optional[str] = None
    destinationPortId: Optional[str] = None
    mode: Literal["safe", "fast", "balanced"]
    totalDistanceNm: float
    estimatedDurationHours: float

    # Normalized risks along the routes
    totalWeatherRisk: float
    totalPiracyRisk: float
    totalDepthPenalty: float
    totalTrafficRisk: float
    totalGeopoliticalRisk: float



class RouteSegment(BaseModel):
    from_: List[float] = Field(..., alias="from", min_items=2, max_items=2)
    to: List[float] = Field(..., min_items=2, max_items=2)
    distanceNm: float
    weatherRisk: float
    piracyRisk: float
    depthPenalty: float

    class Config:
        allow_population_by_field_name = True


class RoutePath(BaseModel):
    coordinates: List[List[float]]
    segments: List[RouteSegment]


class RouteExplanation(BaseModel):
    highLevel: List[str]
    tradeoffs: List[str]


class RouteResponse(BaseModel):
    status: str
    summary: RouteSummary
    path: RoutePath
    explanation: RouteExplanation


class RiskFeature(BaseModel):
    id: str
    polygon: List[List[float]]
    riskLevel: Optional[int] = None
    severity: Optional[int] = None


class RiskLayer(BaseModel):
    type: str
    name: str
    features: List[RiskFeature]


class RiskLayersResponse(BaseModel):
    layers: List[RiskLayer]
