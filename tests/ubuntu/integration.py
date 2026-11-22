#!/usr/bin/python3
"""Run as root inside disposable Ubuntu 24.04, or a dedicated CI Ubuntu VM."""
import base64
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
import libtorrent as lt
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path('/src') if Path('/src/server.py').exists() else Path(__file__).resolve().parents[2]
SYSTEMD=Path('/run/systemd/system').is_dir()
processes={}

def command(*args): subprocess.run(args,check=True)
def wait(test,timeout=25):
    until=time.monotonic()+timeout;error=None
    while time.monotonic()<until:
        try:
            result=test()
            if result:return result
        except Exception as exc:error=exc
        time.sleep(.2)
    raise AssertionError(f'Timeout: {error}')
def start_services():
    if SYSTEMD:
        command('systemctl','restart','torrent-harbor-engine','torrent-harbor-paths','torrent-harbor')
    else:
        start('engine',['/usr/bin/transmission-daemon','--foreground','--config-dir','/var/lib/torrent-harbor/engine'])
        start('paths',['/usr/bin/python3','/usr/lib/torrent-harbor/path_probe.py'])
        start('web',['/usr/bin/python3','/usr/lib/torrent-harbor/server.py'])
def start(name,args):
    user=pwd.getpwnam('torrent-harbor')
    def demote():os.setgid(user.pw_gid);os.setuid(user.pw_uid)
    log=open('/tmp/harbor-'+name+'.log','w')
    processes[name]=subprocess.Popen(args,preexec_fn=demote,stdout=log,stderr=log)
def stop_services():
    if SYSTEMD:command('systemctl','stop','torrent-harbor','torrent-harbor-paths','torrent-harbor-engine')
    else:
        for process in processes.values():process.terminate()
        for process in processes.values():process.wait(timeout=20)
        processes.clear()
def owned(path):
    path.mkdir(parents=True,exist_ok=True)
    user=pwd.getpwnam('torrent-harbor');os.chown(path,user.pw_uid,user.pw_gid);os.chmod(path,0o750)
    return str(path)
jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar));csrf=''
def api(path,body=None):
    headers={'Content-Type':'application/json','X-Harbor-Request':'1','X-Harbor-CSRF':csrf}
    request=urllib.request.Request('http://127.0.0.1:8080'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    try:
        with client.open(request,timeout=35) as response:return json.load(response)
    except urllib.error.HTTPError as exc:raise AssertionError(f'{exc.code}: {exc.read().decode()}') from exc

def rpc(method,args=None):
    data=api('/api/rpc',{'method':method,'arguments':args or {}});assert data['result']=='success',data;return data['arguments']
def login():
    global csrf
    config=json.loads(Path('/etc/torrent-harbor/config.json').read_text())
    csrf=api('/api/login',{'username':config['username'],'password':config['password']})['csrf']
def preview(request):
    token=api('/api/preview',request)['token']
    def ready():
        data=api('/api/preview-status',{'token':token})
        assert data['state']!='error',data
        return data if data['state']=='ready' else None
    return wait(ready,100)

def main():
    # Install old package, then upgrade: credentials and engine settings must survive.
    command('dpkg','-i',str(ROOT/'dist/torrent-harbor_1.1.0_all.deb'))
    before=Path('/etc/torrent-harbor/config.json').read_bytes()
    if SYSTEMD:command('systemctl','stop','torrent-harbor','torrent-harbor-engine')
    settings=Path('/var/lib/torrent-harbor/engine/settings.json')
    old=json.loads(settings.read_text());old['speed-limit-up']=321;settings.write_text(json.dumps(old))
    command('dpkg','-i',str(ROOT/'dist/torrent-harbor_1.2.0_all.deb'))
    assert Path('/etc/torrent-harbor/config.json').read_bytes()==before
    command('systemd-analyze','verify','/usr/lib/systemd/system/torrent-harbor.service','/usr/lib/systemd/system/torrent-harbor-paths.service','/usr/lib/systemd/system/torrent-harbor-engine.service')
    start_services();wait(lambda:urllib.request.urlopen('http://127.0.0.1:8080').status==200);login()
    wait(lambda:rpc('session-get'))
    assert rpc('session-get')['speed-limit-up']==321
    download=owned(Path('/var/lib/torrent-harbor/test-download'))
    partial=owned(Path('/var/lib/torrent-harbor/test-partial'))
    destination=owned(Path('/var/lib/torrent-harbor/test-moved'))
    located=owned(Path('/var/lib/torrent-harbor/test-located'))
    checked=api('/api/path-check',{'path':download});assert checked['writable'] and checked['free']>0
    try:api('/api/path-check',{'path':'/root'})
    except AssertionError as exc:assert '400' in str(exc)
    else:raise AssertionError('Protected folder accepted')
    rpc('session-set',{'download-dir':download,'incomplete-dir':partial,'incomplete-dir-enabled':False,'speed-limit-up':777})
    # Create a deterministic local multi-file torrent. No public copyrighted data or trackers.
    source=Path('/tmp/harbor-source');(source/'bundle').mkdir(parents=True,exist_ok=True)
    (source/'bundle/a.bin').write_bytes(b'a'*65536);(source/'bundle/b.bin').write_bytes(b'b'*65536)
    storage=lt.file_storage();storage.add_file('bundle/a.bin',65536);storage.add_file('bundle/b.bin',65536)
    creator=lt.create_torrent(storage,16384,flags=lt.create_torrent.v1_only)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as route:
        route.connect(('192.0.2.1',9));peer_host=route.getsockname()[0]
    peer={'port':0,'host':peer_host}
    class Tracker(BaseHTTPRequestHandler):
        def do_GET(self):
            body=lt.bencode({'interval':1,'complete':1,'incomplete':0,'peers':socket.inet_aton(peer['host'])+peer['port'].to_bytes(2,'big')})
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    tracker=ThreadingHTTPServer(('127.0.0.1',0),Tracker)
    threading.Thread(target=tracker.serve_forever,daemon=True).start()
    creator.add_tracker(f'http://127.0.0.1:{tracker.server_port}/announce')
    lt.set_piece_hashes(creator,str(source));raw=lt.bencode(creator.generate());info=lt.torrent_info(lt.bdecode(raw))
    seed=lt.session({'listen_interfaces':'0.0.0.0:0','enable_dht':False,'enable_lsd':False,'enable_upnp':False,'enable_natpmp':False})
    handle=seed.add_torrent({'ti':info,'save_path':str(source),'flags':lt.torrent_flags.seed_mode})
    handle.resume();peer['port']=seed.listen_port();assert peer['port']
    view=preview({'metainfo':base64.b64encode(raw).decode()});assert len(view['files'])==2
    assert not rpc('torrent-get',{'fields':['id']})['torrents'],'Preview added torrent to engine'
    result=api('/api/add',{'token':view['token'],'files':[{'wanted':True,'priority':1},{'wanted':False,'priority':-1}],'paused':True})
    tid=result['torrent-added']['id']
    def torrent():return rpc('torrent-get',{'ids':[tid],'fields':['id','status','fileStats','downloadDir','haveValid','errorString']})['torrents'][0]
    wait(lambda:torrent()['status']==0);t=torrent();assert t['status']==0;assert [x['wanted'] for x in t['fileStats']]==[True,False];assert [x['priority'] for x in t['fileStats']]==[1,-1]
    # Actual selective transfer through localhost tracker: omitted file must not download.
    rpc('torrent-start',{'ids':[tid]})
    try:wait(lambda:torrent()['fileStats'][0]['bytesCompleted']==65536,45)
    except Exception:
        print(rpc('torrent-get',{'ids':[tid],'fields':['status','errorString','trackerStats','peers','fileStats']}),flush=True)
        print('seed',handle.status().state,handle.status().is_seeding,handle.status().num_peers,flush=True)
        raise
    rpc('torrent-stop',{'ids':[tid]})
    assert torrent()['fileStats'][1]['bytesCompleted']==0,'Unwanted aligned file downloaded'
    # Supply second file too, verify it, then exercise actual disk move and locate-existing.
    shutil.copytree(source/'bundle',Path(download)/'bundle',dirs_exist_ok=True)
    for path in (Path(download)/'bundle').rglob('*'):shutil.chown(path,'torrent-harbor','torrent-harbor')
    shutil.chown(Path(download)/'bundle','torrent-harbor','torrent-harbor')
    rpc('torrent-verify',{'ids':[tid]});wait(lambda:torrent()['haveValid']==131072)
    api('/api/relocate',{'id':tid,'path':destination,'move':True})
    wait(lambda:torrent()['downloadDir']==destination and (Path(destination)/'bundle/a.bin').exists())
    assert (Path(destination)/'bundle/a.bin').read_bytes()==b'a'*65536
    shutil.move(str(Path(destination)/'bundle'),str(Path(located)/'bundle'))
    api('/api/relocate',{'id':tid,'path':located,'move':False});wait(lambda:torrent()['downloadDir']==located and torrent()['haveValid']==131072)
    # Libtorrent seeder on localhost: fetch metadata and assert no file payload is downloaded.
    port=seed.listen_port();assert port
    magnet=lt.make_magnet_uri(info)+f'&x.pe=127.0.0.1:{port}'
    metadata=preview({'magnet':magnet});assert len(metadata['files'])==2
    assert not list(Path('/tmp').glob('harbor-metadata-*')),'Resolver temporary directory leaked'
    api('/api/preview-cancel',{'token':metadata['token']});seed.remove_torrent(handle);tracker.shutdown();tracker.server_close()
    # Graceful restart must retain session settings, file selection, location and torrent.
    stop_services();start_services();wait(lambda:urllib.request.urlopen('http://127.0.0.1:8080').status==200);login();wait(lambda:rpc('session-get'))
    assert rpc('session-get')['download-dir']==download and rpc('session-get')['speed-limit-up']==777
    t=torrent();assert t['downloadDir']==located and [x['wanted'] for x in t['fileStats']]==[True,False]
    api('/api/logout',{})
    try:api('/api/session')
    except AssertionError as exc:assert '401' in str(exc)
    else:raise AssertionError('Logout did not revoke session')
    stop_services();command('dpkg','--remove','torrent-harbor')
    assert (Path(located)/'bundle/a.bin').exists() and Path('/etc/torrent-harbor/config.json').read_bytes()==before
    print('PASS Ubuntu 24.04: install/upgrade/remove, actual Transmission 4, persistence, selective local transfer, priorities, real move/locate, protected path, metadata-only magnet, login/logout')

if __name__=='__main__':
    try:main()
    finally:
        if processes:stop_services()
