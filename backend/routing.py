from __future__ import annotations

from typing import Dict, Tuple, List

import networkx as nx
from haversine import haversine

from backend.config import LAMBDA_PIRACY, LAMBDA_WEATHER, LAMBDA_DEPTH, LAMBDA_TRAFFIC, LAMBDA_GEO
from backend.models import (
    RouteRequest,
    RouteResponse,
    RouteSummary,
    RoutePath,
    RouteSegment,
    RouteExplanation,
    Port,
)
from backend.geopolitics import infer_vessel_iso3_from_origin_country, get_zone_metadata


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


def _infer_vessel_iso3(route_request: RouteRequest, ports: Dict[str, Port]) -> str | None:
    """
    Asume que el barco está afiliado al país del puerto de origen.
    Usa los country_aliases definidos en geopolitics_config.geojson.
    """
    if route_request.origin.type != "port":
        return None
    if not route_request.origin.portId:
        return None
    origin_port = ports.get(route_request.origin.portId)
    if not origin_port:
        return None
    return infer_vessel_iso3_from_origin_country(origin_port.country)


def build_weight_function(mode: str, G: nx.Graph, vessel_iso3: str | None):

    if mode == "fast":
        lambda_p = 0.0
        lambda_w = 0.0
        lambda_d = 1.0
        lambda_t = 0.5
        lambda_geo = 0.0
    elif mode == "safe":
        lambda_p = 50.0
        lambda_w = 6.0
        lambda_d = 30.0
        lambda_t = 10.0
        lambda_geo = 50.0
    else:  # balanced
        lambda_p = 10.0
        lambda_w = 3.0
        lambda_d = 10.0
        lambda_t = 4.0
        lambda_geo = 4.0

    def geopolitical_node_penalty(node_id: str) -> float:
        node_data = G.nodes[node_id]
        base = float(node_data.get("geo_base_risk", 0.0))
        if vessel_iso3 is None:
            return base
        extras = node_data.get("geo_target_flags", {}) or {}
        extra = float(extras.get(vessel_iso3, 0.0))
        return base + extra

    def weight(u: str, v: str, attrs: dict) -> float:
        dist_nm = attrs.get("distance_nm", 1.0)

        piracy_u = G.nodes[u]["piracy_risk"]
        piracy_v = G.nodes[v]["piracy_risk"]
        weather_u = G.nodes[u]["weather_risk"]
        weather_v = G.nodes[v]["weather_risk"]
        depth_u = G.nodes[u]["depth_penalty"]
        depth_v = G.nodes[v]["depth_penalty"]
        traffic_u = G.nodes[u].get("traffic_risk", 0)
        traffic_v = G.nodes[v].get("traffic_risk", 0)

        geo_u = geopolitical_node_penalty(u)
        geo_v = geopolitical_node_penalty(v)

        piracy_avg = (piracy_u + piracy_v) / 2.0
        weather_avg = (weather_u + weather_v) / 2.0
        depth_avg = (depth_u + depth_v) / 2.0
        traffic_avg = (traffic_u + traffic_v) / 2.0
        geo_avg = (geo_u + geo_v) / 2.0

        cost = (
            dist_nm
            + lambda_p * piracy_avg
            + lambda_w * weather_avg
            + lambda_d * depth_avg
            + lambda_t * traffic_avg
            + lambda_geo * geo_avg
        )
        return cost

    return weight


