"""In-memory login sessions and bounded attempt tracking. Never trust proxy IP headers."""
import hashlib
import hmac
import secrets
import threading
import time
from http.cookies import SimpleCookie, CookieError

class Auth:
    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}
        self.attempts = {}

    def session(self, cookie):
        try:
            jar = SimpleCookie(); jar.load(cookie or '')
            token = jar['harbor_session'].value if 'harbor_session' in jar else ''
        except CookieError:
            return None
        with self.lock:
            now = time.monotonic()
            self.sessions = {k:v for k,v in self.sessions.items() if v['expires'] > now}
            return self.sessions.get(token)

    def login(self, config, username, password, address):
        now = time.monotonic()
        with self.lock:
            self.attempts = {k:v for k,v in self.attempts.items() if v['until'] > now}
            if self.attempts.get(address, {}).get('count', 0) >= 5:
                return None, 429
            # Hash fixed-size strings before constant-time comparison, including Unicode.
            equal = lambda a,b: hmac.compare_digest(hashlib.sha256(a.encode()).digest(), hashlib.sha256(b.encode()).digest())
            if not (equal(username, config['username']) & equal(password, config['password'])):
                if len(self.attempts) >= 4096 and address not in self.attempts:
                    return None, 429
                entry = self.attempts.setdefault(address, {'count':0, 'until':now + 300})
                entry['count'] += 1
                return None, 401
            self.attempts.pop(address, None)
            self.sessions = {k:v for k,v in self.sessions.items() if v['expires'] > now}
            if len(self.sessions) >= 128:
                self.sessions.pop(next(iter(self.sessions)))
            token = secrets.token_urlsafe(32)
            session = {'token':token, 'csrf':secrets.token_urlsafe(32), 'expires':now + 12*3600}
            self.sessions[token] = session
            return session, 200

    def logout(self, cookie):
        session = self.session(cookie)
        if session:
            with self.lock:
                self.sessions.pop(session['token'], None)
