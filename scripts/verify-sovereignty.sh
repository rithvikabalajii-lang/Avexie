#!/usr/bin/env bash
set -euo pipefail

project="${COMPOSE_PROJECT_NAME:-avexie-by-edith}"

echo "[1/4] Docker isolation"
for network in sovereign_internal judge0_internal; do
  value="$(docker network inspect "${project}_${network}" --format '{{.Internal}}')"
  test "$value" = "true"
  echo "  ${network}: internal=${value}"
done
masquerade="$(docker network inspect "${project}_host_ingress" --format '{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}')"
test "$masquerade" = "false"
echo "  host_ingress: ip_masquerade=${masquerade}"

echo "[2/4] Local Ollama is reachable from the application"
docker compose exec -T avexie python -c \
  "import urllib.request; print(urllib.request.urlopen('http://ollama:11434/api/tags', timeout=5).status)"

echo "[3/4] Public network access is blocked"
if docker compose exec -T avexie python -c \
  "import urllib.request; urllib.request.urlopen('https://example.com', timeout=4)" 2>/dev/null; then
  echo "ERROR: public egress unexpectedly succeeded" >&2
  exit 1
else
  echo "  blocked as expected"
fi

echo "[4/4] Runtime policy"
docker compose exec -T avexie python -c \
  "import os; assert os.getenv('ENABLE_OPENAI_API') == 'false'; assert os.getenv('VECTOR_DB') == 'chroma'; print('  cloud providers disabled; Chroma enabled')"

echo "PASS: application services have no external route. UI network monitor should read 0 external calls."
