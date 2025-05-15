#!/bin/bash

# Remove existing virtual environment
#rm -rf venv

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Clean pip cache and install requirements
pip cache purge
pip install --no-cache-dir -r requirements.txt

# Set Flask environment variables
export FLASK_RUN_HOST=0.0.0.0
export FLASK_RUN_PORT=5001
export FLASK_ENV=development
export FLASK_APP=app
export FLASK_DEBUG=True

# Run the application
python3 app.py