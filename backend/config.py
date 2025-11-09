from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv()


BASE_DIR = Path(__file__).resolve().parent  
PROJECT_ROOT = BASE_DIR.parent       
DATA_DIR = PROJECT_ROOT / "data" 

# World Port Index
WPI_CSV_PATH = DATA_DIR / "world_port_index_sample.csv"

# Piracy zones
PIRACY_GEOJSON_PATH = DATA_DIR / "piracy_zones.geojson"

# Weather zones
WEATHER_GEOJSON_PATH = DATA_DIR / "weather_zones.geojson"

# GEBCO bathymetry
GEBCO_NETCDF_PATH = DATA_DIR / "gebco_bathymetry.nc"

# Graph
GRAPH_PICKLE_PATH = DATA_DIR / "maritime_graph.pkl"

# Grid resolution
GRID_LAT_STEP = 0.1
GRID_LON_STEP = 0.1

# Weights
LAMBDA_PIRACY = 10.0
LAMBDA_WEATHER = 3.0
LAMBDA_DEPTH = 10.0

MIN_DEPTH_METERS = 50

# Continuous weather penalty
WAVE_HEIGHT_THRESHOLDS_M = (1.0, 2.5)    # start penalizing above 1.0 m
WIND_SPEED_THRESHOLD_MS  = 8.0           # start above ~15.5 kn
WEATHER_WAVE_WEIGHT      = 6.0
WEATHER_WIND_WEIGHT      = 3.0

# Live weather
WEATHER_API_BASE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_CELL_SIZE_DEG = 2.0
WAVE_HEIGHT_THRESHOLDS_M = (1.5, 3.0)

INCIDENT_RADIUS_NM = 50.0 

# --- Traffic / AIS ---

# Tamaño de las celdas para el tráfico (puedes usar 0.5 o 1.0 para menos ruido)
TRAFFIC_CELL_SIZE_DEG = 1.0

# Peso del tráfico en la función de coste
LAMBDA_TRAFFIC = 5.0

# API key para AISStream (cógela de variable de entorno)
AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY", "")

# Bounding box de tu área de interés (el mismo que usas para el grafo)
AIS_LAT_RANGE = (-10.0, 35.0)
AIS_LON_RANGE = (30.0, 65.0)
