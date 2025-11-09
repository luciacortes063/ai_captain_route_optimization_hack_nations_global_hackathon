from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"

# Data files
WPI_CSV_PATH = DATA_DIR / "world_port_index_sample.csv"
PIRACY_GEOJSON_PATH = DATA_DIR / "piracy_zones.geojson"
WEATHER_GEOJSON_PATH = DATA_DIR / "weather_zones.geojson"
GEBCO_NETCDF_PATH = DATA_DIR / "gebco_bathymetry.nc"

# Graph cache
GRAPH_PICKLE_PATH = DATA_DIR / "maritime_graph.pkl"

# Grid resolution (degrees)
GRID_LAT_STEP = 0.1
GRID_LON_STEP = 0.1

# Baseline weights (routing may override per mode)
LAMBDA_PIRACY = 10.0
LAMBDA_WEATHER = 3.0
LAMBDA_DEPTH = 10.0

# Bathymetry threshold (meters)
MIN_DEPTH_METERS = 50

# Continuous weather penalty (used by live weather)
WAVE_HEIGHT_THRESHOLDS_M = (1.0, 2.5)
WIND_SPEED_THRESHOLD_MS = 8.0
WEATHER_WAVE_WEIGHT = 6.0
WEATHER_WIND_WEIGHT = 3.0

# Live weather API / tiling
WEATHER_API_BASE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_CELL_SIZE_DEG = 2.0
WAVE_HEIGHT_THRESHOLDS_M = (1.5, 3.0)  # NOTE: redefined; this overrides the earlier tuple

# Radius to buffer point incidents into polygons (nautical miles)
INCIDENT_RADIUS_NM = 50.0

# --- Traffic / AIS ---
# Traffic grid size in degrees (larger → smoother, less noise)
TRAFFIC_CELL_SIZE_DEG = 1.0
# Traffic weight in routing cost
LAMBDA_TRAFFIC = 5.0
# AISStream API key (from environment)
AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY", "")
# Area of interest (same bbox as the graph)
AIS_LAT_RANGE = (-10.0, 35.0)
AIS_LON_RANGE = (30.0, 65.0)

# Geopolitics
GEOPOLITICS_GEOJSON_PATH = DATA_DIR / "geopolitics_config.geojson"
# Base geopolitical risk weight (routing still adjusts per mode)
LAMBDA_GEO = 5.0
