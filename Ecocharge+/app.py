from flask import Flask, request, render_template, redirect, url_for, jsonify, session
from flask_session import Session
import sqlite3
import bcrypt
import json
from datetime import datetime, timezone, timedelta
from geopy.distance import geodesic
from zoneinfo import ZoneInfo
import yaml
import os
import traceback
import re
import math
import random
import time
from math import radians, cos, sin, asin, sqrt, atan2
from collections import defaultdict
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_url_path='/static')
app.secret_key = os.getenv("SECRET_KEY")
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.config["SESSION_TYPE"] = "filesystem"  # Store session data in files
app.config["SESSION_PERMANENT"] = False  # Optional: Sessions expire when the browser is closed
app.config["SESSION_COOKIE_SECURE"] = True  # Needed on HTTPS
app.config["SESSION_COOKIE_DOMAIN"] = "micro-grid.online"
Session(app)

DATABASE_FILE = os.getenv("DATABASE_FILE", "./MicroGrid.db")
CONFIG_FILE = '/etc/evcc.yaml'
print(os.path.abspath(DATABASE_FILE))
print(sqlite3.sqlite_version)

CYPRUS_OFFSET = 2  

@app.errorhandler(500)
def internal_server_error(e):
    print("[ERROR] Internal Server Error:", str(e))
    print(traceback.format_exc())
    return jsonify({"error": "Internal Server Error"}), 500

def connect_db():
    return sqlite3.connect(DATABASE_FILE)

# Helper function to add or update a section in the configuration
def update_section(config, section, data):
    if section not in config:
        config[section] = []
    config[section].append(data)
    return config

# Helper function to find an item by name in a section
def find_item(section, name, value):
    config = load_config()
    if section in config:
        for item in config[section]:
            print(item)
            if item.get(name) == value:
                return item
    return None

