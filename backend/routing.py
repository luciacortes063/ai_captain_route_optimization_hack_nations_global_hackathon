from __future__ import annotations

from typing import Dict, Tuple, List

import networkx as nx
from haversine import haversine

from backend.config import LAMBDA_PIRACY, LAMBDA_WEATHER, LAMBDA_DEPTH
from backend.models import (
    RouteRequest,
    RouteResponse,
    RouteSummary,
    RoutePath,
    RouteSegment,
    RouteExplanation,
    Port,
)


def find_closest_node(G: nx.Graph, lat: float, lon: float) -> str:
   
    best_node = None
    best_dist = float("inf")
    for node_id, data in G.nodes(data=True):
        n_lat, n_lon = data["lat"], data["lon"]
        d = haversine((lat, lon), (n_lat, n_lon))
        if d < best_dist:
            best_dist = d
            best_node = node_id
    return best_node


def get_coordinates_of_node(G: nx.Graph, node_id: str) -> Tuple[float, float]:
    data = G.nodes[node_id]
    return data["lat"], data["lon"]


def build_weight_function(mode: str, G: nx.Graph):

    if mode == "fast":
        lambda_p = LAMBDA_PIRACY * 0.2
        lambda_w = LAMBDA_WEATHER * 0.2
        lambda_d = LAMBDA_DEPTH * 0.5
    elif mode == "safe":
        lambda_p = LAMBDA_PIRACY * 2.0
        lambda_w = LAMBDA_WEATHER * 2.0
        lambda_d = LAMBDA_DEPTH * 3.0
    else:  # balanced
        lambda_p = LAMBDA_PIRACY
        lambda_w = LAMBDA_WEATHER
        lambda_d = LAMBDA_DEPTH


    def weight(u: str, v: str, attrs: dict) -> float:
        dist_nm = attrs.get("distance_nm", 1.0)
 
        piracy_u = G.nodes[u]["piracy_risk"]
        piracy_v = G.nodes[v]["piracy_risk"]
        weather_u = G.nodes[u]["weather_risk"]
        weather_v = G.nodes[v]["weather_risk"]
        depth_u = G.nodes[u]["depth_penalty"]
        depth_v = G.nodes[v]["depth_penalty"]

        piracy_avg = (piracy_u + piracy_v) / 2.0
        weather_avg = (weather_u + weather_v) / 2.0
        depth_avg = (depth_u + depth_v) / 2.0

        cost = (
            dist_nm
            + lambda_p * piracy_avg
            + lambda_w * weather_avg
            + lambda_d * depth_avg
        )
        return cost

    return weight


