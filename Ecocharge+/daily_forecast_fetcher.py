import json
import sqlite3
from datetime import datetime
import requests
import os

DATABASE_FILE = os.getenv("DATABASE_FILE", "./MicroGrid.db")
OPENWEATHER_API_KEY = "50bf2c5a75636772ee020a9c2cc969db"
OUTPUT_FILE = "/home/user/Github_Repositories/ADE/static/forecast/daily_forecast.json"

def fetch_all_forecasts():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, latitude, longitude FROM Chargers")
    chargers = cursor.fetchall()
    conn.close()

    all_forecasts = []
    for charger_id, lat, lon in chargers:
        print(f"Fetching forecast for: {lat}, {lon}")
        url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                print(f"Success for charger {charger_id}")
                all_forecasts.append({
                    "charger_id": charger_id,
                    "latitude": lat,
                    "longitude": lon,
                    "forecast": data
                })
            else:
                print(f"Failed with status {response.status_code} for charger {charger_id}")
        except Exception as e:
            print(f"Error fetching for charger {charger_id}: {e}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat(),
            "data": all_forecasts
        }, f, indent=2)

if __name__ == "__main__":
    fetch_all_forecasts()
