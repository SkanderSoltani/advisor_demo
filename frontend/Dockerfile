FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir uv
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app.py ./
COPY assets ./assets
COPY callbacks ./callbacks
COPY components ./components
COPY pages ./pages
COPY services ./services
COPY theme ./theme
ENV PATH="/opt/venv/bin:$PATH" USE_MOCKS=false API_BASE_URL=http://api:8000/api/v1
EXPOSE 8050
# One worker: in mock mode the in-process mock backend keeps its state per process.
CMD ["gunicorn", "app:server", "--bind", "0.0.0.0:8050", "--workers", "1", "--threads", "8", "--timeout", "120"]
