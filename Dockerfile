FROM python:3.13-slim

WORKDIR /app

# System deps for git worktrees
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY config.yaml .
COPY projects/ projects/

# Data directory for SQLite + run outputs
RUN mkdir -p data /tmp/agents

EXPOSE 8080

CMD ["uv", "run", "agents"]
