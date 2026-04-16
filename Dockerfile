FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./

# Copy application code BEFORE installing the package
COPY src/ ./src/

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Copy tests
COPY tests/ ./tests/

# Create data directory
RUN mkdir -p /app/data

# Environment variables
ENV PYTHONPATH=/app
ENV DATA_DIR=/app/data
ENV ENVIRONMENT=development
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434

# Create non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# Switch to non-root user
USER appuser

# Expose default port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start uvicorn FastAPI server
CMD ["uvicorn", "riks_context_engine.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
