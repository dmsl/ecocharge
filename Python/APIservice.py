from flask import Flask, jsonify, request
from flask_cors import CORS
from geopy.distance import geodesic
import json

# Create a Flask application instance named 'app'
app = Flask(__name__)

# Enable Cross-Origin Resource Sharing (CORS) for specific routes
CORS(app, resources={r"/chargers": {"origins": "*"},
                     r"/nearby_chargers": {"origins": "*"},
                     r"/nodes": {"origins": "*"}})

# Open the file "solarDataALL.txt" in read mode
fSolarData = open(r'solarDataALL.txt', "r")
# Read the contents of the "solarDataALL.txt" file and store them in fSolarData
fSolarData = fSolarData.readlines()

# Open the file "nodes.txt" in read mode
fNodes = open(r'nodes.txt', "r")
# Read the contents of the "nodes.txt" file and store them in fNodes
fNodes = fNodes.readlines()


# Function to get the ranking chargers
def get_ranking_chargers(lat, lng, derouting_cost, charger_availability,
                         sustainable_charging_level, coordinatesEV, radius):
    previous_center = [0, 0]  # Starting point
    all_ranking_chargers = []

    for node in fNodes:
        ranking_chargers = []
        dataOfNode = node.split(' ')
        center = [dataOfNode[2], dataOfNode[1]]

        if geodesic(previous_center, (lat, lng)).km > 5:
            filtered_coordinatesEV = []
            farthest_point = 0
            greenestCharger = 0
            for coord in coordinatesEV:
                charger_distance = geodesic((lat, lng), [coord[0], coord[1]]).km
                if charger_distance <= radius:
                    filtered_coordinatesEV.append(coord)
                    if charger_distance > farthest_point:
                        farthest_point = charger_distance
                    if coord[4] > greenestCharger:
                        greenestCharger = coord[4]
            farthest_point = farthest_point * 2  # Going and returning back
            previous_center = center
        else:
            print('skip')

        for coord in filtered_coordinatesEV:

            distance = geodesic((lat, lng), [coord[0], coord[1]]).km

            if geodesic((lat, lng), [coord[0], coord[1]]).km <= radius:
                travelDistanceCO2Cost_togo = geodesic((lat, lng), [coord[0], coord[1]]).km
                minsToArrive = travelDistanceCO2Cost_togo
                travelDistanceCO2Cost_backSame = geodesic([coord[0], coord[1]], (lat, lng)).km

                try:
                    travelDistanceCO2Cost_backNext = (
                        geodesic([coord[0], coord[1]], [fNodes[int(dataOfNode[0]) + 1].split(' ')[2],
                                                        fNodes[int(dataOfNode[0]) + 1].split(' ')[1]]).km)
                except:
                    travelDistanceCO2Cost_backNext = farthest_point / 2
                    # The try catch is only to trigger the very last node element

                try:
                    travelDistanceCO2Cost_backPrevious = (
                        geodesic([coord[0], coord[1]], [fNodes[int(dataOfNode[0]) - 1].split(' ')[2],
                                                        fNodes[int(dataOfNode[0]) - 1].split(' ')[1]]).km)
                except:
                    travelDistanceCO2Cost_backPrevious = farthest_point / 2
                    # The try catch is only to trigger the previous node element if not exist

                travelDistanceCO2Cost = (travelDistanceCO2Cost_togo +
                                         min(travelDistanceCO2Cost_backSame, travelDistanceCO2Cost_backNext,
                                             travelDistanceCO2Cost_backPrevious))
                travelDistanceCO2Cost = 100 - ((travelDistanceCO2Cost * 100) / farthest_point)

                chargingIntersection = (coord[3] + coord[4]) / 2
                chargingCO2Cost = (chargingIntersection * 100) / greenestCharger

                # Consider Estimated Time of Arrival (ETA)
                if minsToArrive > 45:
                    chargingCO2Cost = chargingCO2Cost / 4
                elif minsToArrive > 30:
                    chargingCO2Cost = chargingCO2Cost / 3
                elif minsToArrive > 15:
                    chargingCO2Cost = chargingCO2Cost / 2

                calculatedMetric = coord[:]  # Clone the coord list

                availability = (coord[5] + coord[6]) / 2

                ecocharge_score = (((travelDistanceCO2Cost - 2) * derouting_cost)
                                   + (availability * charger_availability)
                                   + (chargingCO2Cost * sustainable_charging_level))

                calculatedMetric.append(ecocharge_score)

                calculatedMetric.append(minsToArrive)
                calculatedMetric.append(availability)
                calculatedMetric.append(chargingCO2Cost)
                calculatedMetric.append((travelDistanceCO2Cost - 2))
                calculatedMetric.append(distance)

                ranking_chargers.append(calculatedMetric)

        ranking_chargers.sort(key=lambda x: x[8], reverse=True)  # Sort by ecocharge score in descending order
        all_ranking_chargers.append(ranking_chargers[0:5])  # 5 nearby chargers

        return all_ranking_chargers


