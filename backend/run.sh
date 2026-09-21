#!/usr/bin/env bash
# 本地起后端。换端口：PORT=9001 ./run.sh
set -e
cd "$(dirname "$0")"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
