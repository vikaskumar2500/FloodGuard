#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."

(
  cd backend
  uv run --locked ruff format --check .
  uv run --locked ruff check .
  uv run --locked pytest -q -m 'not integration'
)
(
  cd frontend
  npm run format:check
  npm run lint
  npm run type-check
  npm test
)
