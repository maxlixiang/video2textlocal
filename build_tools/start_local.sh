#!/usr/bin/env bash
# Invoke in WSL after Docker Desktop is running; preserves existing project volumes.
set -euo pipefail
cd "$(dirname "$0")/.."
export BOT_ENV_FILE="${BOT_ENV_FILE:-.env}"
export WINDOWS_ADAPTER_ENABLED="${WINDOWS_ADAPTER_ENABLED:-1}"
export ALLOW_FAKE_IP_DNS="${ALLOW_FAKE_IP_DNS:-1}"
test -s "$BOT_ENV_FILE" || { echo 'startup_missing_bot_configuration'; exit 1; }
docker info >/dev/null 2>&1 || { echo 'startup_docker_not_ready'; exit 1; }
python3 build_tools/prepare_runtime.py --runtime-directory "${ADAPTER_RUNTIME_DIR:-.adapter-runtime}"
docker compose -p v2t-live-fixes -f compose.yaml -f compose.adapter.yaml -f compose.final.yaml -f compose.egress.yaml --profile bot up -d --no-build --wait --wait-timeout 180
