# scripts/update_weather_for_graph.py
import logging
from backend.graph_builder import load_graph, save_graph
from backend.live_weather import update_graph_weather
from backend.config import GRAPH_PICKLE_PATH

logging.basicConfig(level=logging.INFO)

def main():
    """Refresh live weather data (wave + wind) in the saved maritime graph."""
    if not GRAPH_PICKLE_PATH.exists():
        print(f"[ERROR] Graph file not found: {GRAPH_PICKLE_PATH}")
        print("Run the backend once to generate 'maritime_graph.pkl' first.")
        return

    print(f"Loading graph from {GRAPH_PICKLE_PATH} ...")
    try:
        G = load_graph()
    except Exception as e:
        print(f"[ERROR] Could not load graph: {e}")
        return

    print("Updating weather_risk using live marine API ...")
    try:
        update_graph_weather(G)
    except Exception as e:
        print(f"[ERROR] Weather update failed: {e}")
        return

    save_graph(G)

if __name__ == "__main__":
    main()