def build_explanation(summary: RouteSummary, mode: str, route_alerts: List[str] | None = None) -> RouteExplanation:
    high_level: List[str] = []
    tradeoffs: List[str] = []

    if mode == "safe":
        high_level.append(
            "Route prioritizes safety, avoiding high piracy and severe weather areas, as well as conflict-affected geopolitical zones."
        )
    elif mode == "fast":
        high_level.append(
            "Route prioritizes speed, allowing higher exposure to risk zones where necessary, including some geopolitical tension areas."
        )
    else:
        high_level.append(
            "Route balances speed and safety, avoiding the most severe risk areas (piracy, weather and geopolitical) while keeping distance reasonable."
        )

    if summary.totalPiracyRisk > 0:
        high_level.append(
            f"Average piracy exposure along the route is {summary.totalPiracyRisk:.2f} (0–3 scale)."
        )

    if summary.totalWeatherRisk > 0:
        high_level.append(
            f"Average weather risk along the route is {summary.totalWeatherRisk:.2f} (relative units)."
        )

    if summary.totalTrafficRisk > 0:
        high_level.append(
            f"Average traffic density risk along the route is {summary.totalTrafficRisk:.2f} (0–3 scale)."
        )

    if summary.totalGeopoliticalRisk > 0:
        high_level.append(
            f"Average geopolitical tension exposure along the route is {summary.totalGeopoliticalRisk:.2f} (relative units)."
        )

    if summary.totalDepthPenalty > 0:
        high_level.append("Route passes near shallow waters, which may restrict drafts.")

    tradeoffs.append(
        f"Estimated distance is {summary.totalDistanceNm:.1f} nm with an ETA of about {summary.estimatedDurationHours:.1f} hours at 20 knots."
    )

    if mode == "safe":
        tradeoffs.append(
            "The chosen route may be longer than the shortest possible path in order to reduce exposure to piracy, bad weather, heavy traffic and geopolitical tension zones."
        )
    elif mode == "fast":
        tradeoffs.append(
            "The chosen route may cross higher-risk regions (including geopolitical tension zones and busy choke points) to shorten distance and time."
        )

    # Añadimos las alertas como líneas separadas (el frontend las mostrará como pills)
    if route_alerts:
        for alert in route_alerts:
            tradeoffs.append(alert)

    return RouteExplanation(
        highLevel=high_level,
        tradeoffs=tradeoffs,
    )


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

    vessel_iso3 = _infer_vessel_iso3(route_request, ports)
    weight_fn = build_weight_function(route_request.mode, G, vessel_iso3)

    path_nodes: List[str] = nx.shortest_path(G, origin_node, dest_node, weight=weight_fn)

    def node_geopolitical_penalty(node_id: str) -> float:
        node_data = G.nodes[node_id]
        base = float(node_data.get("geo_base_risk", 0.0))
        if vessel_iso3 is None:
            return base
        extras = node_data.get("geo_target_flags", {}) or {}
        extra = float(extras.get(vessel_iso3, 0.0))
        return base + extra

    coordinates: List[List[float]] = []
    segments: List[RouteSegment] = []

    total_distance_nm = 0.0

    # acumuladores para riesgo ponderado por distancia
    sum_piracy_len = 0.0
    sum_weather_len = 0.0
    sum_depth_len = 0.0
    sum_traffic_len = 0.0
    sum_geo_len = 0.0

    visited_geo_zones = set()

    last_lat, last_lon = None, None

    for idx, node_id in enumerate(path_nodes):
        lat, lon = get_coordinates_of_node(G, node_id)
        coordinates.append([lat, lon])

        node_data = G.nodes[node_id]
        for zid in node_data.get("geo_zones", []) or []:
            visited_geo_zones.add(str(zid))

        if idx > 0:
            prev_id = path_nodes[idx - 1]
            prev_data = G.nodes[prev_id]

            segment_distance_nm = G[prev_id][node_id]["distance_nm"]

            piracy_avg = (
                prev_data["piracy_risk"] + node_data["piracy_risk"]
            ) / 2.0
            weather_avg = (
                prev_data["weather_risk"] + node_data["weather_risk"]
            ) / 2.0
            depth_avg = (
                prev_data["depth_penalty"] + node_data["depth_penalty"]
            ) / 2.0
            traffic_avg = (
                prev_data.get("traffic_risk", 0) + node_data.get("traffic_risk", 0)
            ) / 2.0

            geo_prev = node_geopolitical_penalty(prev_id)
            geo_curr = node_geopolitical_penalty(node_id)
            geo_avg = (geo_prev + geo_curr) / 2.0

            total_distance_nm += segment_distance_nm

            sum_piracy_len += piracy_avg * segment_distance_nm
            sum_weather_len += weather_avg * segment_distance_nm
            sum_depth_len += depth_avg * segment_distance_nm
            sum_traffic_len += traffic_avg * segment_distance_nm
            sum_geo_len += geo_avg * segment_distance_nm

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

    # medias normalizadas (ponderadas por distancia)
    if total_distance_nm > 0:
        avg_piracy = sum_piracy_len / total_distance_nm
        avg_weather = sum_weather_len / total_distance_nm
        avg_depth = sum_depth_len / total_distance_nm
        avg_traffic = sum_traffic_len / total_distance_nm
        avg_geo = sum_geo_len / total_distance_nm
    else:
        avg_piracy = avg_weather = avg_depth = avg_traffic = avg_geo = 0.0

    estimated_duration_hours = total_distance_nm / default_speed_knots if default_speed_knots > 0 else 0.0

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
        totalWeatherRisk=avg_weather,
        totalPiracyRisk=avg_piracy,
        totalDepthPenalty=avg_depth,
        totalTrafficRisk=avg_traffic,
        totalGeopoliticalRisk=avg_geo,
    )

        # Construir alertas de ruta en función de las zonas geopolíticas visitadas
    route_alerts: List[str] = []
    if visited_geo_zones:
        meta = get_zone_metadata()

        for zid in sorted(visited_geo_zones):
            m = meta.get(zid)
            if not m:
                continue
            name = m.get("name") or zid
            notes = m.get("notes", "").strip()

            if notes:
                # Una alerta por zona con notas
                alert_text = f"Route Alert: {name} –> {notes}"
            else:
                alert_text = f"Route Alert: {name}"

            route_alerts.append(alert_text)


    explanation = build_explanation(summary, route_request.mode, route_alerts)

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
