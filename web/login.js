'use strict';
const theme=localStorage.getItem('harbor-theme')||'system';
document.documentElement.dataset.theme=theme==='system'?(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'):theme;
document.getElementById('login-form').onsubmit=async event=>{
 event.preventDefault();const button=event.submitter;button.disabled=true;
 try{
  const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json','X-Harbor-Request':'1'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value}),signal:AbortSignal.timeout(15000)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'Не удалось войти');location.replace('/');
 }catch(error){document.getElementById('login-status').textContent=error.message;}finally{button.disabled=false;}
};
