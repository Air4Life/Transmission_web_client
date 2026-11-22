"""Bounded, session-owned preview jobs; magnet resolution is isolated and cancellable."""
import json
import secrets
import subprocess
import threading
import time
from pathlib import Path

class Previews:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}

    def clean(self):
        now = time.monotonic()
        for token, job in list(self.jobs.items()):
            if job['expires'] < now:
                if job.get('process'): job['process'].terminate()
                del self.jobs[token]

    def start(self, owner, request):
        with self.lock:
            self.clean()
            if len(self.jobs)>=16 or sum(j['state']=='pending' for j in self.jobs.values())>=2:
                raise ValueError('Слишком много предпросмотров. Закройте предыдущий или повторите позже.')
            if sum(j['owner']==owner for j in self.jobs.values())>=2:
                raise ValueError('Сначала закройте предыдущий предпросмотр')
            token=secrets.token_urlsafe(24)
            job={'owner':owner,'state':'pending','expires':time.monotonic()+600}
            self.jobs[token]=job
            thread=threading.Thread(target=self.run,args=(token,job,request),daemon=True)
            thread.start()
            return {'token':token,'state':'pending'}

    def run(self, token, job, request):
        try:
            with self.lock:
                if token not in self.jobs: return
                process=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).with_name('metadata.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                job['process']=process
            try:
                output,_=process.communicate(json.dumps(request),timeout=100)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate(); raise ValueError('Время получения метаданных истекло')
            result=json.loads(output)
            if result.get('error'): raise ValueError(result['error'])
            job.update(state='ready',result=result)
        except Exception as exc:
            job.update(state='error',error=str(exc))
        finally:
            job.pop('process',None)

    def get(self, owner, token, include_data=False):
        with self.lock:
            self.clean(); job=self.jobs.get(token)
            if not job or job['owner']!=owner: raise ValueError('Предпросмотр истёк. Добавьте торрент заново.')
            result={'token':token,'state':job['state']}
            if job['state']=='ready':
                result.update(job['result'])
                if not include_data: result.pop('metainfo',None)
            if job['state']=='error': result['error']=job['error']
            return result

    def cancel(self, owner, token):
        with self.lock:
            job=self.jobs.get(token)
            if job and job['owner']==owner:
                if job.get('process'): job['process'].terminate()
                del self.jobs[token]

    def cancel_owner(self, owner):
        with self.lock:
            tokens=[k for k,v in self.jobs.items() if v['owner']==owner]
        for token in tokens: self.cancel(owner,token)
