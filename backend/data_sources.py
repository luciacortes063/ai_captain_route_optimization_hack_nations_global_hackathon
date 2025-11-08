# data_sources.py
from __future__ import annotations

from typing import Dict, List, Tuple
import json

import pandas as pd
import geopandas as gpd
import xarray as xr
from shapely.geometry import shape, mapping, Point

from backend.config import (
    WPI_CSV_PATH,
    PIRACY_GEOJSON_PATH,
    WEATHER_GEOJSON_PATH,
    GEBCO_NETCDF_PATH,
    MIN_DEPTH_METERS,
)
from backend.models import Port, RiskLayer, RiskFeature


def load_ports_from_wpi() -> Dict[str, Port]:
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
    gdf = gpd.read_file(PIRACY_GEOJSON_PATH)
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
                    id=str(row.get("id", row.get("name", "piracy_zone"))),
                    polygon=coords,
                    riskLevel=int(row.get("risk_level", 3)),
                    severity=None,
                )
            )

    return RiskLayer(
        type="piracy",
        name="Piracy High Risk Areas (ICC-derived)",
        features=features,
    )


def load_weather_zones() -> RiskLayer:
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
    ds = xr.open_dataset(GEBCO_NETCDF_PATH)
    return ds


def get_depth_at(ds: xr.Dataset, lat: float, lon: float) -> float:

    depth_value = ds["elevation"].sel(lat=lat, lon=lon, method="nearest").values.item()

    if depth_value < 0:
        depth_m = -float(depth_value)
    else:
        depth_m = 0.0
    return depth_m


def is_shallow(ds: xr.Dataset, lat: float, lon: float, min_depth: float = MIN_DEPTH_METERS) -> bool:
    depth = get_depth_at(ds, lat, lon)
    return depth < min_depth

def is_land(ds: xr.Dataset, lat: float, lon: float) -> bool:
    """
    Devuelve True si la celda corresponde a tierra (elevación >= 0).
    """
    depth_value = ds["elevation"].sel(lat=lat, lon=lon, method="nearest").values.item()
    # GEBCO: valores positivos o cero = tierra / costa
    return float(depth_value) >= 5.0