def compute_route(
    G: nx.Graph,
    route_request: RouteRequest,
    ports: Dict[str, Port],
    default_speed_knots: float = 20.0,
) -> RouteResponse:

    origin_lat, origin_lon = _resolve_origin_or_destination(
        route_request.origin, ports
    )
    dest_lat, dest_lon = _resolve_origin_or_destination(
        route_request.destination, ports
    )

    origin_node = find_closest_node(G, origin_lat, origin_lon)
    dest_node = find_closest_node(G, dest_lat, dest_lon)

    weight_fn = build_weight_function(route_request.mode, G)
    path_nodes: List[str] = nx.shortest_path(G, origin_node, dest_node, weight=weight_fn)


    coordinates: List[List[float]] = []
    segments: List[RouteSegment] = []

    total_distance_nm = 0.0
    total_piracy = 0.0
    total_weather = 0.0
    total_depth_penalty = 0.0

    last_lat, last_lon = None, None

    for idx, node_id in enumerate(path_nodes):
        lat, lon = get_coordinates_of_node(G, node_id)
        coordinates.append([lat, lon])

        if idx > 0:
            segment_distance_nm = G[path_nodes[idx - 1]][node_id]["distance_nm"]
   
            piracy_avg = (
                G.nodes[path_nodes[idx - 1]]["piracy_risk"] + G.nodes[node_id]["piracy_risk"]
            ) / 2.0
            weather_avg = (
                G.nodes[path_nodes[idx - 1]]["weather_risk"] + G.nodes[node_id]["weather_risk"]
            ) / 2.0
            depth_avg = (
                G.nodes[path_nodes[idx - 1]]["depth_penalty"] + G.nodes[node_id]["depth_penalty"]
            ) / 2.0

            total_distance_nm += segment_distance_nm
            total_piracy += piracy_avg
            total_weather += weather_avg
            total_depth_penalty += depth_avg

            segment = RouteSegment(
                **{
                    "from": [last_lat, last_lon],
                    "to": [lat, lon],
                    "distanceNm": segment_distance_nm,
                    "weatherRisk": weather_avg,
                    "piracyRisk": piracy_avg,
                    "depthPenalty": depth_avg,
                }
            )
            segments.append(segment)

        last_lat, last_lon = lat, lon

    # Estimated duration in hours = distancia_nm / knots
    estimated_duration_hours = total_distance_nm / default_speed_knots

    origin_port_id = route_request.origin.portId if route_request.origin.type == "port" else None
    dest_port_id = (
        route_request.destination.portId if route_request.destination.type == "port" else None
    )

    summary = RouteSummary(
        originPortId=origin_port_id,
        destinationPortId=dest_port_id,
        mode=route_request.mode,
        totalDistanceNm=total_distance_nm,
        estimatedDurationHours=estimated_duration_hours,
        totalWeatherRisk=total_weather,
        totalPiracyRisk=total_piracy,
        totalDepthPenalty=total_depth_penalty,
    )

    explanation = build_explanation(summary, route_request.mode)

    path = RoutePath(
        coordinates=coordinates,
        segments=segments,
    )

    response = RouteResponse(
        status="ok",
        summary=summary,
        path=path,
        explanation=explanation,
    )
    return response


def _resolve_origin_or_destination(
    od,
    ports: Dict[str, Port],
) -> Tuple[float, float]:
    if od.type == "port":
        if od.portId not in ports:
            raise ValueError(f"Port {od.portId} not found")
        p = ports[od.portId]
        return p.latitude, p.longitude
    else:
        if od.latitude is None or od.longitude is None:
            raise ValueError("Latitude/longitude required for coordinates type")
        return od.latitude, od.longitude


def build_explanation(summary: RouteSummary, mode: str) -> RouteExplanation:
    high_level: List[str] = []
    tradeoffs: List[str] = []

    if mode == "safe":
        high_level.append(
            "Route prioritizes safety, avoiding high piracy and severe weather areas."
        )
    elif mode == "fast":
        high_level.append(
            "Route prioritizes speed, allowing higher exposure to risk zones where necessary."
        )
    else:
        high_level.append(
            "Route balances speed and safety, avoiding the most severe risk areas while keeping distance reasonable."
        )

    if summary.totalPiracyRisk > 0:
        high_level.append(
            f"Total piracy exposure along the route is {summary.totalPiracyRisk:.1f} (normalized units)."
        )

    if summary.totalWeatherRisk > 0:
        high_level.append(
            f"Total weather risk along the route is {summary.totalWeatherRisk:.1f} (normalized units)."
        )

    if summary.totalDepthPenalty > 0:
        high_level.append("Route passes near shallow waters, which may restrict drafts.")

    tradeoffs.append(
        f"Estimated distance is {summary.totalDistanceNm:.1f} nm with an ETA of about {summary.estimatedDurationHours:.1f} hours at 20 knots."
    )

    if mode == "safe":
        tradeoffs.append(
            "The chosen route may be longer than the shortest possible path in order to reduce exposure to risk."
        )
    elif mode == "fast":
        tradeoffs.append(
            "The chosen route may cross higher-risk regions to shorten distance and time."
        )

    return RouteExplanation(
        highLevel=high_level,
        tradeoffs=tradeoffs,
    )
