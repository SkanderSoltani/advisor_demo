# Transition Studio API (FastAPI). Synthetic data only.
# Railway: service "api" (root directory /, config railway.json). Locally: docker compose up.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir uv
WORKDIR /srv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY scripts ./scripts
# starter data: copied into /srv/data (the volume) on first start, never over existing files
COPY data/synthetic ./seed-data/synthetic
COPY data/models ./seed-data/models
COPY data/book ./seed-data/book
RUN uv sync --frozen --no-dev && chmod +x scripts/start_api.sh
ENV PATH="/opt/venv/bin:$PATH"
EXPOSE 8000
CMD ["scripts/start_api.sh"]
