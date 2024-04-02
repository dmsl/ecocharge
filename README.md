# EcoCharge

It internally deploys a Continuous k-Nearest Neighbor query, where the distance function is computed using Estimated Components (ECs) (i.e., a query we term CkNN-EC). An EC defines a function that can have a fuzzy value based on some estimates. Examples of ECs are: (i) the derouting cost, which is the time to reach the charger depending on estimated traffic; (ii) the (available clean) power at the charger, which depends on the estimated weather; and (iii) the charger availability,
which depends on the estimated busy timetables that show when the charger is crowded. EcoCharge framework combines these multiple non-conflicting objectives into an
optimization task providing user-defined ranking means through an intuitive spatial application. 

EcoCharge has been developed by researchers and students at the Data Management Systems Laboratory (DMSL), Department of Computer Science at the University of Cyprus.

URL: https://ecocharge.cs.ucy.ac.cy/

Contact: ecocharge@cs.ucy.ac.cy

### Preface
EcoCharge is a novel framework designed to optimize electric vehicle (EV) charging by prioritizing environmentally friendly chargers that maximize renewable energy use and minimize CO2 emissions. It employs a Continuous k-Nearest Neighbor (CkNN) search with Estimated Components to dynamically rank chargers based on factors like travel time, renewable energy availability, and charger occupancy. The EcoCharge algorithm integrates these parameters into an optimization task, presented through a user-friendly spatial application. 

In case you have any publications resulting from the EcoCharge platform, please cite the following paper(s):

- "A Framework for Continuous kNN Ranking of Electric Vehicle Chargers with Estimated Components", Soteris Constantinou, Constantinos Costa, Andreas Konstantinidis, Mohamed F. Mokbel, Demetrios Zeinalipour-Yazti, Proceedings of the 40th IEEE International Conference on Data Engineering (ICDE'24), IEEE Press, 13 pages, Utrecht, Netherlands, Apr 16, 2024 - Apr 19, 2024. (accepted).


We hope that you find our EcoCharge useful for your research and innovation activities.  We would like to have your feedback, comments and remarks and of course any experiences and test results from your own experimental setups. Questions and feedback may be sent to ecocharge@cs.ucy.ac.cy

Enjoy EcoCharge!

The EcoCharge Team 

Copyright (c) 2021, Data Management Systems Lab (DMSL), Department of Computer Science
University of Cyprus.

All rights reserved.

# GNU General Public License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html.

The software is provided “as is”, without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose and noninfringement. in no event shall the authors or copyright holders be liable for any claim, damages or other liability, whether in an action of contract, tort or otherwise, arising from, out of or in connection with the software or the use or other dealings in the software.


## Components 

Short description of the contents included in this release.

### Python
The Source code for the EcoCharge Information Server (EIS) library. Lead Developer: Soteris Constantinou. 

### Web
The Source code for the EcoCharge Client web application using Leaflet, Mapbox, HTML, and JavaScript. Lead Developer: Soteris Constantinou. 

### Datasets
-  A synthetic trajectory dataset based on Oldenburg’s road network, generated with Brinkhoff spatio-temporal generator (https://www.cs.utah.edu/~lifeifei/SpatialDataset.htm).
-  Real road network trajectories in California, collected by Boston University’s computer science department (https://www.cs.utah.edu/~lifeifei/SpatialDataset.htm).
-  Geolife, contains real GPS trajectories from China, USA, and Europe, collected by Microsoft Research Asia (https://www.microsoft.com/en-us/download/details.aspx?id=52367).
-  T-drive, contains real GPS taxi trajectories, collected by Microsoft Research Asia (https://www.microsoft.com/en-us/research/publication/t-drive-trajectory-data-sample/).
-  EV charging stations and their production information based on weather forecast were retrieved by PlugShare (https://www.plugshare.com/) and “California Distributed Generation
Statistics (CDGS)” (https://www.californiadgstats.ca.gov/). 


Project Leader: Demetris Zeinalipour
