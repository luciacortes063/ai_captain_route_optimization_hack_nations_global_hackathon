from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from shapely.geometry import shape, Point

from backend.config import GEOPOLITICS_GEOJSON_PATH
from backend.models import RiskLayer, RiskFeature


def load_geopolitics_config():
    """
    Load geopolitics GeoJSON and return:
      - RiskLayer (for /risk-layers frontend)
      - list of (shapely_polygon, base_risk, target_flags_dict, zone_id, name, notes)
      - country_aliases (country name -> ISO3)
    """
    path = GEOPOLITICS_GEOJSON_PATH
    if not path.exists():
        raise FileNotFoundError(f"Geopolitics config not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    props = data.get("properties", {}) or {}
    country_aliases: Dict[str, str] = props.get("country_aliases", {}) or {}

    features: List[RiskFeature] = []
    # Note: polygon element is a Shapely geometry (Polygon/MultiPolygon).
    polygons: List[Tuple[object, float, Dict[str, float], str, str, str]] = []

    for feat in data.get("features", []):
        fprops = feat.get("properties", {}) or {}
        geom = feat.get("geometry")
        if not geom:
            continue

        zone_id = fprops.get("zone_id") or fprops.get("id") or "geo_zone"
        name = fprops.get("name", zone_id)
        base_risk = float(fprops.get("base_risk", 0.0))
        target_flags = fprops.get("target_flags", {}) or {}
        notes = fprops.get("notes", "")

        poly = shape(geom)
        polygons.append(
            (poly, base_risk, {k: float(v) for k, v in target_flags.items()}, str(zone_id), name, notes)
        )

        # GeoJSON uses [lon, lat]; RiskFeature expects [lat, lon]
        coords_lonlat = geom.get("coordinates", [[]])[0]
        coords_latlon = [[float(lat), float(lon)] for lon, lat in coords_lonlat]

        features.append(
            RiskFeature(
                id=str(zone_id),
                polygon=coords_latlon,
                riskLevel=int(base_risk),
                severity=None,
            )
        )

    risk_layer = RiskLayer(
        type="geopolitics",
        name="Geopolitical Tension Zones",
        features=features,
    )

    return risk_layer, polygons, country_aliases


def apply_geopolitics_to_graph(G):
    """
    Annotate graph nodes with:
      - geo_base_risk (float)
      - geo_target_flags (dict ISO3 -> extra risk)
      - geo_zones (list of zone_ids)
    """
    _, polygons, _ = load_geopolitics_config()

    for node_id, data in G.nodes(data=True):
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            continue

        p = Point(float(lon), float(lat))

        base_max = 0.0
        flags: Dict[str, float] = {}
        zones: List[str] = []

        for poly, base_risk, target_flags, zone_id, name, notes in polygons:
            if not poly.contains(p):
                continue

            if base_risk > base_max:
                base_max = base_risk

            # Keep the max extra per ISO3
            for iso, val in target_flags.items():
                current = flags.get(iso, 0.0)
                if val > current:
                    flags[iso] = val

            if zone_id not in zones:
                zones.append(zone_id)

        if base_max > 0.0 or flags or zones:
            data["geo_base_risk"] = base_max
            data["geo_target_flags"] = flags
            data["geo_zones"] = zones
        else:
            data["geo_base_risk"] = 0.0
            data["geo_target_flags"] = {}
            data["geo_zones"] = []


def get_zone_metadata() -> Dict[str, Dict[str, str]]:
    """
    Build a small metadata map:
      zone_id -> {"name": str, "notes": str}
    """
    path = GEOPOLITICS_GEOJSON_PATH
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta: Dict[str, Dict[str, str]] = {}
    for feat in data.get("features", []):
        fprops = feat.get("properties", {}) or {}
        zone_id = fprops.get("zone_id") or fprops.get("id")
        if not zone_id:
            continue
        name = fprops.get("name", str(zone_id))
        notes = fprops.get("notes", "")
        meta[str(zone_id)] = {"name": name, "notes": notes}
    return meta


def infer_vessel_iso3_from_origin_country(origin_country: str | None) -> str | None:
    """
    Map origin port country name (e.g., 'Tanzania') to ISO3
    using the GeoJSON country_aliases.
    """
    if not origin_country:
        return None
    try:
        _, _, aliases = load_geopolitics_config()
    except Exception:
        return None

    key = origin_country.strip()
    return aliases.get(key)
