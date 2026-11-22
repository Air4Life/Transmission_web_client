#!/usr/bin/python3
"""Torrent Harbor: dependency-free HTTP UI and restricted Transmission gateway."""
import base64
import hmac
import json
import os
from pathlib import Path
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = Path(os.environ.get('HARBOR_CONFIG', '/etc/torrent-harbor/config.json'))
WEB = Path(__file__).resolve().parent / 'web'
ALLOWED = {'torrent-get', 'torrent-add', 'torrent-start', 'torrent-stop', 'torrent-remove', 'torrent-verify', 'torrent-set', 'session-get', 'session-set', 'session-stats', 'torrent-set-location'}
SESSION_BOOLS = {'speed-limit-down-enabled', 'speed-limit-up-enabled', 'alt-speed-enabled',
                 'incomplete-dir-enabled', 'start-added-torrents', 'rename-partial-files',
                 'download-queue-enabled', 'seed-queue-enabled', 'seedRatioLimited',
                 'dht-enabled', 'pex-enabled', 'lpd-enabled', 'port-forwarding-enabled'}
SESSION_INTS = {'speed-limit-down': (0, 10000000), 'speed-limit-up': (0, 10000000),
                'download-queue-size': (1, 10000), 'seed-queue-size': (1, 10000),
                'peer-port': (1, 65535), 'peer-limit-global': (1, 100000),
                'peer-limit-per-torrent': (1, 100000)}
SESSION_PATHS = {'download-dir', 'incomplete-dir'}
SESSION_KEYS = SESSION_BOOLS | SESSION_INTS.keys() | SESSION_PATHS | {'seedRatioLimit', 'encryption'}

def validate_session(args):
    if not set(args) <= SESSION_KEYS:
        raise ValueError('Недопустимая настройка')
    for key, value in args.items():
        if key in SESSION_BOOLS and type(value) is not bool:
            raise ValueError('Ожидается переключатель: ' + key)
        if key in SESSION_INTS:
            low, high = SESSION_INTS[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Недопустимое число: ' + key)
        if key in SESSION_PATHS and (not isinstance(value, str) or not value.startswith('/') or '\x00' in value):
            raise ValueError('Укажите абсолютный путь: ' + key)
        if key == 'seedRatioLimit' and (type(value) not in (int, float) or not 0 <= value <= 100000):
            raise ValueError('Недопустимый рейтинг отдачи')
        if key == 'encryption' and value not in ('required', 'preferred', 'tolerated'):
            raise ValueError('Недопустимый режим шифрования')


class RPC:
    token = ''
    def call(self, payload):
        for _ in range(2):
            req = urllib.request.Request('http://127.0.0.1:9092/transmission/rpc', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'X-Transmission-Session-Id': self.token})
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code != 409:
                    raise
                self.token = exc.headers.get('X-Transmission-Session-Id', '')
        raise RuntimeError('Transmission session handshake failed')

rpc = RPC()

class Handler(BaseHTTPRequestHandler):
    server_version = 'TorrentHarbor/1.1'
    def send(self, status, body, content_type='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)
    def authenticated(self):
        expected = 'Basic ' + base64.b64encode((self.server.config['username'] + ':' + self.server.config['password']).encode()).decode()
        if hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            return True
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Torrent Harbor", charset="UTF-8"')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return False
    def do_GET(self):
        if not self.authenticated(): return
        paths = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        item = paths.get(self.path.split('?')[0])
        if not item: return self.send(404, {'error': 'Не найдено'})
        self.send(200, (WEB / item[0]).read_bytes(), item[1])
    def do_POST(self):
        if not self.authenticated(): return
        if self.path != '/api/rpc': return self.send(404, {'error': 'Не найдено'})
        # Custom header + no CORS support blocks browser cross-origin form requests.
        if self.headers.get('X-Harbor-Request') != '1': return self.send(403, {'error': 'Отсутствует защитный заголовок'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8 * 1024 * 1024: return self.send(413, {'error': 'Максимум 8 МиБ'})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or payload.get('method') not in ALLOWED: return self.send(400, {'error': 'Недопустимый метод'})
            args = payload.get('arguments', {})
            if not isinstance(args, dict): return self.send(400, {'error': 'Некорректные параметры'})
            if payload['method'] == 'session-set': validate_session(args)
            if payload['method'] == 'torrent-add':
                source = args.get('filename', '')
                if source and not source.startswith('magnet:?'): return self.send(400, {'error': 'Используйте magnet или загрузите .torrent'})
                if not source and not args.get('metainfo'): return self.send(400, {'error': 'Нет торрента'})
            self.send(200, rpc.call(payload))
        except (ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc) or 'Некорректный запрос'})
        except Exception:
            self.send(502, {'error': 'Движок Transmission недоступен. Проверьте службу torrent-harbor-engine.'})

def main():
    config = json.loads(CONFIG.read_text())
    if not config.get('password'): raise SystemExit('Set a nonempty password in ' + str(CONFIG))
    server = ThreadingHTTPServer((config.get('listen', '0.0.0.0'), config.get('port', 8080)), Handler)
    server.config = config
    server.serve_forever()

if __name__ == '__main__': main()
