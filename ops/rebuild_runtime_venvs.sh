#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
PROJECTS=(
  "alphaforge-python"
  "alphaforge-marl"
  "alphaforge-execution"
)

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Required interpreter '$PYTHON_BIN' is not available." >&2
  exit 1
fi

for project in "${PROJECTS[@]}"; do
  project_dir="$ROOT_DIR/$project"
  venv_dir="$project_dir/.venv"
  requirements_file="$project_dir/requirements.txt"

  echo "Rebuilding $project with $PYTHON_BIN"
  rm -rf "$venv_dir"
  "$PYTHON_BIN" -m venv "$venv_dir"
  "$venv_dir/bin/python" -m pip install --upgrade pip
  "$venv_dir/bin/python" -m pip install -r "$requirements_file"
done
