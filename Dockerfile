# Transition Studio: one container for Railway (and any Docker host). Synthetic data only.
# Runs the FastAPI backend inside the container (127.0.0.1:8000) and the Dash UI on $PORT.
# Railway: connect the repo; railway.json points here. Optional volume at /srv/data.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv
WORKDIR /srv

# dependencies first (cached between deploys)
COPY pyproject.toml uv.lock README.md ./
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev --no-install-project
COPY frontend/pyproject.toml frontend/uv.lock ./frontend/
RUN cd frontend && UV_PROJECT_ENVIRONMENT=/opt/fe-venv uv sync --frozen --no-dev

# backend code + starter data (copied into /srv/data on first start, never over existing files)
COPY app ./app
COPY scripts ./scripts
COPY data/synthetic ./seed-data/synthetic
COPY data/models ./seed-data/models
COPY data/book ./seed-data/book
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev \
    && chmod +x scripts/start_all.sh scripts/start_api.sh

# front-end code
COPY frontend/app.py ./frontend/
COPY frontend/assets ./frontend/assets
COPY frontend/callbacks ./frontend/callbacks
COPY frontend/components ./frontend/components
COPY frontend/pages ./frontend/pages
COPY frontend/services ./frontend/services
COPY frontend/theme ./frontend/theme

EXPOSE 8080
CMD ["scripts/start_all.sh"]
