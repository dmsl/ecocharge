import sqlite3
import requests
import os

from datetime import datetime, timezone, timedelta

CYPRUS_OFFSET = 2
cyprus_time = datetime.now(timezone.utc) + timedelta(hours=CYPRUS_OFFSET)

# OpenWeather API Key
API_KEY = '50bf2c5a75636772ee020a9c2cc969db'

# SQLite database file
DATABASE_FILE = "/home/user/Github_Repositories/ADE/MicroGrid.db"

# Log environment and execution details

def get_charger_locations():
    """
    Fetch ChargerID, Latitude, and Longitude from the Charger table.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, Latitude, Longitude FROM Chargers")
        locations = cursor.fetchall()
        conn.close()
        if locations:
            print(f"Fetched {len(locations)} charger locations from the database.")
        else:
            print("No charger locations found in the database.")
        return locations
    except sqlite3.Error as e:
        print(f"Error fetching charger locations from database: {e}")
        return []

def fetch_weather_data(lat, lon):
    """
    Fetch current weather data for a given latitude and longitude from OpenWeather API.
    """
    try:
        url = f'http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}&units=metric'
        print(f"Fetching weather data for coordinates: lat={lat}, lon={lon}...")
        response = requests.get(url)
        if response.status_code == 200:
            print("Weather data fetched successfully.")
            return response.json()
        else:
            print(f"Failed to fetch data. HTTP Status Code: {response.status_code}")
            return None
    except requests.RequestException as e:
        print(f"Error fetching weather data: {e}")
        return None

def update_weather_data(charger_id, weather_data):
    """
    Update existing weather data for a ChargerID in the WeatherForecast table.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        temperature = weather_data['main']['temp']
        clouds = weather_data['clouds']['all']  # cloudiness in percentage
        humidity = weather_data['main']['humidity']
        wind_speed = weather_data['wind']['speed']
        wind_direction = weather_data['wind'].get('deg', None)  # wind direction

        print(f"Updating weather data for ChargerID {charger_id} in the database...")

        cursor.execute('''
            UPDATE WeatherForecast 
            SET Temperature = ?, Clouds = ?, Humidity = ?, WindSpeed = ?, WindDirection = ?, timestamp = ?
            WHERE ChargerID = ?
        ''', (temperature, clouds, humidity, wind_speed, wind_direction, cyprus_time, charger_id,))

        if cursor.rowcount == 0:
            print(f"No existing record for ChargerID {charger_id}, skipping update.")
        else:
            print(f"Weather data for ChargerID {charger_id} updated successfully.")

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"Error updating data in the database: {e}")


def main():
    charger_locations = get_charger_locations()
    if not charger_locations:
        print("No charger locations available to fetch weather data.")
        return

    for charger_id, lat, lon in charger_locations:
        print(f"Processing ChargerID: {charger_id}")
        
        weather_data = fetch_weather_data(lat, lon)
        if weather_data:
            update_weather_data(charger_id, weather_data)
        else:
            print(f"Failed to fetch or insert weather data for ChargerID {charger_id}.")

if __name__ == '__main__':
    print("Starting weather data fetching process...")
    main()
    print("Weather data fetching process completed.")
