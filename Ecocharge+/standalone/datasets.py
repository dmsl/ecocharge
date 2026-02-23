import pandas as pd
import sqlite3
import numpy as np

# Load charger microgrid assignments
df = pd.read_csv("Microgrids.txt", sep="\t")

# Group by GroupID
grouped = df.groupby("GroupID")

# Connect to the database
conn = sqlite3.connect("MicroGrid.db")
cursor = conn.cursor()

# Clear previous entries
cursor.execute("DELETE FROM MicroGridMonthlyProduction")
cursor.execute("DELETE FROM MicroGridHourlyProfile")
cursor.execute("DELETE FROM MicroGridDetails")

# Realistic hourly solar profile (normalized)
hourly_distribution = {
    6:  0.02,
    7:  0.05,
    8:  0.08,
    9:  0.10,
    10: 0.12,
    11: 0.13,
    12: 0.13,
    13: 0.12,
    14: 0.10,
    15: 0.08,
    16: 0.05,
    17: 0.02,
    18: 0.01,
    19: 0.01
}
total_dist = sum(hourly_distribution.values())
# Normalize it
hourly_distribution = {h: v / total_dist for h, v in hourly_distribution.items()}

# Seasonal multipliers
monthly_multipliers = {
    1: 0.55, 2: 0.60, 3: 0.80, 4: 1.00,
    5: 1.10, 6: 1.15, 7: 1.20, 8: 1.10,
    9: 1.00, 10: 0.85, 11: 0.70, 12: 0.60
}

for group_id, group in grouped:
    total_power_kw = (group["Power"] * group["Stalls"]).sum()

    # Simulate solar system parameters
    efficiency = round(np.random.uniform(0.85, 0.95), 2)
    degradation = round(np.random.uniform(0.5, 1.5), 2)
    inverter_limit = round(total_power_kw * np.random.uniform(0.8, 1.0), 1)

    # Insert MicroGridDetails
    cursor.execute("""
        INSERT INTO MicroGridDetails (
            GroupID, Name, City, Country, InstalledCapacity_kWp, Efficiency,
            InverterLimit_kW, DegradationRate, OperatorUserID
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(group_id),
        f"MicroGrid {group_id}",
        "Nicosia",
        "Cyprus",
        float(round(total_power_kw, 1)),
        efficiency,
        inverter_limit,
        degradation,
        15  # Fake operator ID
    ))

    # Generate monthly production estimates (30 days x ~5 sun hours/day)
    monthly_productions = {}
    for month in range(1, 13):
        seasonal_factor = monthly_multipliers[month]
        monthly_kwh = total_power_kw * 30 * 5 * seasonal_factor * np.random.uniform(0.95, 1.05)
        monthly_kwh = round(monthly_kwh, 2)
        monthly_productions[month] = monthly_kwh

        cursor.execute("""
            INSERT INTO MicroGridMonthlyProduction (GroupID, Month, EstimatedProduction_kWh)
            VALUES (?, ?, ?)
        """, (
            int(group_id),
            month,
            monthly_kwh
        ))

    # Insert hourly production once using average daily kWh
    avg_daily_kwh = np.mean(list(monthly_productions.values())) / 30.0
    for hour in range(24):
        hour_frac = hourly_distribution.get(hour, 0)
        hour_kwh = round(avg_daily_kwh * hour_frac, 2)

        cursor.execute("""
            INSERT INTO MicroGridHourlyProfile (GroupID, Hour, RelativeProduction)
            VALUES (?, ?, ?)
        """, (
            int(group_id),
            hour,
            hour_kwh
        ))

conn.commit()
conn.close()
print("MicroGrid details, hourly profile, and monthly production populated.")
