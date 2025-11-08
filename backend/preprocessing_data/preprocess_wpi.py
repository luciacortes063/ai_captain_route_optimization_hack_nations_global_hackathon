import pandas as pd
from pathlib import Path

 
raw_path = Path("data/UpdatedPub150.csv")
out_path = Path("data/world_port_index_sample.csv")


df = pd.read_csv(raw_path)

print("Original columns:")
print(list(df.columns))

df_out = df.rename(
    columns={
        "World Port Index Number": "port_id",
        "Main Port Name": "port_name",
        "Country Code": "country",
        "Latitude": "latitude",
        "Longitude": "longitude",
    }
)[["port_id", "port_name", "country", "latitude", "longitude"]]

# Convert to numeric 
df_out["latitude"] = pd.to_numeric(df_out["latitude"], errors="coerce")
df_out["longitude"] = pd.to_numeric(df_out["longitude"], errors="coerce")

# Drop rows without coordinates 
df_out = df_out.dropna(subset=["latitude", "longitude"])

# Filter region (Red Sea + Gulf of Aden + Suez + part of Indian Ocean)
lat_min, lat_max = -10.0, 35.0
lon_min, lon_max = 30.0, 65.0

df_out = df_out[
    (df_out["latitude"] >= lat_min)
    & (df_out["latitude"] <= lat_max)
    & (df_out["longitude"] >= lon_min)
    & (df_out["longitude"] <= lon_max)
]

out_path.parent.mkdir(parents=True, exist_ok=True)
df_out.to_csv(out_path, index=False)

print(f"Saved filtered subset to: {out_path}")
print(f"Number of ports in region: {len(df_out)}")
print(df_out.head(10))
