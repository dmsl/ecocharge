import sqlite3
import folium
import random
from collections import defaultdict

# Connect to the SQLite DB
conn = sqlite3.connect("MicroGrid.db")
cursor = conn.cursor()

# Step 1: Fetch grouped chargers
cursor.execute("""
    SELECT Chargers.latitude, Chargers.longitude, Microgrids.GroupID
    FROM Chargers
    JOIN Microgrids ON Chargers.id = Microgrids.ChargerID
    WHERE Microgrids.GroupID != -1
""")
grouped = cursor.fetchall()

# Step 2: Fetch ungrouped chargers
cursor.execute("""
    SELECT latitude, longitude
    FROM Chargers
    WHERE id NOT IN (SELECT ChargerID FROM Microgrids)
""")
ungrouped = cursor.fetchall()

# Step 3: Compute centroids for each group
group_coords = defaultdict(list)
for lat, lon, group_id in grouped:
    group_coords[group_id].append((lat, lon))

centroids = {
    group_id: (
        sum(lat for lat, _ in coords) / len(coords),
        sum(lon for _, lon in coords) / len(coords)
    )
    for group_id, coords in group_coords.items()
}

# Step 4: Initialize map
map_center = [35.1264, 33.4299]  # Cyprus
fmap = folium.Map(location=map_center, zoom_start=8)
cluster_colors = {}

# Step 5: Plot grouped chargers
for lat, lon, group_id in grouped:
    if group_id not in cluster_colors:
        cluster_colors[group_id] = "#{:06x}".format(random.randint(0, 0xFFFFFF))
    color = cluster_colors[group_id]

    folium.CircleMarker(
        location=(lat, lon),
        radius=4,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.7,
        popup=f"Group {group_id}"
    ).add_to(fmap)

# Step 6: Plot ungrouped chargers in gray
for lat, lon in ungrouped:
    folium.CircleMarker(
        location=(lat, lon),
        radius=4,
        color="gray",
        fill=True,
        fill_color="gray",
        fill_opacity=0.5,
        popup="Ungrouped"
    ).add_to(fmap)

# Step 7: Plot group centroids
for group_id, (lat, lon) in centroids.items():
    folium.Marker(
        location=(lat, lon),
        icon=folium.Icon(color="blue", icon="info-sign"),
        popup=f"Group {group_id} centroid"
    ).add_to(fmap)

# Save and display
fmap.save("charger_clusters_map.html")
print("✅ Map saved as charger_clusters_map.html")
