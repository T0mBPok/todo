#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v docker >/dev/null 2>&1 && timeout 5 docker info >/dev/null 2>&1; then
  exec docker compose "$@"
fi
desktop_cli=$(command -v docker.exe || true)
desktop_cli=${desktop_cli:-'/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe'}
if [[ -x "$desktop_cli" ]]; then
  # Preserve the local-only override from demo.sh when using the Windows CLI.
  if [[ -v AI_PROVIDER ]]; then export WSLENV="${WSLENV:+$WSLENV:}AI_PROVIDER/w"; fi
  exec "$desktop_cli" compose --project-directory "$(wslpath -w "$PWD")" -f "$(wslpath -w "$PWD/compose.yaml")" "$@"
fi
echo 'Не удалось подключиться к Docker. Запустите Docker Desktop и проверьте интеграцию WSL.' >&2
exit 1
