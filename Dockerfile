FROM ubuntu:24.04

# Copy uv directly from its image (correct path this time)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install required system dependencies for building Python packages
RUN apt-get update && \
    apt-get install -y \
    gcc \
    python3-dev \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first
COPY pyproject.toml uv.lock .python-version /app/
WORKDIR /app

# Create virtual environment and install dependencies
ENV PATH="/app/.venv/bin:$PATH"
RUN uv sync --frozen --no-cache

# Copy the project files
COPY . .

# Set default port using ARG and ENV
ARG PORT=8000
ENV PORT=${PORT}

# Default command (can be overridden in compose.yml)
CMD /app/.venv/bin/fastapi run app/main.py --host 0.0.0.0 --port ${PORT}