def get_vehicle_data():
    conn = connect_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT VehicleID, Make, Model, BatteryCapacity, ConsumptionRate
        FROM Vehicle
    ''')
    vehicle_rows = cursor.fetchall()

    cursor.execute('''
        SELECT VehicleID, ChargerType
        FROM VehicleChargerTypes
    ''')
    charger_rows = cursor.fetchall()

    conn.close()

    plug_types_map = {}
    for vehicle_id, charger_type in charger_rows:
        plug_types_map.setdefault(vehicle_id, []).append(charger_type)

    vehicles_by_make = {}
    for vehicle_id, make, model, battery_capacity, consumption_rate in vehicle_rows:
        if make not in vehicles_by_make:
            vehicles_by_make[make] = []
        vehicles_by_make[make].append({
            "vehicle_id": vehicle_id,
            "model": model,
            "battery_capacity": battery_capacity,
            "consumption_rate": consumption_rate,
            "plug_types": plug_types_map.get(vehicle_id, [])
        })

    return vehicles_by_make

# Load YAML config
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as file:
            return yaml.safe_load(file) or {}
    return {}

# Save YAML config
def save_config(config):
    with open(CONFIG_FILE, 'w') as file:
        yaml.dump(config, file, default_flow_style=False, indent=2, sort_keys=False)

@app.route('/api/get_user_id')
def get_user_id():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 200

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT Role FROM User WHERE UserID = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    return jsonify({
        "userID": int(user_id),
        "role": row[0] if row else "Regular"
    }), 200

def get_microgrid_data():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # Map: charger_id -> microgrid group_id
    cursor.execute("SELECT ChargerID, GroupID FROM Microgrids")
    charger_to_group = dict(cursor.fetchall())

    # MicroGrid details (installed capacity and efficiency)
    cursor.execute("SELECT GroupID, InstalledCapacity_kWp, Efficiency FROM MicroGridDetails")
    grid_details = {row[0]: {"capacity": row[1], "efficiency": row[2]} for row in cursor.fetchall()}

    cursor.execute("SELECT Hour, RelativeProduction FROM MicroGridHourlyProfile")
    hourly_profile = dict(cursor.fetchall())

    # Monthly production: GroupID -> {month -> kWh}
    cursor.execute("SELECT GroupID, Month, EstimatedProduction_kWh FROM MicroGridMonthlyProduction")
    monthly_productions = {}
    for gid, month, kwh in cursor.fetchall():
        monthly_productions.setdefault(gid, {})[int(month)] = kwh

    conn.close()
    return charger_to_group, grid_details, hourly_profile, monthly_productions

def estimate_clear_sky_ghi(hour, latitude=35.0):
    # Approx: sunrise at 6, sunset at 19
    sunrise = 6
    sunset = 18
    if hour < sunrise or hour >= sunset:
        return 0

    # Normalize hour to [0, π] over the solar day
    hour_angle = (hour - sunrise) / (sunset - sunrise) * math.pi
    return 1000 * math.sin(hour_angle)

def estimate_ghi(cloud_coverage_fraction, ghi_clear_sky):
    """
    Estimate GHI based on cloud coverage using empirical formula:
    GHI_estimated = GHI_clear_sky * (1 - 0.75 * (cloud_coverage_fraction)^3)
    """
    return ghi_clear_sky * (1 - 0.75 * (cloud_coverage_fraction))

def calculate_pv_output(ghi_estimated, installed_capacity_kwp, pv_efficiency):
    """
    Estimate solar PV output (kW) based on estimated GHI and system efficiency.
    """
    # installed_capacity_kwp already reflects area × efficiency approximately
    # We directly scale GHI with installed_capacity_kwp and efficiency
    pv_output_kw = (ghi_estimated / 1000) * installed_capacity_kwp * pv_efficiency
    return pv_output_kw

def get_all_weather_data():
    print("Scheduler: Running get_all_weather_data()")
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # Get current time in Cyprus
    cyprus_now = datetime.now(ZoneInfo("Europe/Nicosia"))
    current_hour = cyprus_now.hour
    current_month = cyprus_now.month
    date_str = cyprus_now.strftime("%Y-%m-%d")

    # Load latest weather data per charger
    cursor.execute("""
        SELECT wf.ChargerID, wf.Temperature, wf.Clouds, wf.Humidity, wf.WindSpeed, 
               wf.WindDirection, wf.timestamp, c.power
        FROM WeatherForecast wf
        JOIN Chargers c ON wf.ChargerID = c.id
        WHERE wf.timestamp IN (
            SELECT MAX(timestamp) FROM WeatherForecast GROUP BY ChargerID
        )
        ORDER BY wf.ChargerID;
    """)
    weather_rows = cursor.fetchall()

    # Map ChargerID → GroupID
    cursor.execute("SELECT ChargerID, GroupID FROM Microgrids")
    charger_to_group = {row[0]: row[1] for row in cursor.fetchall()}

    # Map GroupID → MicroGridDetails
    cursor.execute("SELECT GroupID, InstalledCapacity_kWp, Efficiency FROM MicroGridDetails")
    grid_details = {row[0]: {"capacity": row[1], "efficiency": row[2]} for row in cursor.fetchall()}

    # Monthly production: GroupID → {Month → kWh}
    cursor.execute("SELECT GroupID, Month, EstimatedProduction_kWh FROM MicroGridMonthlyProduction")
    monthly_prod = defaultdict(dict)
    for group_id, month, kwh in cursor.fetchall():
        monthly_prod[group_id][int(month)] = kwh

    # Hourly profile: {Hour → Fraction}
    cursor.execute("SELECT Hour, RelativeProduction FROM MicroGridHourlyProfile")
    hourly_profile = dict(cursor.fetchall())

    # Precompute group-wise charger lists and demand
    group_to_chargers = defaultdict(list)
    charger_demand_map = {}

    for row in weather_rows:
        charger_id = row[0]
        power_demand = row[7] or 0
        group_id = charger_to_group.get(charger_id)
        if group_id:
            group_to_chargers[group_id].append(charger_id)
            charger_demand_map[charger_id] = power_demand

    group_hourly_totals = defaultdict(float)
    result = []

    for row in weather_rows:
        charger_id, temp, clouds, humidity, wind_speed, wind_dir, timestamp_utc, power_demand = row
        power_demand = power_demand or 0
        group_id = charger_to_group.get(charger_id)
        if not group_id:
            continue

        # Retrieve MicroGrid details
        monthly_kwh = monthly_prod.get(group_id, {}).get(current_month, 0)
        derating_factor = 0.8  # adjust based on tests or PVGIS output
        monthly_kwh *= derating_factor
        installed_capacity = grid_details.get(group_id, {}).get("capacity", 0)
        efficiency = grid_details.get(group_id, {}).get("efficiency", 1.0)
        hour_fraction = hourly_profile.get(current_hour, 0)

        # Estimate GHI based on cloud coverage and time
        cloud_fraction = min(max(clouds, 0), 100) / 100.0
        clear_sky_ghi = estimate_clear_sky_ghi(current_hour)
        ghi_estimated = estimate_ghi(cloud_fraction, clear_sky_ghi) * hour_fraction

        # Estimate solar PV output (kW) at this time
        # solar_power_kw = calculate_pv_output(ghi_estimated, installed_capacity, efficiency) 

        # Estimate normalized cloud reduction
        cloud_scaling = ghi_estimated / clear_sky_ghi if clear_sky_ghi > 0 else 0

        # Monthly + hourly expected energy (in kWh)
        daily_kwh = monthly_kwh / 30.0 if monthly_kwh else 0
        hourly_group_generation = daily_kwh * efficiency * cloud_scaling

        # Distribute solar energy proportionally to charger demand
        chargers_in_group = group_to_chargers.get(group_id, [])
        total_group_demand = sum(charger_demand_map.get(cid, 0) for cid in chargers_in_group)

        if total_group_demand > 0:
            demand_fraction = power_demand / total_group_demand
        else:
            demand_fraction = 1.0 / len(chargers_in_group) if chargers_in_group else 1.0

        # Actual energy assigned to this charger
        solar_power_now = hourly_group_generation * demand_fraction

        group_hourly_totals[group_id] += solar_power_now

        # Compute solar percentage for this charger
        solar_power_percentage = round(min(solar_power_now / power_demand, 1.0) * 100, 2) if power_demand else 0

        result.append(dict(
            charger_id=charger_id,
            demand_fraction=demand_fraction,
            clouds=clouds,
            cloud_scaling=cloud_scaling,
            grid_power_percentage=round(100 * max(0, 1 - (solar_power_now / power_demand)) if power_demand else 100, 2),
            solar_power_used=round(min(solar_power_now, power_demand), 2),
            charger_power_demand=power_demand,
            grid_power_usage=round(max(0, power_demand - solar_power_now), 2),
            residual_solar_power=round(max(0, solar_power_now - power_demand), 2),
            group_id=group_id,
            group_solar_generated=0,
            monthly_production=monthly_kwh,
            hourly_production=hour_fraction,
            installed_capacity=installed_capacity,
            efficiency=efficiency,
            timestamp_cyprus=cyprus_now.strftime("%Y-%m-%d %H:%M:%S.%f%z"),
            ghi_clear_sky=round(clear_sky_ghi, 2),
            ghi_estimated=round(ghi_estimated, 2),
            solar_power_generated=round(solar_power_now, 2),
            solar_power_estimate=solar_power_percentage,
            power_demand=power_demand
        ))

        print(f"[{charger_id}] hour: {current_hour}, hour_fraction: {hour_fraction}, clouds: {clouds}, cloud_scaling: {cloud_scaling}, solar_power_now: {solar_power_now}, power_demand: {power_demand}")

    for entry in result:
        gid = entry["group_id"]
        entry["group_solar_generated"] = round(group_hourly_totals[gid], 2)


    # Insert group totals into the database
    for group_id, total_kwh in group_hourly_totals.items():
        cursor.execute(
            "INSERT INTO MicroGridHourlyGeneration (GroupID, Hour, Date, SolarGenerated_kWh, CloudCover) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(GroupID, Hour, Date) DO UPDATE SET "
            "SolarGenerated_kWh = excluded.SolarGenerated_kWh, "
            "CloudCover = excluded.CloudCover",
            (group_id, current_hour, date_str, round(total_kwh, 2), round(clouds, 2))
        )

    conn.commit()
    conn.close()
    return result

def estimate_solar_power(clouds, timestamp_cyprus):
    """Estimate solar power based on cloud coverage and time of day."""
    
    hour = datetime.strptime(timestamp_cyprus, "%Y-%m-%d %H:%M:%S.%f%z").hour
    
    SUNRISE_HOUR = 6  
    SUNSET_HOUR = 19 

    if hour < SUNRISE_HOUR or hour >= SUNSET_HOUR:
        return 0  # Solar panels do not generate power at night

    if clouds < 25:
        return 80 + 20 * (1 - clouds / 25)  
    elif 25 <= clouds <= 75:
        return 40 + (75 - clouds) / 50 * 40  
    else:
        return max(0, 40 - (clouds - 75) / 25 * 40)

def get_ranking_chargers(lat, lng, derouting_cost, charger_availability,
                         sustainable_charging_level, coordinatesEV, radius, fNodes, nearby_chargers):
    # previous_center = [0, 0]  # Track the previous center
    global_ranking_chargers = []

    for node in fNodes:
        dataOfNode = node.split(' ')
        center = [float(dataOfNode[2]), float(dataOfNode[1])]

        # Recalculate only if new center is >5km away
        # if geodesic(previous_center, (lat, lng)).km > 5:
        filtered_coordinatesEV = []
        farthest_point = 0
        greenestCharger = 0
        for coord in coordinatesEV:
            charger_distance = geodesic((lat, lng), (coord[0], coord[1])).km
            if charger_distance <= radius:
                filtered_coordinatesEV.append(coord)
                if charger_distance > farthest_point:
                    farthest_point = charger_distance
                if coord[3] > greenestCharger:
                    greenestCharger = coord[3]
        farthest_point *= 2  # For round trip
            # previous_center = center
        # else:
            # continue  # Skip if not far enough from previous

        # Evaluate eco-score per charger
        for coord in filtered_coordinatesEV:
            distance = geodesic((lat, lng), (coord[0], coord[1])).km

            # Skip out-of-radius again (optional, safety)
            if distance > radius:
                continue

            # Travel calculations
            travel_to = geodesic((lat, lng), (coord[0], coord[1])).km
            mins_to_arrive = travel_to

            try:
                travel_back_next = geodesic((coord[0], coord[1]),
                                            (float(fNodes[int(dataOfNode[0]) + 1].split(' ')[2]),
                                             float(fNodes[int(dataOfNode[0]) + 1].split(' ')[1]))).km
            except:
                travel_back_next = farthest_point / 2

            try:
                travel_back_prev = geodesic((coord[0], coord[1]),
                                            (float(fNodes[int(dataOfNode[0]) - 1].split(' ')[2]),
                                             float(fNodes[int(dataOfNode[0]) - 1].split(' ')[1]))).km
            except:
                travel_back_prev = farthest_point / 2

            # Total travel cost (round trip logic)
            travel_total = travel_to + min(travel_back_next, travel_back_prev, travel_to)
            travelScore = 100 - ((travel_total * 100) / farthest_point)

            # Solar usage score (normalized)
            solarUsageScore = (coord[3] * 100) / greenestCharger if greenestCharger > 0 else 0

            # ETA penalty
            if mins_to_arrive > 45:
                solarUsageScore /= 4
            elif mins_to_arrive > 30:
                solarUsageScore /= 3
            elif mins_to_arrive > 15:
                solarUsageScore /= 2

            availability = (coord[4] + coord[5]) / 2

            ecocharge_score = (
                (travelScore * derouting_cost) +
                (availability * charger_availability) +
                (solarUsageScore * sustainable_charging_level)
            )

            charger_id = coord[6]  # Get the charger ID you stored in Step 1

            # Search for the full charger info from nearby_chargers
            charger_meta = next((c for c in nearby_chargers if c.get('charger_id') == charger_id), {})
            location_name = charger_meta.get('LocationName', 'Unknown')
            name = charger_meta.get('name', f'Charger {charger_id}')

            # Construct a dictionary for the charger
            charger_dict = {
                "charger_id": charger_id,
                "latitude": coord[0],
                "longitude": coord[1],
                "eco_score": round(ecocharge_score, 2),
                "mins_to_arrive": round(mins_to_arrive, 2),
                "availability": round(availability, 2),
                "travel_score": round(travelScore, 2),
                "solar_score": round(solarUsageScore, 2),
                "distance": round(distance, 2),
                "name": name,
                "location": location_name,
                "address": charger_meta.get("Address", "Unknown"),
                "power": charger_meta.get("power", "N/A"),
                "types": charger_meta.get("types", []),
                "stalls": charger_meta.get("stalls", 1)
            }

            global_ranking_chargers.append(charger_dict)

        # Sort globally by ecocharge score
    seen = set()
    unique_ranked = []
    for c in global_ranking_chargers:
        if c['name'] not in seen:
            unique_ranked.append(c)
            seen.add(c['name'])

    # Then sort and return top 5
    unique_ranked.sort(key=lambda x: x["eco_score"], reverse=True)

    return unique_ranked[:5]  # Return top 5 chargers

# API to fetch all chargers from DB
@app.route('/api/chargers', methods=['GET'])
def get_chargers():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT 
    c.id, 
    c.LocationName AS name,
    GROUP_CONCAT(ct.TypeName) AS types,
    c.Power, c.Available, c.latitude, c.longitude, c.Address, c.stalls
    FROM Chargers c
    LEFT JOIN ChargerPlugTypes cp ON c.id = cp.ChargerID
    LEFT JOIN ChargerType ct ON cp.PlugType = ct.TypeID
    GROUP BY c.id;
    """)
    
    chargers_map = {}
    for row in cursor.fetchall():
        charger_id = row[0]
        if charger_id not in chargers_map:
            chargers_map[charger_id] = {
                "charger_id": charger_id,
                "name": row[1],
                "template": row[2],
                "power": row[3],
                "enabled": row[4],
                "latitude": row[5],
                "longitude": row[6],
                "Address": row[7],
                "stalls": row[8],
                "LocationName": row[1],
                "types": set()
            }
        # Add plug types from GROUP_CONCAT
        if row[2]:
            plug_types = row[2].split(",")
            chargers_map[charger_id]["types"].update(plug_types)
    # Convert to list and turn types into list
    chargers_from_db = []
    for charger in chargers_map.values():
        charger["types"] = list(charger["types"])
        chargers_from_db.append(charger)
    
    conn.close()

    # Fetch solar power data from the weather API function
    solar_data = get_all_weather_data()

    # Create a dictionary for quick lookup of solar data by charger_id
    solar_map = {s["charger_id"]: s for s in solar_data}

    # Merge solar power data with charger data
    for charger in chargers_from_db:
        solar_info = solar_map.get(charger["charger_id"])
        if solar_info:
            charger["solar_power_estimate"] = solar_info["solar_power_estimate"]
            charger["grid_power_percentage"] = solar_info["grid_power_percentage"]
        else:
            charger["solar_power_estimate"] = 0
            charger["grid_power_percentage"] = "N/A"

    return jsonify(chargers_from_db), 200

# API to add a charger
@app.route('/api/chargers', methods=['POST'])
def add_charger():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"}), 401

    user_id = session['user_id']
    charger_data = request.json

    user_given_name = charger_data.get('name')
    charger_type = charger_data.get('type', 'custom')
    template = charger_data.get('template')
    status = charger_data.get('status', 'C')
    power = charger_data.get('power')
    enabled = charger_data.get('enabled', True)
    loadpoint_id = charger_data.get('loadpointID')

    if not all([user_given_name, template, power, loadpoint_id]):
        return jsonify({"error": "Missing required fields"}), 400

    # Load existing evcc.yaml
    config = load_config()

    # Ensure loadpoints exist before adding a charger
    if not config.get("loadpoints"):
        return jsonify({"error": "No loadpoints found in evcc.yaml"}), 400

    # Find the last added loadpoint
    latest_loadpoint = config["loadpoints"][-1] if config["loadpoints"] else None

    if not latest_loadpoint:
        return jsonify({"error": "Loadpoint not found in evcc.yaml"}), 400

    try:
        # Insert charger into database and retrieve ID
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Charger (name, type, template, status, power, enabled, LoadpointID, UserID) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_given_name, charger_type, template, status, power, enabled, loadpoint_id, user_id)
        )
        conn.commit()
        conn.close()

        charger_id = get_next_charger_id(config)  # Get charger_id from evcc.yaml

        # Format charger name as "charger_[charger_id]"
        charger_name = f"charger_{charger_id}"
        meter_name = f"meter_{charger_name}"

         # Update the existing loadpoint instead of adding a new one
        latest_loadpoint["charger"] = charger_name
        latest_loadpoint["meter"] = meter_name
        
        randomIndex = math.floor(random.random() * 2)

        # Add the new charger
        charger_entry = {
            "name": charger_name,
            "type": charger_type,
            "enable": {
                "source": "js",
                "vm": "shared",
                "script": f'logState();\nvar lp = state.loadpoints[{randomIndex}];\nlp.enabled = enable;\nif (lp.enabled) lp.chargepower = lp.maxcurrent * 230 * lp.phases; else lp.chargepower = 0;'
            },
            "enabled": {
                "source": "js",
                "vm": "shared",
                "script": f'state.loadpoints[{randomIndex}].enabled;'
            },
            "status": {
                "source": "js",
                "vm": "shared",
                "script": f'if (state.loadpoints[{randomIndex}].enabled) "C"; else "B";'
            },
            "maxcurrent": {
                "source": "js",
                "vm": "shared",
                "script": f'logState();\nvar lp = state.loadpoints[{randomIndex}];\nlp.maxcurrent = maxcurrent;\nif (lp.enabled) lp.chargepower = lp.maxcurrent * 230 * lp.phases; else lp.chargepower = 0;'
            }
        }
        config.setdefault("chargers", []).append(charger_entry)

        # Add a corresponding meter
        meter_entry = {
            "name": meter_name,
            "type": "custom",
            "power": {
                "source": "js",
                "vm": "shared",
                "script": f"state.loadpoints[{randomIndex}].chargepower;"
            }
        }
        config.setdefault("meters", []).append(meter_entry)

        # Save changes to evcc.yaml
        save_config(config)

        return jsonify({"message": "Charger added successfully", "charger_id": charger_id}), 201

    except sqlite3.Error as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

# API Endpoint to get all loadpoints
@app.route('/api/loadpoints', methods=['GET'])
def get_loadpoints():
    config = load_config()
    return jsonify(config.get('loadpoints', [])), 200

#API Endpoint to add a loadpoint
@app.route('/api/loadpoints', methods=['POST'])
def add_loadpoint():

    data = request.json

    title = data.get('title')
    mode = data.get('mode')
    vehicle_title = data.get('vehicleTitle')

    if not title or not mode:
        return jsonify({"error": "Title and Mode are required"}), 400

    try:
        conn = connect_db()
        cursor = conn.cursor()

        # Insert loadpoint into the database
        cursor.execute("""
            INSERT INTO Loadpoints (title, mode, vehicle)
            VALUES (?, ?, ?)
        """, (title, mode, vehicle_title))
        
        loadpoint_id = cursor.lastrowid  # Get the new loadpoint ID
        conn.commit()
        conn.close()

        config = load_config()

        if "loadpoints" not in config:
            config["loadpoints"] = []

        # Add the new loadpoint entry
        loadpoint_entry = {
            "title": title,
            "charger": None,  # Will be updated when a charger is added
            "mode": mode,
            "meter": None,  # Will be updated when a charger is added
            "vehicle": f"vehicle_5"
        }
        config["loadpoints"].append(loadpoint_entry)

        update_state_loadpoints(config, loadpoint_id)

        # Save updated evcc.yaml
        save_config(config)

        return jsonify({"message": "Loadpoint added successfully", "loadpointID": loadpoint_id}), 201

    except sqlite3.Error as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

@app.route('/')
def home():
    vehicle_data = get_vehicle_data()
    return render_template("index.html", vehicle_data=vehicle_data)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')

    if request.method == 'POST':
        name = request.form['name']
        surname = request.form['surname']
        email = request.form['email']
        password = request.form['password']

        is_operator = 'is_operator' in request.form
        role = "Operator" if is_operator else "User"

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        try:
            conn = connect_db()
            cursor = conn.cursor()

            # Check if the email already exists
            cursor.execute('SELECT Email FROM User WHERE Email = ?', (email,))
            existing_user = cursor.fetchone()

            if existing_user:
                return render_template('signup.html', error_message="Email already exists. Please use a different email.")

            cursor.execute('''
                INSERT INTO User (Name, Surname, Email, Password, Role)
                VALUES (?, ?, ?, ?, ?)
            ''', (name, surname, email, hashed_password.decode('utf-8'), role))
            conn.commit()
            conn.close()

            return redirect(url_for('signin'))

        except sqlite3.Error as e:
            return f"An error occurred: {e}"

    
@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Query the database to check if the email exists
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM User WHERE Email = ?', (email,))
        user = cursor.fetchone()
        conn.close()

        if user and bcrypt.checkpw(password.encode('utf-8'), user[4].encode('utf-8')):
            session["user_id"] = user[0]
            session["username"] = user[1]
            return redirect(url_for('dashboard'))
        else:
            return render_template('signin.html', error_message="Invalid email or password.")
    return render_template('signin.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('signin'))

@app.route('/dashboard')
def dashboard():
    vehicle_data = get_vehicle_data()
    return render_template("index.html", vehicle_data=vehicle_data)

@app.route('/solar_power_all', methods=['GET'])
def get_all_solar_power():
    chargers_data = get_all_weather_data()
    if not chargers_data:
        return jsonify({"error": "No weather data available"}), 404

    return jsonify({"chargers": chargers_data})

@app.route('/nodes', methods=['POST', 'GET'])
def receive_nodes():
    try:
        data = request.get_json()
        nodes = data.get('nodesList', [])
        total_nodes = len(nodes)

        if(total_nodes < 15):
            fNodes = nodes
        else:
            step = total_nodes // 14  # 14 steps = 15 points
            fNodes = [nodes[i] for i in range(0, total_nodes, step)]

        # Save to file (nodes.txt)
        with open('nodes.txt', 'w') as f:
            for node in fNodes:
                f.write(f"{node}\n")

        return jsonify({"status": "success", "message": "Nodes saved successfully!"}, fNodes)
    except Exception as e:
        print("Error receiving nodes:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/nearby_chargers', methods=['POST'])
def get_nearby_chargers():
    data = request.get_json()

    lat = float(data['lat'])
    lng = float(data['lng'])
    derouting_cost = float(data['derouting_cost'])
    charger_availability = float(data['charger_availability'])
    sustainable_charging_level = float(data['sustainable_charging_level'])
    radius = float(data['radius'])

    # Get charger and solar data
    chargers = get_chargers()[0].get_json()

    selected_types = set(data.get("plug_types", []))
    if selected_types:
        chargers = [c for c in chargers if selected_types & set(c.get("types", []))]

    origin = (lat, lng)

    nearby_chargers = []
    count = 0

    for charger in chargers:
        if charger['latitude'] is None or charger['longitude'] is None:
            continue

        charger_coords = (charger['latitude'], charger['longitude'])

        # Calculate haversine distance
        dist = haversine_distance(lat, lng, charger_coords[0], charger_coords[1])
        
        if dist <= radius:
            # Compute score based on user preferences
            score = (
                (100 - dist) * derouting_cost +
                (charger.get("enabled", True)) * charger_availability * 100 +
                charger.get("solar_power_estimate", 0) * sustainable_charging_level
            )
            charger['score'] = round(score, 2)
            charger['distance_km'] = round(dist, 2)
            nearby_chargers.append(charger)

            coordinatesEV = []
            for charger in nearby_chargers:
                if charger['latitude'] and charger['longitude']:
                    coordinatesEV.append([
                        charger['latitude'],
                        charger['longitude'],
                        0,
                        charger.get("solar_power_estimate", 0),
                        int(charger.get("enabled", True)),
                        int(charger.get("enabled", True)),
                        charger.get("charger_id")
                    ])

            count += 1
            print(f"Charger {charger['name']} - Score: {charger['score']} - Distance: {charger['distance_km']}km")

    print(f"🔍 Found {count} nearby chargers within {radius} km radius.")
        # Sort by score descending
    nearby_chargers = sorted(nearby_chargers, key=lambda x: x['score'], reverse=True)

    # Read and sort fNodes
    try:
        with open("nodes.txt", "r") as file:
            all_nodes = file.readlines()
            fNodes = all_nodes
    except FileNotFoundError:
        return jsonify({"error": "nodes.txt not found"}), 500

    # Get top ranked chargers
    ranked_chargers = get_ranking_chargers(
        lat, lng, derouting_cost, charger_availability,
        sustainable_charging_level, coordinatesEV, radius, fNodes, nearby_chargers
    )

    for charger in ranked_chargers:
        print(f"Ranked Charger at {charger['latitude']}, {charger['longitude']} — Eco Score: {charger['eco_score']}")

    for charger in ranked_chargers:
        charger_id = charger['charger_id']
        lat_str = round(charger['latitude'], 6)
        lng_str = round(charger['longitude'], 6)
        eco_score = round(charger['eco_score'], 2)
        mins_to_arrive = round(charger['mins_to_arrive'], 2)
        availability = round(charger['availability'], 2)
        travel_score = round(charger['travel_score'], 2)
        solar_score = round(charger['solar_score'], 2)
        name = charger['name']
        location = charger['location']
        address = charger['address']
        power = charger['power']
        charger_types = charger.get('types', ['Unknown'])

        print(f"🔋 {charger_id} {location} at ({lat_str}, {lng_str}) — {location} | Eco: {eco_score} | Travel: {travel_score} | Solar: {solar_score} | Avail: {availability} | ETA: {mins_to_arrive} mins")

    return jsonify({
        "latitude": lat,
        "longitude": lng,
        "radius": radius,
        "nearby_chargers": ranked_chargers
    })

@app.route('/forecasted_ranked_chargers', methods=['POST'])
def forecasted_ranked_chargers():
    try:
        data = request.get_json()
        lat = float(data['lat'])
        lng = float(data['lng'])
        derouting_cost = float(data['derouting_cost'])
        charger_availability = float(data['charger_availability'])
        sustainable_charging_level = float(data['sustainable_charging_level'])
        radius = float(data['radius'])
        forecast_time = data['forecast_time']

        # Parse forecast time
        dt = datetime.strptime(forecast_time, "%Y-%m-%d %H:%M:%S")
        forecast_hour = dt.hour
        forecast_month = dt.month
        timestamp_str = dt.replace(tzinfo=ZoneInfo("Europe/Nicosia")).strftime("%Y-%m-%d %H:%M:%S%z")

        # Fetch chargers from DB
        chargers = get_chargers()[0].get_json()

        # Apply plug filtering
        selected_types = set(data.get("plug_types", []))
        if selected_types:
            chargers = [c for c in chargers if selected_types & set(c.get("types", []))]

        solar_scores = data.get("solar_scores", {})  # { charger_id: solar_pct }

        # After fetching chargers
        for charger in chargers:
            cid = charger["charger_id"]
            charger["solar_power_estimate"] = solar_scores.get(str(cid), 0)
            print(f"Using forecasted solar for charger {cid}: {charger['solar_power_estimate']}%")

        # Now apply get_ranking_chargers logic
        coordinatesEV = []
        for c in chargers:
            if c['latitude'] and c['longitude']:
                coordinatesEV.append([
                    c['latitude'],
                    c['longitude'],
                    0,
                    c.get("solar_power_estimate", 0),
                    int(c.get("enabled", True)),
                    int(c.get("enabled", True)),
                    c.get("charger_id")
                ])

        # Use recent nodes from file
        with open("nodes.txt", "r") as file:
            fNodes = file.readlines()

        ranked = get_ranking_chargers(
            lat, lng,
            derouting_cost, charger_availability, sustainable_charging_level,
            coordinatesEV, radius, fNodes, chargers
        )

        return jsonify({"ranked_chargers": ranked})

    except Exception as e:
        print("❌ Error in /forecasted_ranked_chargers:", e)
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/select_vehicle', methods=['POST'])
def select_vehicle():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"}), 401

    data = request.json
    vehicle_id = data.get('vehicleID')

    if vehicle_id is None:
        return jsonify({"error": "Missing vehicleID"}), 400

    user_id = session['user_id']

    conn = connect_db()
    cursor = conn.cursor()

    # Always insert a new user-vehicle pair
    cursor.execute(
        "INSERT INTO userVehicle (userID, vehicleID) VALUES (?, ?)",
        (user_id, vehicle_id)
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "Vehicle added successfully"})


@app.route('/api/user_vehicle')
def get_user_vehicles():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"}), 401

    try:
        user_id = session['user_id']
        conn = connect_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get ALL vehicle info for this user
        cursor.execute("""
            SELECT v.vehicleID as vehicle_id, v.make, v.model, v.batteryCapacity, v.consumptionRate
            FROM userVehicle uv
            JOIN Vehicle v ON uv.vehicleID = v.vehicleID
            WHERE uv.userID = ?
        """, (user_id,))
        rows = cursor.fetchall()

        vehicles = []

        for row in rows:
            # Fetch plug types for this vehicle
            cursor.execute("""
                SELECT chargerType
                FROM VehicleChargerTypes
                WHERE vehicleID = ?
            """, (row["vehicle_id"],))
            plug_types = [r[0] for r in cursor.fetchall()]

            vehicles.append({
                "vehicle_id": row["vehicle_id"],
                "make": row["make"],
                "model": row["model"],
                "battery_capacity": row["batteryCapacity"],
                "consumption_rate": row["consumptionRate"],
                "plug_types": plug_types
            })

        conn.close()

        return jsonify(vehicles)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/microgrids')
def get_microgrid_clusters():
    conn = sqlite3.connect("MicroGrid.db")
    cursor = conn.cursor()

    # Fetch all chargers and their group
    cursor.execute("""
        SELECT m.GroupID, c.latitude, c.longitude, c.id, c.LocationName
        FROM Microgrids m
        JOIN Chargers c ON c.id = m.ChargerID
    """)
    rows = cursor.fetchall()
    conn.close()

    # Organize by group
    clusters = {}
    for group_id, lat, lon, charger_id, name in rows:
        clusters.setdefault(group_id, []).append({
            "lat": lat,
            "lon": lon,
            "charger_id": charger_id,
            "name": name
        })

    return jsonify(clusters)

@app.route('/api/microgrid_solar_scores')
def microgrid_solar_scores():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # Map: charger_id -> group_id
    cursor.execute("SELECT ChargerID, GroupID FROM Microgrids")
    group_map = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    # Fetch per-charger solar data
    all_weather_data = get_all_weather_data()

    group_solar_sum = {}
    group_counts = {}

    for entry in all_weather_data:
        charger_id = entry["charger_id"]
        solar_score = entry["solar_power_estimate"]  # or "solar_power_generated"

        if charger_id in group_map:
            group_id = group_map[charger_id]
            group_solar_sum[group_id] = group_solar_sum.get(group_id, 0) + solar_score
            group_counts[group_id] = group_counts.get(group_id, 0) + 1

    # Compute average per group
    group_avg_solar = {
        gid: group_solar_sum[gid] / group_counts[gid]
        for gid in group_solar_sum
    }

    return jsonify(group_avg_solar)

@app.route("/api/top_microgrids", methods=["POST"])
def get_top_microgrids():
    data = request.get_json()
    
    lat = float(data['lat'])
    lng = float(data['lng'])
    derouting_cost = float(data['derouting_cost'])
    charger_availability = float(data['charger_availability'])
    sustainable_charging_level = float(data['sustainable_charging_level'])
    radius = float(data['radius'])

    chargers = get_chargers()[0].get_json()

    selected_types = set(data.get("plug_types", []))
    if selected_types:
        chargers = [c for c in chargers if selected_types & set(c.get("types", []))]

    # Build coordinatesEV list for ranking
    coordinatesEV = []
    for charger in chargers:
        if charger['latitude'] and charger['longitude']:
            coordinatesEV.append([
                charger['latitude'],
                charger['longitude'],
                0,
                charger.get("solar_power_estimate", 0),
                int(charger.get("enabled", True)),
                int(charger.get("enabled", True)),
                charger.get("charger_id")
            ])

    try:
        with open("nodes.txt", "r") as file:
            all_nodes = file.readlines()
            fNodes = all_nodes
    except FileNotFoundError:
        return jsonify({"error": "nodes.txt not found"}), 500

    # Run ranking
    ranked_chargers = get_ranking_chargers(
        lat, lng, derouting_cost, charger_availability,
        sustainable_charging_level, coordinatesEV, radius, fNodes, chargers
    )

    # Step 2: Group by MicroGrid
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT GroupID, ChargerID FROM Microgrids")
    grid_map = cursor.fetchall()
    conn.close()

    group_scores = defaultdict(list)
    charger_to_group = {charger_id: group_id for group_id, charger_id in grid_map}

    for charger in ranked_chargers:
        cid = charger.get("charger_id") or charger.get("id")
        gid = charger_to_group.get(cid)
        if gid is not None:
            group_scores[gid].append(charger["eco_score"])

    avg_group_scores = [
        {"group_id": gid, "avg_score": sum(scores) / len(scores), "count": len(scores)}
        for gid, scores in group_scores.items()
    ]

    top_microgrids = sorted(avg_group_scores, key=lambda x: x["avg_score"], reverse=True)[:2]

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.GroupID, c.latitude, c.longitude
        FROM Microgrids m
        JOIN Chargers c ON c.id = m.ChargerID
    """)
    all_coords = cursor.fetchall()
    conn.close()

    # Organize by group
    group_coords = {}
    for gid, lat, lon in all_coords:
        if lat is not None and lon is not None:
            group_coords.setdefault(gid, []).append((lat, lon))

    # Compute centroids
    for g in top_microgrids:
        gid = g["group_id"]
        coords = group_coords.get(gid, [])
        if coords:
            avg_lat = sum([c[0] for c in coords]) / len(coords)
            avg_lon = sum([c[1] for c in coords]) / len(coords)
            g["center"] = [avg_lat, avg_lon]
        else:
            g["center"] = [None, None]

    return jsonify(top_microgrids)

@app.route('/api/create_microgrid', methods=['POST'])
def create_microgrid_full():
    data = request.get_json()

    name = data.get("name")
    city = data.get("city")
    country = data.get("country")
    capacity = data.get("capacity_kwp")
    efficiency = data.get("efficiency")
    inverter_limit = data.get("inverter_limit")
    degradation = data.get("degradation_rate")
    annual_kwh = data.get("annual_production")
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    chargers = data.get("chargers", [])
    operator_id = session.get("user_id", 1)

    # Monthly + hourly solar production weights
    monthly_weights = {
        1: 0.05, 2: 0.06, 3: 0.08, 4: 0.10,
        5: 0.11, 6: 0.11, 7: 0.12, 8: 0.11,
        9: 0.09, 10: 0.07, 11: 0.05, 12: 0.05
    }

    hourly_weights = [
        0, 0, 0, 0, 0, 0,
        0.03, 0.07, 0.12, 0.16,
        0.18, 0.20, 0.22, 0.20,
        0.18, 0.15, 0.12, 0.08,
        0.04, 0.02, 0, 0, 0, 0
    ]
    total_hour = sum(hourly_weights)
    hourly_profile = [val / total_hour for val in hourly_weights]

    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()

    # 1. Generate new GroupID
    c.execute("SELECT MAX(GroupID) FROM Microgrids")
    result = c.fetchone()
    new_group_id = (result[0] or 0) + 1

    # 2. Insert into MicroGridDetails
    c.execute("""
        INSERT INTO MicroGridDetails (
            GroupID, Name, City, Country, InstalledCapacity_kWp,
            Efficiency, InverterLimit_kW, DegradationRate,
            OperatorUserID, Latitude, Longitude
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        new_group_id, name, city, country, capacity,
        efficiency, inverter_limit, degradation,
        operator_id, latitude, longitude
    ))

    # 3. Insert new chargers and link them
    for charger in chargers:
        lat = charger["lat"]
        lng = charger["lng"]
        location_name = charger.get("location")
        address = charger.get("address")
        available = charger.get("available", 0)
        stalls = charger.get("stalls", 1)
        power = charger.get("power", 0)

        # Insert charger
        c.execute("""
            INSERT INTO Chargers (Latitude, Longitude, LocationName, Address, Available, Stalls, Power, Status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (lat, lng, location_name, address, available, stalls, power, 1))

        charger_id = c.lastrowid

        # Link to microgrid
        c.execute("INSERT INTO Microgrids (GroupID, ChargerID) VALUES (?, ?)", (new_group_id, charger_id))

        # Fetch current weather from OpenWeather API
        weather_url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid=50bf2c5a75636772ee020a9c2cc969db&units=metric"
        try:
            response = requests.get(weather_url)
            if response.status_code == 200:
                weather = response.json()
                temperature = weather['main']['temp']
                clouds = weather['clouds']['all']
                humidity = weather['main']['humidity']
                wind_speed = weather['wind']['speed']
                wind_direction = weather['wind'].get('deg', None)

                timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

                # Insert into WeatherForecast table
                c.execute('''
                    INSERT INTO WeatherForecast 
                    (ChargerID, Temperature, Clouds, Humidity, WindSpeed, WindDirection, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (charger_id, temperature, clouds, humidity, wind_speed, wind_direction, timestamp))
            else:
                print(f"Weather API failed for Charger {charger_id}: HTTP {response.status_code}")
        except Exception as e:
            print(f"Error fetching weather for Charger {charger_id}: {e}")

    # 4. Insert monthly production
    for month, weight in monthly_weights.items():
        est_kwh = annual_kwh * weight
        c.execute("""
            INSERT INTO MicroGridMonthlyProduction (GroupID, Month, EstimatedProduction_kWh)
            VALUES (?, ?, ?)
        """, (new_group_id, month, est_kwh))

    for plug_type in charger.get("types", []):
        c.execute("INSERT INTO ChargerPlugTypes (ChargerID, PlugType) VALUES (?, ?)", (charger_id, plug_type))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "group_id": new_group_id})

