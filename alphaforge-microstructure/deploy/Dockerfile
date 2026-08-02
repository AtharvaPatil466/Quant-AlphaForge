# Containerized Phase 0 collector — for VPS deployment (see DEPLOY.md).
# Build from the alphaforge-microstructure/ directory:
#   docker compose -f deploy/docker-compose.yml up -d --build
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY collector/ collector/

# Same invocation as the launchd agent; data/ and logs/ are volume mounts.
CMD ["python", "-m", "collector.run_collector", "--symbol", "BTCUSDT", "--out", "data/"]
