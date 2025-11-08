# scripts/update_weather_for_graph.py
import logging
from pathlib import Path
import sys

from backend.graph_builder import load_graph, save_graph 
from backend.live_weather import update_graph_weather  
from backend.config import GRAPH_PICKLE_PATH  

logging.basicConfig(level=logging.INFO)


def main():
    if not GRAPH_PICKLE_PATH.exists():
        print(f"Graph file not found: {GRAPH_PICKLE_PATH}")
        print("First stap the app once to generete maritime_graph.pkl")
        return

    print(f"Loading graph from {GRAPH_PICKLE_PATH} ...")
    G = load_graph()

    print("Updating weather_risk using live marine API ...")
    update_graph_weather(G)

    print("Saving updated graph ...")
    save_graph(G)
    print("Done. maritime_graph.pkl now includes live weather_risk.")


if __name__ == "__main__":
    main()