@app.route("/api/my_microgrids")
def get_my_microgrids():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify([])

    conn = sqlite3.connect("MicroGrid.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT GroupID, Name, City, Country, InstalledCapacity_kWp, Efficiency
        FROM MicroGridDetails
        WHERE OperatorUserID = ?
    """, (user_id,))
    result = cursor.fetchall()
    conn.close()

    return jsonify([
        {
            "group_id": row[0],
            "name": row[1],
            "city": row[2],
            "country": row[3],
            "capacity_kwp": row[4],
            "efficiency": row[5]
        } for row in result
    ])

def estimate_solar_power2(clouds, timestamp_cyprus):
    dt = datetime.strptime(timestamp_cyprus, "%Y-%m-%d %H:%M:%S%z")
    hour = dt.hour
    print("hour: ", hour)

    if hour < 6 or hour >= 19:
        return 0

    if clouds < 25:
        return 80 + 20 * (1 - clouds / 25)
    elif 25 <= clouds <= 75:
        return 40 + (75 - clouds) / 50 * 40
    else:
        return max(0, 40 - (clouds - 75) / 25 * 40)

@app.route('/api/daily_forecast')
def daily_forecast():
    with open('static/forecast/daily_forecast.json') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/api/forecast_solar_scores', methods=['POST'])
def forecast_solar_scores():
    try:
        data = request.get_json()
        forecast_time_str = data.get("forecast_time")
        forecast_clouds = data.get("clouds", {})  # {charger_id: clouds_value}

        if not forecast_time_str or not forecast_clouds:
            return jsonify({"error": "Missing forecast_time or clouds data"}), 400

        try:
            forecast_time = datetime.strptime(forecast_time_str, "%Y-%m-%d %H:%M:%S")
            cyprus_time = forecast_time.replace(tzinfo=ZoneInfo("Europe/Nicosia"))
            forecast_hour = cyprus_time.hour
            forecast_month = cyprus_time.month
        except Exception as e:
            return jsonify({"error": f"Invalid time format: {str(e)}"}), 400

        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Map charger -> group
        cursor.execute("SELECT ChargerID, GroupID FROM Microgrids")
        charger_to_group = {row[0]: row[1] for row in cursor.fetchall()}

        # Group details
        cursor.execute("SELECT GroupID, InstalledCapacity_kWp, Efficiency FROM MicroGridDetails")
        grid_details = {row[0]: {"capacity": row[1], "efficiency": row[2]} for row in cursor.fetchall()}

        # Monthly production
        cursor.execute("SELECT GroupID, Month, EstimatedProduction_kWh FROM MicroGridMonthlyProduction")
        monthly_prod = {}
        for group_id, month, kwh in cursor.fetchall():
            monthly_prod.setdefault(group_id, {})[int(month)] = kwh

        # Hourly profile
        cursor.execute("SELECT Hour, RelativeProduction FROM MicroGridHourlyProfile")
        hourly_profile = dict(cursor.fetchall())

        # Charger power demand
        cursor.execute("SELECT id, power FROM Chargers")
        charger_power_demand = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

        results = {}

        for charger_id_str, clouds in forecast_clouds.items():
            try:
                charger_id = int(charger_id_str)
                group_id = charger_to_group.get(charger_id)
                if not group_id:
                    continue

                monthly_kwh = monthly_prod.get(group_id, {}).get(forecast_month, 0)
                installed_capacity = grid_details.get(group_id, {}).get("capacity", 0)
                efficiency = grid_details.get(group_id, {}).get("efficiency", 1.0)
                hour_fraction = hourly_profile.get(forecast_hour, 0)
                demand_kw = charger_power_demand.get(charger_id, 0) or 1  # prevent division by 0

                # Solar estimation based on GHI
                cloud_fraction = clouds / 100.0
                clear_sky_ghi = estimate_clear_sky_ghi(forecast_hour)
                ghi_estimated = estimate_ghi(cloud_fraction, clear_sky_ghi)
                solar_power_kw = calculate_pv_output(ghi_estimated, installed_capacity, efficiency)
                cloud_scaling = ghi_estimated / clear_sky_ghi if clear_sky_ghi > 0 else 0

                print(f"Charger {charger_id} - GHI: {ghi_estimated}, Cloud Scaling: {cloud_scaling}, clouds: {clouds}")

                # Estimate daily and hourly production
                daily_kwh = monthly_kwh / 30.0 * 0.5 if monthly_kwh else 0
                hourly_kwh_estimated = daily_kwh * hour_fraction * efficiency * cloud_scaling

                # Final production correction
                if hourly_kwh_estimated > 0:
                    solar_power_estimate = min(solar_power_kw, hourly_kwh_estimated)
                else:
                    solar_power_estimate = 0

                # Calculate solar percentage relative to charger power demand
                solar_percentage = min(100, round((solar_power_estimate / demand_kw) * 100, 2))

                results[charger_id] = solar_percentage
            except Exception as e:
                print(f"❌ Error forecasting charger {charger_id}: {e}")
                continue

        return jsonify(results)

    except Exception as e:
        print("❌ Forecast Error:", e)
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/charger_types')
def get_charger_types():
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute("SELECT TypeID, TypeName FROM ChargerType")
    types = [{"id": row[0], "name": row[1]} for row in c.fetchall()]
    conn.close()
    return jsonify(types)

#@app.route("/api/forecast_solar_scores", methods=["POST"])
#def forecast_solar_scores():
#    try:
#        data = request.get_json()
#        forecast_time_str = data.get("forecast_time")
#        print("forecast_time_str: ", {forecast_time_str})
#
#        if not forecast_time_str:
#            return jsonify({"error": "Missing forecast_time"}), 400
#
#        forecast_dt = datetime.strptime(forecast_time_str, "%Y-%m-%d %H:%M:%S")
#        print("forecast_dt: ", {forecast_dt})
#        forecast_hour = forecast_dt.hour
#        forecast_month = forecast_dt.month
#
#        # Get microgrid and weather data
#        charger_to_group, grid_details, hourly_profile, monthly_productions = get_microgrid_data()
#
#        conn = connect_db()
#        cursor = conn.cursor()
#        cursor.execute("SELECT id, power FROM Chargers")
#        charger_power_map = dict(cursor.fetchall())
#        conn.close()
#
#        result = []
#
#        for charger_id, group_id in charger_to_group.items():
#            power_demand = charger_power_map.get(charger_id, 0)
#            if group_id not in grid_details:
#                continue
#
#            month_kwh = monthly_productions.get(group_id, {}).get(forecast_month, 0)
#            hour_fraction = hourly_profile.get(forecast_hour, 0)
#            efficiency = grid_details[group_id].get("efficiency", 1.0)
#
#            # We'll simulate clouds as 0 for now (perfect sun)
#            clouds = 0  # Or you could pass cloud % from frontend later
#            solar_eff = estimate_solar_power2(clouds, forecast_dt.replace(tzinfo=ZoneInfo("Europe/Nicosia")).strftime("%Y-%m-%d %H:%M:%S%z")) / 100.0
#            total_solar_power_now = (month_kwh / 30.0) * hour_fraction * efficiency * solar_eff
#
#            solar_power_now = total_solar_power_now  # Assume full power delivered
#            solar_power_percentage = round(min(solar_power_now / power_demand, 1.0) * 100, 2) if power_demand else 0
#
#            result.append({
#                "charger_id": charger_id,
#                "group_id": group_id,
#                "solar_power_estimate": solar_power_percentage,
#                "solar_power_generated": round(solar_power_now, 2),
#                "power_demand": power_demand
#            })
#
#        return jsonify({"forecast": result})
#
#    except Exception as e:
#        print("❌ Forecast Error:", e)
#        import traceback
#        traceback.print_exc()
#        return jsonify({"error": str(e)}), 500


@app.route("/api/microgrid_details/<int:group_id>")
def microgrid_details_api(group_id):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Name, City, Country, InstalledCapacity_kWp, Efficiency, InverterLimit_kW, DegradationRate, Latitude, Longitude, GroupID
        FROM MicroGridDetails
        WHERE GroupID = ?
    """, (group_id,))
    row = cursor.fetchone()

    if not row:
        return jsonify({"error": "Microgrid not found"}), 404

    microgrid = {
        "name": row[0],
        "city": row[1],
        "country": row[2],
        "capacity_kwp": row[3],
        "efficiency": row[4] * 100,
        "inverter_limit_kw": row[5],
        "degradation_rate": row[6],
        "latitude": row[7],
        "longitude": row[8],
        "group_id": row[9]
    }

    cursor.execute("""
        SELECT c.id, c.Latitude, c.Longitude, c.Power, c.Available,
            GROUP_CONCAT(ct.TypeName), wf.Clouds,
            c.LocationName, c.Address, c.Stalls
        FROM Chargers c
        JOIN Microgrids m ON c.id = m.ChargerID
        LEFT JOIN ChargerPlugTypes cp ON c.id = cp.ChargerID
        LEFT JOIN ChargerType ct ON cp.PlugType = ct.TypeID
        LEFT JOIN WeatherForecast wf ON wf.ChargerID = c.id
        WHERE m.GroupID = ?
        GROUP BY c.id
    """, (group_id,))

    chargers = [
        {
            "id": r[0],
            "latitude": r[1],
            "longitude": r[2],
            "power": r[3],
            "available": bool(r[4]),
            "plug_types": r[5].split(",") if r[5] else [],
            "clouds": r[6],
            "location_name": r[7],
            "address": r[8],
            "stalls": r[9] if r[9] else 1
            #"solar_forecast": estimate_solar_power(r[6] or 100, datetime.now(ZoneInfo("Europe/Nicosia")).strftime("%Y-%m-%d %H:%M:%S%z"))
        }
        for r in cursor.fetchall()
    ]

    # Monthly Production
    cursor.execute("SELECT Month, EstimatedProduction_kWh FROM MicroGridMonthlyProduction WHERE GroupID = ?", (group_id,))
    monthly = {str(month): kwh for month, kwh in cursor.fetchall()}
    annual = sum(monthly.values())

    # Hourly Profile (same for all microgrids)
    cursor.execute("SELECT Hour, RelativeProduction FROM MicroGridHourlyProfile")
    hourly = {str(hour): rel for hour, rel in cursor.fetchall()}

    conn.close()
    return jsonify({
        "microgrid": microgrid,
        "chargers": chargers,
        "production": {
            "annual": round(annual, 2),
            "monthly": monthly,
            "hourly": hourly
        }
    })

