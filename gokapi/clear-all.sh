#!/bin/bash
# Usage: bash gokapi/clear-all.sh <sg|sz> [-y]
#   Deletes EVERY file stored in that box's Gokapi (all share links stop working).
#   Lists the files and asks for confirmation first; -y skips the question.
#
# Run from your Mac. Reads the box's URL and API key from the gitignored .env
# at the repo root: SG_GOKAPI_URL + SG_GOKAPI_API_KEY (or the SZ_ pair).
# Create the key in Gokapi's admin page (API Keys menu); it needs permission
# to view and delete files.
#
# Requires: curl, jq.
set -e

BOX="${1:?Usage: bash gokapi/clear-all.sh <sg|sz> [-y]}"
ASSUME_YES="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

if [ ! -f "${ENV_FILE}" ]; then
    echo "Error: ${ENV_FILE} not found."
    exit 1
fi
set -a; source "${ENV_FILE}"; set +a

case "${BOX}" in
    sg) URL="${SG_GOKAPI_URL}"; KEY="${SG_GOKAPI_API_KEY}"; PREFIX="SG" ;;
    sz) URL="${SZ_GOKAPI_URL}"; KEY="${SZ_GOKAPI_API_KEY}"; PREFIX="SZ" ;;
    *)  echo "Error: box must be 'sg' or 'sz'"; exit 1 ;;
esac

if [ -z "${URL}" ] || [ -z "${KEY}" ]; then
    echo "Error: ${PREFIX}_GOKAPI_URL / ${PREFIX}_GOKAPI_API_KEY must be set in .env"
    exit 1
fi

# The saved URL is the admin page (.../admin); the API lives at .../api.
API="${URL%/}"; API="${API%/admin}/api"

list_files() {
    local out
    out=$(curl -sS -m 30 -w '\n%{http_code}' -H "apikey: ${KEY}" "${API}/files/list")
    local code="${out##*$'\n'}" body="${out%$'\n'*}"
    if [ "${code}" != "200" ]; then
        echo "Error: listing files failed (HTTP ${code}): ${body}" >&2
        [ "${code}" = "401" ] && echo "       Check ${PREFIX}_GOKAPI_API_KEY and that the key may view files." >&2
        return 1
    fi
    # An empty Gokapi answers "null" rather than "[]".
    echo "${body}" | jq -c '. // []'
}

FILES=$(list_files)
COUNT=$(echo "${FILES}" | jq 'length')

if [ "${COUNT}" = "0" ]; then
    echo "==> ${BOX}: no files stored, nothing to do."
    exit 0
fi

echo "==> ${BOX}: ${COUNT} file(s) stored at ${API%/api}"
echo "${FILES}" | jq -r '.[] | "    \(.Id)  \(.Size)  \(.Name)"'

if [ "${ASSUME_YES}" != "-y" ]; then
    read -r -p "Delete all ${COUNT}? This cannot be undone. Type 'yes': " ANSWER
    if [ "${ANSWER}" != "yes" ]; then
        echo "Aborted, nothing deleted."
        exit 1
    fi
fi

FAILED=0
for id in $(echo "${FILES}" | jq -r '.[].Id'); do
    code=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' -X DELETE \
        -H "apikey: ${KEY}" -H "id: ${id}" -H "delay: 0" "${API}/files/delete")
    if [ "${code}" = "200" ]; then
        echo "    deleted ${id}"
    else
        echo "    FAILED  ${id} (HTTP ${code})"
        FAILED=1
    fi
done

LEFT=$(list_files | jq 'length')
echo ""
echo "==> Done. Files still stored: ${LEFT}"
[ "${FAILED}" = "0" ] && [ "${LEFT}" = "0" ]
