FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY server.py .

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
