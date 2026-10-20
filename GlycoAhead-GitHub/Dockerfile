FROM node:24-bookworm-slim AS frontend
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GLYCOAHEAD_HOME=/app OMP_NUM_THREADS=4
WORKDIR /app
COPY requirements.lock.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/ backend/
COPY migrations/ migrations/
COPY alembic.ini ./
RUN pip install --no-deps . && useradd --create-home appuser && mkdir -p data artifacts logs && chown -R appuser:appuser /app
COPY --from=frontend /ui/dist frontend/dist/
USER appuser
EXPOSE 8000
CMD ["uvicorn", "glycoahead.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
