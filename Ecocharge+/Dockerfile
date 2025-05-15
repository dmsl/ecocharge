FROM python:3.9-slim

# Set environment variables
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Create virtual environment
RUN python -m venv $VIRTUAL_ENV

# Set workdir
WORKDIR /app

# Install dependencies in the virtual environment
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

# Expose the port your app runs on
EXPOSE 5001

# Run the app using the venv's Python
CMD ["python", "app.py"]