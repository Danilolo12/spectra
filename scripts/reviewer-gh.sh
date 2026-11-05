#!/usr/bin/env bash
# Corre gh autenticado como spectra-reviewer[bot].
# Uso: ./scripts/reviewer-gh.sh pr review 12 --approve --body "..."
set -euo pipefail

CRED_DIR="${HOME}/.config/spectra/github-app"
APP_ID_FILE="${CRED_DIR}/app-id"
KEY_FILE="${CRED_DIR}/private-key.pem"
INSTALL_FILE="${CRED_DIR}/installation-id"

if [[ ! -f "${APP_ID_FILE}" || ! -f "${KEY_FILE}" ]]; then
  echo "Faltan credenciales. Corre: python3 scripts/setup-reviewer-app.py" >&2
  exit 1
fi

APP_ID="$(tr -d '[:space:]' < "${APP_ID_FILE}")"
NOW="$(date +%s)"
IAT=$((NOW - 10))
EXP=$((NOW + 540))

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

HEADER="$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)"
PAYLOAD="$(printf '{"iat":%s,"exp":%s,"iss":"%s"}' "${IAT}" "${EXP}" "${APP_ID}" | b64url)"
SIGNATURE="$(printf '%s' "${HEADER}.${PAYLOAD}" | openssl dgst -sha256 -sign "${KEY_FILE}" | b64url)"
JWT="${HEADER}.${PAYLOAD}.${SIGNATURE}"

if [[ ! -f "${INSTALL_FILE}" ]]; then
  INSTALL_ID="$(curl -fsS -H "Authorization: Bearer ${JWT}" -H "Accept: application/vnd.github+json" \
    https://api.github.com/app/installations | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data[0]["id"] if data else "")')"
  if [[ -z "${INSTALL_ID}" ]]; then
    echo "La app no está instalada en ningún repo. Ábrela en GitHub y elige spectra." >&2
    exit 1
  fi
  printf '%s\n' "${INSTALL_ID}" > "${INSTALL_FILE}"
  chmod 600 "${INSTALL_FILE}"
fi

INSTALL_ID="$(tr -d '[:space:]' < "${INSTALL_FILE}")"
TOKEN="$(curl -fsS -X POST -H "Authorization: Bearer ${JWT}" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/app/installations/${INSTALL_ID}/access_tokens" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')"

export GH_TOKEN="${TOKEN}"
export GH_REPO="${GH_REPO:-Danilolo12/spectra}"
gh "$@"
