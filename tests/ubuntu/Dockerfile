FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-libtorrent transmission-daemon systemd adduser ca-certificates curl && rm -rf /var/lib/apt/lists/*
WORKDIR /src
