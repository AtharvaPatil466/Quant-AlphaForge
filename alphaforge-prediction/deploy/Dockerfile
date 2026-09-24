# Containerized Phase 2 forward paper trader — for VPS deployment (see DEPLOY.md).
#
# Build context is the REPO ROOT, not this sub-project: requirements.txt installs
# the canonical gauntlet package editable from the sibling ../alphaforge-gauntlet,
# so both trees must be inside the context. The image mirrors the repo layout
# under /srv so that relative path resolves unchanged.
#
#   docker compose -f deploy/docker-compose.yml build
FROM python:3.13-slim

# Sibling package first — requirements.txt references it as ../alphaforge-gauntlet.
COPY alphaforge-gauntlet/ /srv/alphaforge-gauntlet/

WORKDIR /srv/alphaforge-prediction
COPY alphaforge-prediction/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source only. data/ is a volume mount — never bake the journal into the image.
COPY alphaforge-prediction/ingest/     ingest/
COPY alphaforge-prediction/signals/    signals/
COPY alphaforge-prediction/validation/ validation/
COPY alphaforge-prediction/research/   research/
COPY alphaforge-prediction/scripts/    scripts/

# The wrapper defaults to the macOS framework interpreter; here it is plain python3.
ENV PAPER_TRADER_PYTHON=python3

# Batch job, not a daemon: invoked per-run via `docker compose run --rm`.
ENTRYPOINT ["scripts/run_paper_trader.sh"]
