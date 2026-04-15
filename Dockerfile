FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY src/ ./src/
COPY tests/ ./tests/

# Create data directory
RUN mkdir -p /app/data

# Environment variables
ENV PYTHONPATH=/app
ENV DATA_DIR=/app/data
ENV ENVIRONMENT=development

# Expose default port
EXPOSE 8000

# Quick start entrypoint
CMD ["python", "-m", "riks_context_engine.cli.main", "--help"]