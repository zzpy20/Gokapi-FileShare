#!/bin/sh
# Only needed for docker-compose.china.yml — downloads the linux-amd64 release
# binary so it can be baked into a local image instead of pulling f0rc3/gokapi
# from Docker Hub (blocked by mainland China's registry mirrors).
#
# Run this on a machine with normal internet access, NOT the target server —
# GitHub's release-asset CDN is unreachable from mainland China directly.
# Then scp the resulting bin/ directory to the server before `docker compose
# -f docker-compose.china.yml up -d --build`.

set -e
VERSION="${1:-2.2.4}"
URL="https://github.com/Forceu/Gokapi/releases/download/v${VERSION}/gokapi-${VERSION}_linux-amd64.zip"

echo "Downloading Gokapi v${VERSION} for linux-amd64..."
curl -sL -o gokapi.zip "$URL"
python3 -c "import zipfile; zipfile.ZipFile('gokapi.zip').extractall('bin')"
chmod +x bin/gokapi
rm gokapi.zip
echo "Done: ./bin/gokapi"
