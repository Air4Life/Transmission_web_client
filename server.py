#!/usr/bin/python3
"""Torrent Harbor: dependency-free HTTP UI and restricted Transmission gateway."""
import base64
import hmac
import json
import os
import socket
from auth import Auth
from previews import Previews
from pathlib import Path
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = Path(os.environ.get('HARBOR_CONFIG', '/etc/torrent-harbor/config.json'))
WEB = Path(__file__).resolve().parent / 'web'
ALLOWED = {'torrent-get', 'torrent-start', 'torrent-stop', 'torrent-remove', 'torrent-verify', 'torrent-set', 'session-get', 'session-set', 'session-stats', 'torrent-set-location'}
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
auth = Auth()
previews = Previews()

def engine(method, arguments=None):
    result = rpc.call({'method':method, 'arguments':arguments or {}})
    if result.get('result') != 'success': raise ValueError(result.get('result','Ошибка Transmission'))
    return result.get('arguments', {})

def probe_request(request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(8)
        try:
            client.connect(os.environ.get('HARBOR_PROBE_SOCKET','/var/lib/torrent-harbor/path-check.sock'))
        except OSError as exc:
            raise ValueError('Служба проверки папок недоступна: проверьте torrent-harbor-paths') from exc
        client.sendall(json.dumps(request).encode()+b'\n')
        response = client.makefile('rb').readline(1024*1024)
        result = json.loads(response)
        if result.get('error'): raise ValueError(result['error'])
        return result


def probe_path(path, write=True):
    return probe_request({'path':path,'write':write})

class Handler(BaseHTTPRequestHandler):
    server_version = 'TorrentHarbor/1.2.1'
    def send(self, status, body, content_type='application/json', headers=None):
        if not isinstance(body, bytes): body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key,value in (headers or {}).items(): self.send_header(key,value)
        self.end_headers(); self.wfile.write(body)

    def session(self): return auth.session(self.headers.get('Cookie'))

    def do_GET(self):
        path=self.path.split('?')[0]
        session=self.session()
        if path=='/api/session':
            return self.send(200,{'authenticated':True,'csrf':session['csrf'],'username':self.server.config['username']}) if session else self.send(401,{'error':'Войдите в аккаунт'})
        if path in ('/', '/login'):
            item=('index.html' if session and path=='/' else 'login.html', 'text/html; charset=utf-8')
        else:
            item={'/app.js':('app.js','text/javascript; charset=utf-8'), '/login.js':('login.js','text/javascript; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8')}.get(path)
        if not item: return self.send(404,{'error':'Не найдено'})
        self.send(200,(WEB/item[0]).read_bytes(),item[1])

    def read_json(self):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=8*1024*1024: raise ValueError('Максимальный размер запроса — 8 МиБ')
        data=json.loads(self.rfile.read(length))
        if not isinstance(data,dict): raise ValueError('Некорректный запрос')
        return data

    def cookie(self, token, max_age):
        value=f'harbor_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}'
        if self.server.config.get('secure_cookie',False): value+='; Secure'
        return value

    def do_POST(self):
        self.connection.settimeout(30)
        try:
            if self.headers.get('X-Harbor-Request')!='1': return self.send(403,{'error':'Отсутствует защитный заголовок'})
            if self.path=='/api/login':
                body=self.read_json()
                username,password=body.get('username',''),body.get('password','')
                if not isinstance(username,str) or not isinstance(password,str) or len(username)>256 or len(password)>4096:
                    raise ValueError('Некорректные учётные данные')
                session,status=auth.login(self.server.config,username,password,self.client_address[0])
                if not session:
                    return self.send(status,{'error':'Слишком много попыток. Повторите через 5 минут.' if status==429 else 'Неверный логин или пароль'},headers={'Retry-After':'300'} if status==429 else None)
                return self.send(200,{'csrf':session['csrf']},headers={'Set-Cookie':self.cookie(session['token'],43200)})
            session=self.session()
            if not session: return self.send(401,{'error':'Сессия истекла. Войдите снова.'})
            if not hmac.compare_digest(self.headers.get('X-Harbor-CSRF',''),session['csrf']): return self.send(403,{'error':'Обновите страницу: неверный защитный токен'})
            body=self.read_json()
            owner=session['token']
            if self.path=='/api/logout':
                previews.cancel_owner(owner); auth.logout(self.headers.get('Cookie'))
                return self.send(200,{},headers={'Set-Cookie':self.cookie('',0)})
            if self.path=='/api/directories':
                return self.send(200,probe_request({'operation':'list','path':body.get('path'),'offset':body.get('offset',0),'query':body.get('query',''),'hidden':body.get('hidden',False)}))
            if self.path=='/api/path-check':
                return self.send(200,probe_path(body.get('path'),body.get('write',True)))
            if self.path=='/api/preview':
                if bool(body.get('magnet'))==bool(body.get('metainfo')): raise ValueError('Укажите magnet или .torrent-файл')
                return self.send(200,previews.start(owner,body))
            if self.path=='/api/preview-status': return self.send(200,previews.get(owner,body.get('token')))
            if self.path=='/api/preview-cancel':
                previews.cancel(owner,body.get('token')); return self.send(200,{})
            if self.path=='/api/add':
                preview=previews.get(owner,body.get('token'),include_data=True)
                if preview['state']!='ready': raise ValueError('Дождитесь списка файлов')
                choices=body.get('files')
                if not isinstance(choices,list) or len(choices)!=len(preview['files']): raise ValueError('Неверный список файлов')
                args={'metainfo':preview['metainfo'],'paused':True}
                for i,choice in enumerate(choices):
                    if not isinstance(choice,dict) or type(choice.get('wanted')) is not bool or type(choice.get('priority')) is not int or choice['priority'] not in (-1,0,1): raise ValueError('Неверный выбор файла')
                    key='files-wanted' if choice['wanted'] else 'files-unwanted'
                    args.setdefault(key,[]).append(i)
                    key={-1:'priority-low',0:'priority-normal',1:'priority-high'}[choice['priority']]
                    args.setdefault(key,[]).append(i)
                if not args.get('files-wanted'): raise ValueError('Выберите хотя бы один файл')
                config=engine('session-get')
                directory=body.get('directory') or config['download-dir']
                target=probe_path(directory); args['download-dir']=target['path']
                if config.get('incomplete-dir-enabled'): target=probe_path(config['incomplete-dir'])
                selected=sum(f['length'] for f,c in zip(preview['files'],choices) if c['wanted'])
                if target['free']<selected: raise ValueError('Недостаточно свободного места для выбранных файлов')
                result=engine('torrent-add',args)
                # Never modify or start an existing duplicate.
                if result.get('torrent-added') and not body.get('paused',False):
                    engine('torrent-start',{'ids':[result['torrent-added']['id']]})
                previews.cancel(owner,body.get('token'))
                return self.send(200,result)
            if self.path=='/api/relocate':
                torrent_id=body.get('id'); move=body.get('move')
                if type(torrent_id) is not int or type(move) is not bool: raise ValueError('Неверные параметры переноса')
                target=probe_path(body.get('path'),write=move)
                torrents=engine('torrent-get',{'ids':[torrent_id],'fields':['id','downloadDir','haveValid','haveUnchecked']})['torrents']
                if not torrents: raise ValueError('Торрент уже удалён')
                current=torrents[0]
                if move and target['free'] < current['haveValid']+current['haveUnchecked'] and target['path']!=current['downloadDir'] and target.get('device')!=probe_path(current['downloadDir'],write=False).get('device'):
                    raise ValueError('Недостаточно места для переноса данных')
                engine('torrent-set-location',{'ids':[torrent_id],'location':target['path'],'move':move})
                if not move: engine('torrent-verify',{'ids':[torrent_id]})
                return self.send(200,{'path':target['path'],'message':'Запрос передан Transmission. Дождитесь завершения и проверьте путь и ошибки торрента.' if move else 'Путь изменён. Запущена проверка файлов.'})
            if self.path!='/api/rpc': return self.send(404,{'error':'Не найдено'})
            method=body.get('method'); args=body.get('arguments',{})
            if method not in ALLOWED or not isinstance(args,dict): raise ValueError('Недопустимый метод или параметры')
            if method=='session-set':
                validate_session(args)
                for key in SESSION_PATHS & args.keys(): probe_path(args[key])
                if args.get('incomplete-dir-enabled') and 'incomplete-dir' not in args:
                    probe_path(engine('session-get')['incomplete-dir'])
            if method=='torrent-set-location': raise ValueError('Используйте окно переноса')
            self.send(200,rpc.call(body))
        except (ValueError,TypeError) as exc: self.send(400,{'error':str(exc) or 'Некорректный запрос'})
        except Exception: self.send(502,{'error':'Движок Transmission недоступен. Проверьте службу torrent-harbor-engine.'})

def main():
    config = json.loads(CONFIG.read_text())
    if not config.get('password'): raise SystemExit('Set a nonempty password in ' + str(CONFIG))
    server = ThreadingHTTPServer((config.get('listen', '0.0.0.0'), config.get('port', 8080)), Handler)
    server.config = config
    server.serve_forever()

if __name__ == '__main__': main()
