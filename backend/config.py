from pathlib import Path

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
LAMBDA_PIRACY = 5.0
LAMBDA_WEATHER = 3.0
LAMBDA_DEPTH = 10.0

MIN_DEPTH_METERS = 20

# Live weather
WEATHER_API_BASE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_CELL_SIZE_DEG = 2.0
WAVE_HEIGHT_THRESHOLDS_M = (1.5, 3.0)
