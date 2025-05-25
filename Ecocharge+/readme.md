EcoCharge+
Author: Eleni Michala

--- Overview ---
EcoCharge+ is a full-stack web application that helps Electric Vehicle (EV) users locate and select the most eco-friendly charging stations based on spatial, 
temporal, and weather-based solar production data. The system integrates a custom-built Flask backend with a rich Leaflet.js frontend to visualize chargers 
and microgrids across a map interface, and a local SQLite database.


--- Project Repository ---

GitHub URL: git@github.com:dmsl/ecocharge.git


--- Deployment Details ---

Server IP: 10.16.20.19
DNS: https://micro-grid.online

Admin Access:
operator1@email.com -> password: pass1
operator2@email.com -> password: pass2
...
operator99@email.com -> password: pass99


--- System Components ---

1. Backend (Python/Flask):	
	app.py: Main server logic, API endpoints, session management, charger ranking.

	update_weather.py: Periodically fetches current weather data for all chargers and updates the SQLite DB.

	daily_forecast_fetcher.py: Retrieves 5-day weather forecasts for each charger and stores them as a JSON file.

	save_actual_production.py: Persists current solar production based on weather and microgrid profiles.

2. Frontend (HTML/JS/CSS):

	index.html: Map interface using Leaflet, Bootstrap for styling, AJAX calls to Flask endpoints, vehicle and plug filters, 
		    eco-score based charger ranking, and real-time route guidance.

3. Database (SQLite - MicroGrid.db):

	Contains tables for: Chargers, Microgrids, MicroGridDetails, WeatherForecast, Vehicle, VehicleChargerTypes
			     Forecasted production via MicroGridHourlyProfile, MicroGridMonthlyProduction

	User-specific data such as User, userVehicle, etc.


--- Key Features ---
	Charger Discovery: View and filter EV chargers by plug type, power, solar efficiency.

	Forecast Slider: Simulate future solar availability using OpenWeather forecast data.

	Eco-Ranking: Suggest top 5 chargers based on solar usage, availability, and travel time.

	MicroGrid Management: Operators can create MicroGrids with chargers and metadata.

	Vehicle Awareness: Users select their EV; supported plugs are auto-highlighted.

	Map Interactivity: View ETA, charger info, toggle cloud layers, draw routes with routing machine.


--- Cron Jobs Setup ---

Automate periodic weather updates and forecast generation using crontab -e:

# Update real-time weather for each charger every hour
0 */1 * * * /usr/bin/python3 /path/to/update_weather.py

# Fetch daily 5-day/3-hour forecasts every 3 hours and log output
* */3 * * * DATABASE_FILE=/path/to/MicroGrid.db /usr/bin/python3 /path/to/daily_forecast_fetcher.py >> /path/to/cron2.log 2>&1

# Save actual solar production for each microgrid once every hour
0 * * * * DATABASE_FILE=/path/to/MicroGrid.db /usr/bin/python3 /path/to/save_actual_production.py >> /path/to/cron.log 2>&1


--- Setup Instructions ---

1. Install Requirements:
	pip install flask flask_session geopy requests bcrypt

2. Prepare the Database:
	Ensure MicroGrid.db is present in the root directory or set the path via the DATABASE_FILE environment variable.

3. Run the Flask App:
	python app.py

	(The app will be accessible on http://localhost:5001)

4. Optional First-Time Scripts:

	python3 update_weather.py
	python3 daily_forecast_fetcher.py


--- Authentication ---

	- Users can sign up and log in.
	- Operators (flagged during signup) gain access to MicroGrid creation and management tools.