@app.route('/api/microgrid_hourly_today/<int:group_id>')
def get_hourly_today(group_id):
    now = datetime.now(ZoneInfo("Europe/Nicosia"))
    current_hour = now.hour
    date_str = now.strftime("%Y-%m-%d")

    conn = connect_db()
    cursor = conn.cursor()

    # Fetch actual production + clouds
    cursor.execute("""
        SELECT Hour, SolarGenerated_kWh, CloudCover
        FROM MicroGridHourlyGeneration
        WHERE GroupID = ? AND Date = ?
        ORDER BY Hour
    """, (group_id, date_str))
    rows = cursor.fetchall()

    actual = {}
    clouds = {}
    for hour, solar_kwh, cloud in rows:
        actual[str(hour)] = round(solar_kwh, 2)
        clouds[str(hour)] = f"{int(cloud)}%" if cloud is not None else "?"

    # Efficiency + production
    cursor.execute("SELECT Efficiency FROM MicroGridDetails WHERE GroupID = ?", (group_id,))
    efficiency = cursor.fetchone()[0]

    current_month = now.month
    cursor.execute("""
        SELECT EstimatedProduction_kWh FROM MicroGridMonthlyProduction
        WHERE GroupID = ? AND Month = ?
    """, (group_id, current_month))
    monthly_kwh = cursor.fetchone()[0]
    # daily_kwh = monthly_kwh / 30

    cursor.execute("SELECT Hour, RelativeProduction FROM MicroGridHourlyProfile")
    hourly_profile = dict(cursor.fetchall())

    clear_sky_ghi = estimate_clear_sky_ghi(current_hour)

    # Monthly + hourly expected energy (in kWh)
    daily_kwh = monthly_kwh / 30.0 if monthly_kwh else 0

    # Theoretical max
    theoretical = {}
    for h in range(24):
        ghi = estimate_clear_sky_ghi(h)
        if ghi == 0:
            theoretical[str(h)] = 0
            continue

        #ghi_estimated = estimate_ghi(0.0, ghi)  # simulate no clouds
        cloud_scaling = 1.0
        hourly_kwh = daily_kwh * efficiency * hourly_profile.get(h, 0) * cloud_scaling
        theoretical[str(h)] = round(hourly_kwh, 2)

    return jsonify({
        "actual": actual,
        "theoretical": theoretical,
        "clouds": clouds
    })

