#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export AI_PROVIDER=ollama
echo 'Waiting for Docker Desktop...'
ready=0
for i in $(seq 1 90); do
  if bash scripts/compose.sh version >/dev/null 2>&1 && bash scripts/compose.sh ps >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
if [ "$ready" != 1 ]; then echo 'Docker did not start. Open Docker Desktop and check WSL integration.'; exit 1; fi
if ! systemctl is-active --quiet ollama; then
  sudo -n systemctl start ollama || { echo 'Start Ollama in WSL: sudo systemctl start ollama'; exit 1; }
fi
echo 'Starting database, voice recognition, backend and frontend...'
bash scripts/compose.sh up -d --no-build --pull never --wait --wait-timeout 180 db speech backend frontend
echo 'Checking local AI and warming the model (first start can take a minute)...'
bash scripts/compose.sh exec -T backend python - <<'PY'
import httpx
from app.core import config
if config.AI_PROVIDER!='ollama':raise SystemExit('Expected local Ollama; cloud provider is not enabled by this launcher.')
health=httpx.get('http://localhost:8000/api/health',timeout=15).json()
if not health.get('ai_configured'):raise SystemExit('Ollama model missing. Check your local Ollama configuration.')
voice=httpx.get('http://speech:8001/health',timeout=15).json()
if not voice.get('ready'):raise SystemExit('Speech recognition is not ready.')
response=httpx.post(config.OLLAMA_BASE_URL+'/api/chat',timeout=180,json={'model':config.OLLAMA_MODEL,'stream':False,'think':False,'keep_alive':'1h','messages':[{'role':'user','content':'Ответь одним словом: готов'}],'options':{'num_predict':16,'temperature':0}})
response.raise_for_status()
if not response.json().get('message',{}).get('content'):raise SystemExit('Local AI returned an empty answer.')
print('Ready: local Ollama ('+config.OLLAMA_MODEL+'), GigaAM, PostgreSQL and calendar.')
PY
echo 'Open http://localhost:5173/ — allow microphone access in the browser.'