# Define a route for handling POST requests to '/nodes'
@app.route('/nodes', methods=['POST'])
def write_nodes():
    # Extract JSON data from the request
    data = request.get_json()

    if 'nodesList' in data:
        # Extract nodes list from the JSON data
        nodes_list = data['nodesList']

        # Write nodes to a text file
        write_to_file(nodes_list)

        return jsonify({'message': 'Data received and saved to file successfully'})

    return jsonify({'error': 'Invalid request'})


def write_to_file(data):
    # Open the file in write mode
    with open('nodes.txt', 'w') as file:
        # Write each item in the data list to the file
        for item in data:
            file.write(f"{item}\n")


# Define a route for handling POST requests to '/chargers'
@app.route('/chargers', methods=['POST'])
def get_chargers():
    # Retrieve JSON data from the request
    data = request.get_json()

    # Extract the 'selected_value' from the JSON data
    selected_value = data.get('selected_value')

    # Open the JSON file corresponding to the selected value
    f = open(r'' + selected_value + '.json')
    # Load the JSON data from the file
    chargers = json.load(f)
    # Close the file after loading the data
    f.close()

    return jsonify(chargers)


# Define a route for handling POST requests to '/nearby_chargers'
@app.route('/nearby_chargers', methods=['POST'])
def get_nearby_chargers():
    # Retrieve JSON data from the request
    data = request.get_json()

    lat = data['lat']
    lng = data['lng']
    derouting_cost = data['derouting_cost']
    charger_availability = data['charger_availability']
    sustainable_charging_level = data['sustainable_charging_level']
    selected_value = data['selected_value']
    radius = data['radius']

    # Initialize empty list to store coordinates of EV chargers
    coordinatesEV = []
    # Initialize count variable
    count = 0

    # Open the JSON file corresponding to the selected value
    f = open(r'' + selected_value + '.json')
    # Load the JSON data from the file
    chargers = json.load(f)

    for i in chargers:
        chargerKW = i['stations'][0]['outlets'][0]['kilowatts']
        if chargerKW is None:  # Pythonic way of checking for a null value
            chargerKW = 7.2

        energyKWHmin = float(fSolarData[count].split(',')[2])
        energyKWHmax = float(fSolarData[count].split(',')[3])

        coordinatesEV.append([i['latitude'],
                              i['longitude'],
                              chargerKW,
                              energyKWHmin,
                              energyKWHmax,
                              i['availabilityMIN'],
                              i['availabilityMAX'],
                              i['name']])

        count += 1

    # Close the file
    f.close()

    nearby_chargers = (
        get_ranking_chargers(
            lat, lng, derouting_cost, charger_availability, sustainable_charging_level, coordinatesEV, radius
        )
    )

    return jsonify({
        "latitude": lat,
        "longitude": lng,
        "derouting_cost": derouting_cost,
        "charger_availability": charger_availability,
        "sustainable_charging_level": sustainable_charging_level,
        "selected_value": selected_value,
        "radius": radius,
        "nearby_chargers": nearby_chargers
    })


# Check if this script is being executed as the main program
if __name__ == '__main__':
    # Run the Flask application in debug mode
    app.run(debug=True, port=5000, host='ecocharge-demo.cs.ucy.ac.cy',
            ssl_context=('/etc/pki/tls/certs/star_cs_ucy_ac_cy.crt',
                         '/etc/pki/tls/private/private.key'))
