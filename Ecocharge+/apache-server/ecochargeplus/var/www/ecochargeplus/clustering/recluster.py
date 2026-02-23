import sqlite3

# Config
MAX_CLUSTER_SIZE = 3

conn = sqlite3.connect("MicroGrid.db")
cursor = conn.cursor()

# Get current max GroupID
cursor.execute("SELECT MAX(GroupID) FROM Microgrids")
max_group_id = cursor.fetchone()[0] or 0
next_group_id = max_group_id + 1

# Find clusters with more than MAX_CLUSTER_SIZE
cursor.execute("""
    SELECT GroupID
    FROM Microgrids
    GROUP BY GroupID
    HAVING COUNT(*) > ?
""", (MAX_CLUSTER_SIZE,))
large_groups = [row[0] for row in cursor.fetchall()]

print(f"Splitting {len(large_groups)} oversized groups...")

for group_id in large_groups:
    # Get chargers in this group
    cursor.execute("""
        SELECT Chargers.id, Chargers.latitude, Chargers.longitude
        FROM Chargers
        JOIN Microgrids ON Chargers.id = Microgrids.ChargerID
        WHERE Microgrids.GroupID = ?
    """, (group_id,))
    chargers = cursor.fetchall()

    # Decide split axis (lat vs lon)
    lats = [c[1] for c in chargers]
    lons = [c[2] for c in chargers]
    axis = 1 if (max(lats) - min(lats)) >= (max(lons) - min(lons)) else 2

    # Sort and split
    chargers.sort(key=lambda c: c[axis])
    mid = len(chargers) // 2
    group1 = chargers[:mid]
    group2 = chargers[mid:]

    # Delete old group
    cursor.execute("DELETE FROM Microgrids WHERE GroupID = ?", (group_id,))

    # Insert new groups
    for charger in group1:
        cursor.execute("INSERT INTO Microgrids (GroupID, ChargerID) VALUES (?, ?)", (next_group_id, charger[0]))
    next_group_id += 1

    for charger in group2:
        cursor.execute("INSERT INTO Microgrids (GroupID, ChargerID) VALUES (?, ?)", (next_group_id, charger[0]))
    next_group_id += 1

conn.commit()
conn.close()
print("✅ Split complete. You can run again to keep splitting oversized groups.")
