FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose web port
EXPOSE 8000

# Default command: run the web server
CMD ["gunicorn", "src.web.app:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers", "2", "--max-requests", "10000", "--max-requests-jitter", "5000", "--graceful-timeout", "60", "--timeout", "600", "--keep-alive", "30"]
