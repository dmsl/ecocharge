import sqlite3
import numpy as np
from sklearn.cluster import DBSCAN
from geopy.distance import geodesic

# Load chargers
conn = sqlite3.connect('MicroGrid.db')
cursor = conn.cursor()
cursor.execute("SELECT id, latitude, longitude FROM Chargers")
chargers = cursor.fetchall()

# Convert to NumPy array for clustering
coords = np.array([[lat, lon] for _, lat, lon in chargers])

# Define DBSCAN clustering with ~3km radius
kms_per_radian = 6371.0088
epsilon = 3 / kms_per_radian

db = DBSCAN(eps=epsilon, min_samples=2, algorithm='ball_tree', metric='haversine')
clusters = db.fit(np.radians(coords))

# Insert results into Microgrids table
for (charger, cluster_id) in zip(chargers, clusters.labels_):
    if cluster_id == -1:
        continue  # Noise (unclustered)
    charger_id = charger[0]
    cursor.execute(
        "INSERT INTO Microgrids (GroupID, ChargerID) VALUES (?, ?)",
        (int(cluster_id), charger_id)  # cast to plain int
    )

print("Number of clusters:", len(set(clusters.labels_)) - (1 if -1 in clusters.labels_ else 0))

conn.commit()
conn.close()
print("Microgrids table populated.")
# This script connects to the SQLite database, retrieves charger locations, and uses DBSCAN to cluster them based on their geographic coordinates.
