#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v docker >/dev/null 2>&1; then
  exec docker compose "$@"
elif command -v docker.exe >/dev/null 2>&1; then
  # Docker Desktop can build WSL sources through their Windows UNC path.
  exec docker.exe compose --project-directory "$(wslpath -w "$PWD")" -f "$(wslpath -w "$PWD/compose.yaml")" "$@"
else
  echo 'Docker не найден. Установите Docker Desktop и включите WSL integration.' >&2
  exit 1
fi
