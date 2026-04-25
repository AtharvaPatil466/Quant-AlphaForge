#!/bin/sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR/alphaforge-python"

python3 sync_market_data.py --start-date 2010-01-01 --end-date "$(date +%F)"
