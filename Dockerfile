FROM python:3.11-slim

# Install Nginx and other utilities
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for generated configs
RUN mkdir -p generated_configs

# Expose ports
# 80 for Nginx (Proxy)
# 8181 for Flask (UI)
EXPOSE 80 8181

# Start Nginx (background) and Flask (foreground)
CMD ["sh", "-c", "nginx && python app.py"]
