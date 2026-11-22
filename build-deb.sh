#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p dist
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
install -d "$stage/DEBIAN" "$stage/usr/lib/torrent-harbor/web" "$stage/usr/lib/systemd/system" "$stage/usr/share/doc/torrent-harbor"
install -m 0644 server.py "$stage/usr/lib/torrent-harbor/server.py"
install -m 0644 web/* "$stage/usr/lib/torrent-harbor/web/"
install -m 0644 packaging/*.service "$stage/usr/lib/systemd/system/"
install -m 0644 README.md "$stage/usr/share/doc/torrent-harbor/README.md"
install -m 0644 LICENSE "$stage/usr/share/doc/torrent-harbor/copyright"
for script in postinst prerm postrm; do install -m 0755 "packaging/$script" "$stage/DEBIAN/$script"; done
cat > "$stage/DEBIAN/control" <<EOF
Package: torrent-harbor
Version: 1.1.0
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), transmission-daemon (>= 3.00), adduser, systemd
Maintainer: Torrent Harbor Maintainers <maintainers@torrent-harbor.invalid>
Installed-Size: $(du -sk "$stage/usr" | cut -f1)
Description: Modern themed HTTP interface for the Transmission BitTorrent engine
 Russian responsive web UI, magnet and torrent uploads, speed limits,
 authentication and dedicated systemd services for Ubuntu 24.04.
EOF
chmod 0755 "$stage"
chmod -R go-w "$stage"
dpkg-deb --root-owner-group --build "$stage" dist/torrent-harbor_1.1.0_all.deb
