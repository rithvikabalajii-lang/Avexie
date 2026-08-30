#!/usr/bin/env bash
set -euo pipefail

project="${COMPOSE_PROJECT_NAME:-avexie-by-edith}"

echo "[1/5] Runtime startup uses local images only"
docker compose config --format json | python3 -c \
  "import json,sys; services=json.load(sys.stdin)['services']; invalid={name:item.get('pull_policy') for name,item in services.items() if item.get('pull_policy') != 'never'}; assert not invalid, invalid; print('  all service pull policies: never')"

echo "[2/5] Docker isolation"
for network in sovereign_internal judge0_internal; do
  value="$(docker network inspect "${project}_${network}" --format '{{.Internal}}')"
  test "$value" = "true"
  echo "  ${network}: internal=${value}"
done
masquerade="$(docker network inspect "${project}_host_ingress" --format '{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}')"
test "$masquerade" = "false"
echo "  host_ingress: ip_masquerade=${masquerade}"

echo "[3/5] Local Ollama is reachable from the application"
docker compose exec -T avexie python -c \
  "import urllib.request; print(urllib.request.urlopen('http://ollama:11434/api/tags', timeout=5).status)"

echo "[4/5] Public network access is blocked"
if docker compose exec -T avexie python -c \
  "import urllib.request; urllib.request.urlopen('https://example.com', timeout=4)" 2>/dev/null; then
  echo "ERROR: public egress unexpectedly succeeded" >&2
  exit 1
else
  echo "  blocked as expected"
fi

echo "[5/5] Runtime policy"
docker compose exec -T avexie python -c \
  "import os; assert os.getenv('ENABLE_OPENAI_API') == 'false'; assert os.getenv('VECTOR_DB') == 'chroma'; print('  cloud providers disabled; Chroma enabled')"

echo "PASS: application services have no external route. UI network monitor should read 0 external calls."
