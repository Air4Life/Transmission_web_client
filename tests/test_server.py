import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('harbor',Path(__file__).parents[1]/'server.py')
harbor=importlib.util.module_from_spec(spec);spec.loader.exec_module(harbor)

class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=harbor.ThreadingHTTPServer(('127.0.0.1',0),harbor.Handler)
        cls.server.config={'username':'admin','password':'test-secret'}
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls): cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        harbor.auth=harbor.Auth();self.cookie='';self.csrf=''
        with self.request('/api/login',{'username':'admin','password':'test-secret'}) as r:
            self.cookie=r.headers['Set-Cookie'].split(';')[0];self.csrf=json.load(r)['csrf']
    def request(self,path='/',payload=None,auth=True,csrf=True):
        headers={'X-Harbor-Request':'1'}
        if auth: headers['Cookie']=self.cookie
        if csrf: headers['X-Harbor-CSRF']=self.csrf
        req=urllib.request.Request(self.url+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        try:return urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:return e
    def test_session_and_login_page(self):
        self.assertEqual(self.request('/api/session',auth=False).status,401)
        with self.request('/',auth=False) as r:self.assertIn(b'login-form',r.read())
        self.assertEqual(self.request('/api/session').status,200)
        with self.request('/api/login',{'username':'admin','password':'test-secret'}) as r:
            cookie=r.headers['Set-Cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)
        self.assertEqual(self.request('/api/rpc',{'method':'session-get'},auth=False).status,401)
    def test_logout_revokes_session(self):
        self.assertEqual(self.request('/api/logout',{}).status,200)
        self.assertEqual(self.request('/api/session').status,401)
    def test_login_throttle_and_proxy_header_not_trusted(self):
        for _ in range(5):self.assertEqual(self.request('/api/login',{'username':'admin','password':'bad'}).status,401)
        self.assertEqual(self.request('/api/login',{'username':'admin','password':'test-secret'}).status,429)
    def test_csrf_and_restrictions(self):
        self.assertEqual(self.request('/api/rpc',{'method':'session-get'},csrf=False).status,403)
        for p in [{'method':'session-close'},{'method':'session-set','arguments':{'rpc-bind-address':'0.0.0.0'}},{'method':'torrent-get','arguments':[]}]:
            self.assertEqual(self.request('/api/rpc',p).status,400)
    def test_static_files_and_traversal(self):
        for path in ['/','/app.js','/style.css','/login','/login.js']:
            with self.request(path) as r:self.assertEqual(r.status,200);self.assertTrue(r.read())
        self.assertEqual(self.request('/../server.py').status,404)
    def test_settings_and_file_selection_forwarding(self):
        for payload in [{'method':'session-set','arguments':{'download-dir':'/mnt/media','incomplete-dir':'/mnt/partial','incomplete-dir-enabled':True,'download-queue-size':3,'seedRatioLimit':1.5,'encryption':'required'}},{'method':'torrent-set','arguments':{'ids':[7],'files-wanted':[0],'files-unwanted':[1],'priority-high':[0],'priority-low':[1]}}]:
            with patch.object(harbor.rpc,'call',return_value={'result':'success','arguments':{}}) as call,patch.object(harbor,'probe_path',return_value={'path':'/mnt/media'}):
                self.assertEqual(self.request('/api/rpc',payload).status,200);call.assert_called_once_with(payload)
    def test_invalid_settings(self):
        for args in [{'download-dir':'relative'}, {'peer-port':65536}, {'speed-limit-down':True}, {'download-queue-size':0}, {'dht-enabled':'true'}, {'seedRatioLimit':float('nan')}, {'encryption':'no'}, {'rpc-enabled':False}]:
            with patch.object(harbor.rpc,'call') as call:
                self.assertEqual(self.request('/api/rpc',{'method':'session-set','arguments':args}).status,400);call.assert_not_called()
    def test_path_failure_blocks_save(self):
        with patch.object(harbor,'probe_path',side_effect=ValueError('Нет прав')),patch.object(harbor.rpc,'call') as call:
            with self.request('/api/rpc',{'method':'session-set','arguments':{'download-dir':'/bad'}}) as r:self.assertEqual(r.status,400);self.assertIn('Нет прав',json.load(r)['error'])
            call.assert_not_called()
    def test_add_selected_before_start_and_duplicate(self):
        preview={'state':'ready','metainfo':'encoded','files':[{'length':100},{'length':50}]}
        request={'token':'token','files':[{'wanted':True,'priority':1},{'wanted':False,'priority':-1}],'paused':False}
        for duplicate in [False,True]:
            calls=[]
            def engine(method,args=None):
                calls.append((method,args))
                return {'session-get':{'download-dir':'/downloads'},'torrent-add':{'torrent-duplicate' if duplicate else 'torrent-added':{'id':7}},'torrent-start':{}}[method]
            with patch.object(harbor.previews,'get',return_value=preview),patch.object(harbor.previews,'cancel'),patch.object(harbor,'probe_path',return_value={'path':'/downloads','free':1000}),patch.object(harbor,'engine',side_effect=engine):
                self.assertEqual(self.request('/api/add',request).status,200)
                args=calls[1][1];self.assertTrue(args['paused']);self.assertEqual(args['files-unwanted'],[1]);self.assertEqual(args['priority-high'],[0]);self.assertEqual(args['priority-low'],[1])
                self.assertEqual(any(m=='torrent-start' for m,a in calls),not duplicate)
    def test_move_and_locate(self):
        for move in [False,True]:
            with patch.object(harbor,'probe_path',return_value={'path':'/new','free':1000}) as probe,patch.object(harbor,'engine',side_effect=lambda m,a:{'torrents':[{'downloadDir':'/old','haveValid':10,'haveUnchecked':0}]} if m=='torrent-get' else {}) as engine:
                self.assertEqual(self.request('/api/relocate',{'id':7,'path':'/new','move':move}).status,200)
                probe.assert_called_once_with('/new',write=move)
                engine.assert_any_call('torrent-set-location',{'ids':[7],'location':'/new','move':move})
                self.assertEqual(any(c.args[0]=='torrent-verify' for c in engine.call_args_list),not move)
    def test_engine_unavailable(self):
        with patch.object(harbor.rpc,'call',side_effect=OSError('unavailable')):self.assertEqual(self.request('/api/rpc',{'method':'session-get'}).status,502)
    def test_preview_ownership(self):
        previews=harbor.Previews()
        previews.jobs['token']={'owner':'a','expires':float('inf'),'state':'ready','result':{'files':[],'metainfo':'private'}}
        with self.assertRaises(ValueError):previews.get('b','token')
        self.assertNotIn('metainfo',previews.get('a','token'))
        previews.cancel('b','token');self.assertIn('token',previews.jobs)
        previews.cancel_owner('a');self.assertNotIn('token',previews.jobs)
    def test_directory_listing_requires_auth_and_csrf(self):
        self.assertEqual(self.request('/api/directories',{'path':'/'},auth=False).status,401)
        self.assertEqual(self.request('/api/directories',{'path':'/'},csrf=False).status,403)
        response={'path':'/mnt','parent':'/','entries':[],'offset':0,'next_offset':None,'total':0,'free':1000}
        with patch.object(harbor,'probe_request',return_value=response) as helper:
            with self.request('/api/directories',{'path':'/mnt','offset':100,'query':'media','hidden':True}) as result:
                self.assertEqual(result.status,200);self.assertEqual(json.load(result),response)
            helper.assert_called_once_with({'operation':'list','path':'/mnt','offset':100,'query':'media','hidden':True})
    def test_directory_listing(self):
        from path_probe import list_directories
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ['Alpha','beta','.hidden']:(root/name).mkdir()
            (root/'ordinary-file.txt').write_text('no files in picker')
            (root/'link').symlink_to(root/'Alpha',target_is_directory=True)
            data=list_directories(d)
            self.assertEqual([e['name'] for e in data['entries']],['Alpha','beta','link'])
            self.assertTrue(data['entries'][2]['symlink'])
            self.assertEqual(list_directories(str(root/'link'))['path'],str(root/'Alpha'))
            self.assertEqual(list_directories(d,query='ALP')['total'],1)
            self.assertEqual(list_directories(d,hidden=True)['total'],4)
            for i in range(110):(root/f'folder-{i:03}').mkdir()
            first=list_directories(d);self.assertEqual(len(first['entries']),100);self.assertEqual(first['next_offset'],100)
            second=list_directories(d,offset=100);self.assertEqual(len(second['entries']),13);self.assertIsNone(second['next_offset'])
            for bad in [-1,True,'100']:
                with self.assertRaises(ValueError):list_directories(d,offset=bad)
            with self.assertRaises(ValueError):list_directories(str(root/'ordinary-file.txt'))

    def test_path_probe(self):
        from path_probe import check_path
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(check_path(d)['writable']);self.assertEqual(list(Path(d).iterdir()),[])
            with self.assertRaises(FileNotFoundError):check_path(d+'/missing')
            with self.assertRaises(ValueError):check_path('relative')

if __name__=='__main__':unittest.main()
