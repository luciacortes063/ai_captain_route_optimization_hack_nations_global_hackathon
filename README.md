# Cargo Route Planner (AI Captain)

## Project Description
Cargo Route Planner is a maritime route optimization tool that combines multiple real-world risk factors: piracy, weather, AIS vessel traffic, bathymetry, and geopolitical tensions, to compute optimal shipping routes between ports.  
It includes a **FastAPI backend** for risk-aware routing and a **Leaflet.js frontend** for interactive visualization. Users can select **Safe**, **Fast**, or **Balanced** routing modes and overlay live or static risk maps.

---

## Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/luciacortes063/ai_captain_route_optimization_hack_nations_global_hackathon.git
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```


4. **Run the backend and the frontend**
   ```bash
   bash run_all.sh
   ```
   Then open the API documentation at [http://localhost:8000/docs](http://localhost:8000/docs). Visit [http://localhost:5500](http://localhost:5500) to use the interface.

---

##  Dependencies / Environment
| Package | Purpose |
|----------|----------|
| FastAPI / Uvicorn | Backend API and ASGI server |
| Pydantic | Data models for API |
| NetworkX / NumPy | Graph-based pathfinding |
| GeoPandas / Shapely | Spatial analysis and geometry operations |
| xarray | Bathymetry data access |
| Websockets | AIS vessel traffic stream |
| Haversine | Geodesic distance calculation |
| Pandas | CSV and tabular data |
| Python-dotenv | Environment variable management |

Required data files in `/data`:
- `world_port_index_sample.csv` – port dataset  
- `piracy_zones.geojson` – piracy risk polygons  
- `weather_zones.geojson` – weather risk polygons  
- `geopolitics_config.geojson` – geopolitical risk zones  
- `gebco_bathymetry.nc` – GEBCO bathymetry dataset  

---

##  Team Member Credits
**Author:** Lucía Cortés Páez
MSc Artificial Intelligence, University of Zurich / ETHZ
**Author:** Àlex Capilla Miralles  
MSc Artificial Intelligence, University of Zurich  / ETHZ

