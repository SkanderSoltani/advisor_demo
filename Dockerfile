FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir uv
WORKDIR /srv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY scripts ./scripts
COPY data/synthetic ./data/synthetic
COPY data/models ./data/models
RUN uv sync --frozen --no-dev
ENV PATH="/opt/venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "python scripts/seed_demo.py --if-empty && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
