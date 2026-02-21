FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Self-hosted mem0 defaults (can be overridden at runtime)
ENV MEM0_ENABLED=false
ENV MEM0_API_URL=http://host.docker.internal:8888
ENV QDRANT_HOST=host.docker.internal
ENV QDRANT_PORT=6333

# Expose port (adjust as needed)
EXPOSE 8000

# Default command
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
