import base64
import importlib.util
import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location('harbor', Path(__file__).parents[1] / 'server.py')
harbor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harbor)

class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), harbor.Handler)
        cls.server.config = {'username':'admin','password':'test-secret'}
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
    def request(self, path='/', payload=None, auth=True, csrf=True):
        headers = {}
        if auth: headers['Authorization']='Basic '+base64.b64encode(b'admin:test-secret').decode()
        if csrf: headers['X-Harbor-Request']='1'
        req=urllib.request.Request(self.url+path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try: return urllib.request.urlopen(req)
        except urllib.error.HTTPError as e: return e
    def test_password_required(self):
        self.assertEqual(self.request(auth=False).status,401)
    def test_assets_and_no_path_traversal(self):
        for path in ['/', '/app.js', '/style.css']:
            with self.request(path) as r:
                self.assertEqual(r.status,200)
                self.assertIn("frame-ancestors 'none'", r.headers['Content-Security-Policy'])
                self.assertTrue(r.read())
        self.assertEqual(self.request('/../server.py').status,404)
    def test_csrf_and_rpc_restrictions(self):
        self.assertEqual(self.request('/api/rpc',{'method':'session-get'},csrf=False).status,403)
        for p in [{'method':'session-close'},{'method':'session-set','arguments':{'rpc-bind-address':'0.0.0.0'}},{'method':'torrent-add','arguments':{'filename':'http://internal/private'}}, {'method':'torrent-get','arguments':[]}]:
            self.assertEqual(self.request('/api/rpc',p).status,400)
    def test_rpc_gateway_success_and_failure(self):
        with patch.object(harbor.rpc,'call',return_value={'result':'success','arguments':{'torrents':[]}}) as call:
            with self.request('/api/rpc',{'method':'torrent-get'}) as r:
                self.assertEqual(json.load(r)['result'],'success')
            call.assert_called_once()
        with patch.object(harbor.rpc,'call',side_effect=OSError('unavailable')):
            self.assertEqual(self.request('/api/rpc',{'method':'session-get'}).status,502)
    def test_settings_and_file_selection_forwarding(self):
        payloads = [
            {'method':'session-set','arguments':{'download-dir':'/mnt/media','incomplete-dir':'/mnt/partial','incomplete-dir-enabled':True,'download-queue-size':3,'seedRatioLimit':1.5,'encryption':'required'}},
            {'method':'torrent-set','arguments':{'ids':[7],'files-wanted':[0],'files-unwanted':[1],'priority-high':[0],'priority-low':[1]}}
        ]
        for payload in payloads:
            with patch.object(harbor.rpc,'call',return_value={'result':'success','arguments':{}}) as call:
                with self.request('/api/rpc',payload) as response:
                    self.assertEqual(response.status,200)
                call.assert_called_once_with(payload)
    def test_invalid_settings_never_reach_engine(self):
        for args in [{'download-dir':'relative/path'}, {'download-dir':'/bad\\0path'.replace('\\0',chr(0))}, {'peer-port':65536}, {'speed-limit-down':True}, {'download-queue-size':0}, {'dht-enabled':'true'}, {'seedRatioLimit':float('nan')}, {'encryption':'no'}, {'rpc-enabled':False}]:
            with patch.object(harbor.rpc,'call') as call:
                self.assertEqual(self.request('/api/rpc',{'method':'session-set','arguments':args}).status,400)
                call.assert_not_called()

    def test_malformed_body(self):
        self.assertEqual(self.request('/api/rpc',[]).status,400)

class HandshakeTests(unittest.TestCase):
    def test_transmission_409_handshake(self):
        class Engine(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.headers.get('X-Transmission-Session-Id') != 'test-token':
                    self.send_response(409)
                    self.send_header('X-Transmission-Session-Id','test-token')
                    self.end_headers()
                else:
                    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({'result':'success','arguments':body}).encode())
        engine=ThreadingHTTPServer(('127.0.0.1',0),Engine)
        threading.Thread(target=engine.serve_forever,daemon=True).start()
        original=urllib.request.urlopen
        def redirect(req,timeout):
            req.full_url=f'http://127.0.0.1:{engine.server_port}/transmission/rpc'
            return original(req,timeout=timeout)
        try:
            with patch.object(harbor.urllib.request,'urlopen',side_effect=redirect):
                result=harbor.RPC().call({'method':'session-stats'})
                self.assertEqual(result['arguments']['method'],'session-stats')
        finally:
            engine.shutdown()
            engine.server_close()

if __name__=='__main__': unittest.main()
