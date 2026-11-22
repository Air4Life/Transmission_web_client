#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
./build-deb.sh
docker --host=unix:///var/run/docker.sock build -f tests/ubuntu/Dockerfile -t torrent-harbor-test:24.04 .
docker --host=unix:///var/run/docker.sock run --rm --mount "type=bind,src=$(pwd),dst=/src,readonly" torrent-harbor-test:24.04 python3 tests/ubuntu/integration.py
