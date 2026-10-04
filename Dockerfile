FROM node:24.13.0-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f AS web
WORKDIR /build
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY services services
COPY domain domain
COPY ingest ingest
COPY migrations migrations
COPY alembic.ini ./
COPY fixtures fixtures
COPY config config
COPY ATTRIBUTIONS.md README.md ./
COPY third_party third_party
COPY scripts/start-container.py scripts/start-container.py
COPY scripts/smoke.py scripts/smoke.py
COPY --from=web /build/dist /app/apps/web/dist
RUN useradd --create-home --uid 10001 smartcity && mkdir -p /data/evidence /app/.data && chown -R smartcity:smartcity /data /app/.data
USER smartcity
ENV STORAGE_PATH=/data/evidence SMART_CITY_WEB_DIST=/app/apps/web/dist SMART_CITY_ADAPTER_CACHE=/data/adapters.sqlite
EXPOSE 8000
CMD ["python", "scripts/start-container.py", "api"]