@app.route('/api/microgrid/<int:group_id>')
def get_microgrid(group_id):
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT City, Country, InstalledCapacity_kWp, Efficiency,
               InverterLimit_kW, DegradationRate
        FROM MicroGridDetails WHERE GroupID = ?
    """, (group_id,))
    row = c.fetchone()
    conn.close()
    return jsonify({
        "city": row[0],
        "country": row[1],
        "capacity_kwp": row[2],
        "efficiency": row[3],
        "inverter_limit": row[4],
        "degradation": row[5]
    })

@app.route('/api/update_microgrid', methods=['POST'])
def update_microgrid():
    data = request.get_json()
    group_id = data["group_id"]

    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute("""
        UPDATE MicroGridDetails SET
            City = ?, Country = ?, InstalledCapacity_kWp = ?,
            Efficiency = ?, InverterLimit_kW = ?, DegradationRate = ?
        WHERE GroupID = ?
    """, (
        data["city"], data["country"], data["capacity_kwp"],
        data["efficiency"], data["inverter_limit"], data["degradation"],
        group_id
    ))
    conn.commit()
    conn.close()

    return jsonify({"status": "success"})


@app.route('/api/charger/<int:charger_id>')
def get_charger(charger_id):
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT LocationName, Address, Power, Available, Stalls
        FROM Chargers WHERE id = ?
    """, (charger_id,))
    row = c.fetchone()
    conn.close()
    return jsonify({
        "location_name": row[0],
        "address": row[1],
        "power": row[2],
        "available": row[3],
        "stalls": row[4]
    })


