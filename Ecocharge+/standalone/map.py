from flask import Flask, jsonify, render_template
import sqlite3
import os

app = Flask(__name__)

# SQLite database file
DATABASE_FILE = "C:/Users/35799/Desktop/GitHub_Repositories/MicroGrid/MicroGrid.db"
print(os.path.abspath(DATABASE_FILE))

def get_data_from_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Fetch charger and weather data
    cursor.execute('''SELECT Chargers.Latitude, Chargers.Longitude, WeatherForecast.Temperature, WeatherForecast.Clouds, 
                             WeatherForecast.Humidity, WeatherForecast.WindSpeed, WeatherForecast.WindDirection
                      FROM Chargers
                      JOIN WeatherForecast ON Chargers.ChargerID = WeatherForecast.ChargerID''')
    charger_data = cursor.fetchall()
    
    # Fetch microgrid data
    cursor.execute('''SELECT City, Country, Max_lon, Min_lon, Max_lat, Min_lat FROM MicroGrid LIMIT 1''')
    microgrid_data = cursor.fetchone()
    conn.close()
    
    # Convert charger data to a list of dictionaries
    locations = []
    for row in charger_data:
        locations.append({
            "latitude": row[0],
            "longitude": row[1],
            "temperature": row[2],
            "clouds": row[3],
            "humidity": row[4],
            "wind_speed": row[5],
            "wind_direction": row[6]
        })
    
    # Add microgrid data if available
    if microgrid_data:
        microgrid = {
            "city": microgrid_data[0],
            "country": microgrid_data[1],
            "max_lon": microgrid_data[2],
            "min_lon": microgrid_data[3],
            "max_lat": microgrid_data[4],
            "min_lat": microgrid_data[5]
        }
        locations.append({"microgrid": microgrid})

    return locations

@app.route('/map_data')
def map_data():
    data = get_data_from_db()
    return jsonify(data)

@app.route('/')
def index():
    return render_template('map.html')

if __name__ == '__main__':
    app.run(debug=True)
