#!/usr/bin/python3
"""Run with the engine UID and filesystem restrictions, outside web's read-only sandbox."""
import json
import os
import shutil
import socketserver
import tempfile
from pathlib import Path

SOCKET = os.environ.get('HARBOR_PROBE_SOCKET', '/var/lib/torrent-harbor/path-check.sock')

def check_path(path, write=True):
    if not isinstance(path, str) or not path.startswith('/') or '\x00' in path or len(path)>4096:
        raise ValueError('Укажите абсолютный путь к папке')
    directory = Path(path).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError('Это не папка: ' + path)
    if not os.access(directory, os.R_OK | os.X_OK):
        raise PermissionError('Нет доступа к папке')
    if write:
        # Exercise real filesystem permissions/ACLs/read-only mounts, and always remove the probe.
        with tempfile.TemporaryFile(prefix='.harbor-check-', dir=directory) as file:
            file.write(b'harbor'); file.flush(); os.fsync(file.fileno())
    usage = shutil.disk_usage(directory)
    return {'path':str(directory), 'writable':bool(write), 'free':usage.free, 'total':usage.total, 'device':directory.stat().st_dev}

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(5)
        try:
            request = json.loads(self.rfile.readline(8193))
            result = check_path(request.get('path'), request.get('write', True))
        except FileNotFoundError:
            result = {'error':'Папка не существует. Создайте её и дайте пользователю torrent-harbor доступ.'}
        except PermissionError:
            result = {'error':'Пользователь torrent-harbor не может читать или записывать в эту папку. Проверьте права и доступ к родительским каталогам.'}
        except (OSError, ValueError, TypeError) as exc:
            result = {'error':str(exc)}
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode() + b'\n')

def main():
    Path(SOCKET).unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o600)
        server.serve_forever()

if __name__ == '__main__': main()
