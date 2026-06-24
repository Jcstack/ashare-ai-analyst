FROM python:3.11-slim

WORKDIR /app

# Proxy for build-time network access (PyPI, apt)
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY=localhost,127.0.0.1

# Install system dependencies + set timezone
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc tzdata \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --timeout 120 --retries 10 --resume-retries 20 -r requirements.txt

# Copy application code
COPY . .

# Expose web port
EXPOSE 8000

# Default command: run the web server
CMD ["gunicorn", "src.web.app:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers", "4", "--preload", "--max-requests", "5000", "--max-requests-jitter", "2000", "--graceful-timeout", "60", "--timeout", "600", "--keep-alive", "30"]
