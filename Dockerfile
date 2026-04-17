# ===== Base ===== #
FROM python:3.12-slim

LABEL maintainer="vopsiton <vahit@opsiton.com>"
LABEL description="Rik's Context Engine - AI memory and context management"

WORKDIR /app

# ===== Dependencies ===== #
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy app source (needed for editable install)
COPY src/ ./src/
COPY tests/ ./tests/

# Copy and install
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# ===== Data directory ===== #
RUN mkdir -p /app/data && chmod 755 /app/data

ENV PYTHONPATH=/app/src
ENV DATA_DIR=/app/data

# Default port
EXPOSE 8000

# Default command - interactive shell
CMD ["python", "-c", "print('Rik\\'s Context Engine ready!')"]