from flask import Flask, jsonify
import sqlite3
import os
from datetime import datetime, timezone, timedelta

app = Flask(__name__)
DATABASE_FILE = os.getenv("DATABASE_FILE", "/home/user/Github_Repositories/ADE/MicroGrid.db")

# Define Cyprus Time Offset (Change to 3 if daylight saving time applies)
CYPRUS_OFFSET = 2  

def get_all_weather_data():
    """Fetch the latest weather data for all chargers and estimate solar/grid power usage."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    query = """
    SELECT wf.ChargerID, wf.Temperature, wf.Clouds, wf.Humidity, wf.WindSpeed, 
           wf.WindDirection, wf.timestamp, c.power
    FROM WeatherForecast wf
    JOIN Charger c ON wf.ChargerID = c.id
    WHERE wf.timestamp IN (
        SELECT MAX(timestamp) FROM WeatherForecast GROUP BY ChargerID
    )
    ORDER BY wf.ChargerID;
    """
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()

    chargers_data = []

    for row in data:
        charger_id, temp, clouds, humidity, wind_speed, wind_dir, timestamp_utc, power_demand = row

        # Convert timestamp correctly (handles fractions and timezone)
        try:
            timestamp_utc = datetime.fromisoformat(timestamp_utc)
        except ValueError:
            timestamp_utc = timestamp_utc.split("+")[0]  # Remove timezone
            timestamp_utc = timestamp_utc.split(".")[0]  # Remove fractional seconds
            timestamp_utc = datetime.strptime(timestamp_utc, "%Y-%m-%d %H:%M:%S")  

        # Convert to Cyprus Time
        # cyprus_time = timestamp_utc + timedelta(hours=CYPRUS_OFFSET)
        cyprus_time_str = timestamp_utc.strftime("%Y-%m-%d %H:%M:%S")

        # Estimate solar power based on cloud coverage AND time
        solar_efficiency = estimate_solar_power(clouds, cyprus_time_str) / 100

        solar_power = power_demand * solar_efficiency

        # If power demand is NULL or missing, set a default (e.g., 50 kW)
        charger_power_demand = power_demand if power_demand is not None else 50

        # Calculate Grid Power Usage
        grid_power_usage = max(0, charger_power_demand - solar_power)

        # Calculate Residual Solar Power
        residual_solar_power = max(0, solar_power - charger_power_demand)

        chargers_data.append({
            "charger_id": charger_id,
            "temperature": temp,
            "clouds": clouds,
            "humidity": humidity,
            "wind_speed": wind_speed,
            "wind_direction": wind_dir,
            "timestamp_utc": timestamp_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_cyprus": cyprus_time_str,
            "solar_power_estimate_%": solar_efficiency * 100,
            "solar_power_generated": solar_power,
            "charger_power_demand": charger_power_demand,
            "grid_power_usage": grid_power_usage,
            "residual_solar_power": residual_solar_power 
        })

    return chargers_data

def estimate_solar_power(clouds, timestamp_cyprus):
    """Estimate solar power based on cloud coverage and time of day."""
    
    # Extract the hour from timestamp_cyprus
    hour = datetime.strptime(timestamp_cyprus, "%Y-%m-%d %H:%M:%S").hour
    
    # Define typical sunrise and sunset hours for Cyprus
    SUNRISE_HOUR = 6  # 06:00 AM
    SUNSET_HOUR = 18  # 06:00 PM
    
    # If it's nighttime, return 0 solar power
    if hour < SUNRISE_HOUR or hour >= SUNSET_HOUR:
        return 0

    # Estimate solar power based on cloud coverage during the day
    if clouds < 25:
        return 80 + 20 * (1 - clouds / 25)  # 80-100% efficiency
    elif 25 <= clouds <= 75:
        return 40 + (75 - clouds) / 50 * 40  # 40-80% efficiency
    else:
        return max(0, 40 - (clouds - 75) / 25 * 40)  # 0-40% efficiency

@app.route('/solar_power_all', methods=['GET'])
def get_all_solar_power():
    chargers_data = get_all_weather_data()
    if not chargers_data:
        return jsonify({"error": "No weather data available"}), 404

    return jsonify({"chargers": chargers_data})

if __name__ == '__main__':
    app.run(debug=True)
