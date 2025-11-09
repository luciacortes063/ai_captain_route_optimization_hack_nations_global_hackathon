# data_sources.py
from __future__ import annotations

from typing import Dict, List

import pandas as pd
import geopandas as gpd
import xarray as xr

from backend.config import (
    WPI_CSV_PATH,
    PIRACY_GEOJSON_PATH,
    WEATHER_GEOJSON_PATH,
    GEBCO_NETCDF_PATH,
    MIN_DEPTH_METERS,
    INCIDENT_RADIUS_NM,
)
from backend.models import Port, RiskLayer, RiskFeature


def load_ports_from_wpi() -> Dict[str, Port]:
    """Read WPI CSV and return a dict of ports keyed by port_id."""
    df = pd.read_csv(WPI_CSV_PATH)
    ports: Dict[str, Port] = {}
    for _, row in df.iterrows():
        port = Port(
            id=str(row["port_id"]),
            name=row["port_name"],
            country=row["country"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
        )
        ports[port.id] = port
    return ports


def load_piracy_zones() -> RiskLayer:
    """
    Build a piracy RiskLayer.
    - Polygons and MultiPolygons are used as-is.
    - Points are buffered into circles (approx; 1° lat ≈ 60 nm) with INCIDENT_RADIUS_NM.
    - Output polygons use [lat, lon] ordering for the frontend.
    """
    gdf = gpd.read_file(PIRACY_GEOJSON_PATH)
    features: List[RiskFeature] = []

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue

        risk_level = int(row.get("risk_level", 3))
        polygons = []

        if geom.geom_type == "Polygon":
            polygons = [geom]
        elif geom.geom_type == "MultiPolygon":
            polygons = list(geom.geoms)
        elif geom.geom_type == "Point":
            # Quick approximation: 1° latitude ~ 60 nm → buffer in degrees
            radius_deg = INCIDENT_RADIUS_NM / 60.0
            buffered = geom.buffer(radius_deg)
            polygons = [buffered]
        else:
            continue

        for poly in polygons:
            # shapely exterior coords are (lon, lat); convert to [lat, lon]
            coords = [[float(y), float(x)] for x, y in poly.exterior.coords]
            features.append(
                RiskFeature(
                    id=str(row.get("id", row.get("name", "piracy_zone"))),
                    polygon=coords,
                    riskLevel=risk_level,
                    severity=None,
                )
            )

    return RiskLayer(
        type="piracy",
        name="Piracy High Risk Areas (bbox + incidents)",
        features=features,
    )


def load_weather_zones() -> RiskLayer:
    """
    Build a weather RiskLayer from polygons.
    Output polygons use [lat, lon]; severity defaults to 2.
    """
    gdf = gpd.read_file(WEATHER_GEOJSON_PATH)
    features: List[RiskFeature] = []

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue

        if geom.geom_type == "Polygon":
            polygons = [geom]
        elif geom.geom_type == "MultiPolygon":
            polygons = list(geom.geoms)
        else:
            continue

        for poly in polygons:
            coords = [[float(y), float(x)] for x, y in poly.exterior.coords]
            features.append(
                RiskFeature(
                    id=str(row.get("id", row.get("name", "weather_zone"))),
                    polygon=coords,
                    riskLevel=None,
                    severity=int(row.get("severity", 2)),
                )
            )

    return RiskLayer(
        type="weather",
        name="Weather Risk Areas (NOAA/ECMWF-derived)",
        features=features,
    )


def load_bathymetry() -> xr.Dataset:
    """Open GEBCO NetCDF once; caller can reuse the Dataset."""
    ds = xr.open_dataset(GEBCO_NETCDF_PATH)
    return ds


def get_depth_at(ds: xr.Dataset, lat: float, lon: float) -> float:
    """
    Return water depth in meters at (lat, lon).
    GEBCO elevation: negative = ocean depth; positive/zero = land.
    """
    depth_value = ds["elevation"].sel(lat=lat, lon=lon, method="nearest").values.item()
    if depth_value < 0:
        depth_m = -float(depth_value)
    else:
        depth_m = 0.0
    return depth_m


def is_shallow(ds: xr.Dataset, lat: float, lon: float, min_depth: float = MIN_DEPTH_METERS) -> bool:
    """True if depth is below the minimum safe draft threshold."""
    depth = get_depth_at(ds, lat, lon)
    return depth < min_depth


def is_land(ds: xr.Dataset, lat: float, lon: float) -> bool:
    """
    True if the cell corresponds to land (elevation >= ~5 m).
    Note: using a small positive threshold to avoid coastline noise.
    """
    depth_value = ds["elevation"].sel(lat=lat, lon=lon, method="nearest").values.item()
    return float(depth_value) >= 5.0