@app.route('/api/update_charger', methods=['POST'])
def update_charger():
    data = request.get_json()
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute("""
        UPDATE Chargers SET
            LocationName = ?, Address = ?, Power = ?,
            Available = ?, Stalls = ?
        WHERE id = ?
    """, (
        data["location_name"], data["address"], data["power"],
        data["available"], data["stalls"], data["charger_id"]
    ))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/delete_vehicle', methods=['POST'])
def delete_vehicle():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"}), 401

    data = request.json
    vehicle_id = data.get('vehicleID')

    if vehicle_id is None:
        return jsonify({"error": "Missing vehicleID"}), 400

    user_id = session['user_id']

    conn = connect_db()
    cursor = conn.cursor()

    # Delete the specific vehicle association
    cursor.execute("""
        DELETE FROM userVehicle
        WHERE userID = ? AND vehicleID = ?
    """, (user_id, vehicle_id))

    conn.commit()
    conn.close()

    return jsonify({"message": "Vehicle deleted successfully"})

@app.route('/login/google')
def google_login():
    #session.clear()
    session.pop('_state_google', None)
    redirect_uri = url_for('google_callback', _external=True, _scheme='https')
    print("Before redirect, session contents:", dict(session))
    return google.authorize_redirect(redirect_uri)

@app.route('/login/callback')
def google_callback():
    print("In callback, session contents:", dict(session))
    token = google.authorize_access_token()
    token = google.authorize_access_token()
    user_info = google.parse_id_token(token)
    email = user_info['email']
    name = user_info['given_name']

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT UserID, Role FROM User WHERE Email = ?", (email,))
    user = cursor.fetchone()

    if not user:
        # New user – create with no role yet
        cursor.execute("INSERT INTO User (Name, Surname, Email, Password, Role) VALUES (?, ?, ?, ?, ?)",
                       (name, '', email, '', ''))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        session['user_id'] = user_id
        session['username'] = name
        return redirect(url_for('choose_role'))
    else:
        session['user_id'] = user[0]
        session['username'] = name
        return redirect(url_for('dashboard'))

@app.route('/choose_role', methods=['GET', 'POST'])
def choose_role():
    if request.method == 'POST':
        selected_role = request.form.get('role')
        user_id = session.get('user_id')
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE User SET Role = ? WHERE UserID = ?", (selected_role, user_id))
        conn.commit()
        conn.close()
        return redirect(url_for('dashboard'))
    
    return render_template('choose_role.html')


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0  # Radius of the Earth in kilometers
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * 
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

# Create scheduler
#scheduler = BackgroundScheduler()
#
## Add the scheduled job
#scheduler.add_job(func=get_all_weather_data, trigger="interval", minutes=30)
#
## Start the scheduler
#scheduler.start()
#
## Shut down the scheduler cleanly on exit
#atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001, debug=True)