'use strict';
const $ = id => document.getElementById(id);
let torrents=[], filter='all', removing=null, loading=false;
const states=['На паузе','В очереди проверки','Проверка','В очереди загрузки','Загрузка','В очереди раздачи','Раздача'];
function node(tag, cls, text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function bytes(n){n=Number(n)||0;const units=['Б','КиБ','МиБ','ГиБ','ТиБ'];let i=0;while(n>=1024&&i<4){n/=1024;i++;}return `${n.toFixed(i?1:0)} ${units[i]}`;}
function notify(e){$('notice').textContent=e instanceof Error?e.message:String(e);}
let csrf='';
const sessionReady=fetch('/api/session').then(async r=>{if(!r.ok){location.replace('/login');throw Error('Требуется вход');}const data=await r.json();csrf=data.csrf;return data;});
async function api(path,body={}){
 await sessionReady;
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Harbor-Request':'1','X-Harbor-CSRF':csrf},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
 const data=await response.json();if(response.status===401){location.replace('/login');throw Error('Сессия истекла');}if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;
}
async function rpc(method,args={}){const data=await api('/api/rpc',{method,arguments:args});if(data.result!=='success')throw Error(data.result||'Ошибка движка');return data.arguments;}
$('logout').onclick=async()=>{try{await api('/api/logout');location.replace('/login');}catch(e){notify(e);}};
function applyTheme(){const v=$('theme').value;document.documentElement.dataset.theme=v==='system'?(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'):v;localStorage.setItem('harbor-theme',v);}
$('theme').value=localStorage.getItem('harbor-theme')||'system';applyTheme();$('theme').onchange=applyTheme;matchMedia('(prefers-color-scheme: light)').addEventListener('change',applyTheme);
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('filters').onclick=e=>{const b=e.target.closest('button');if(!b)return;filter=b.dataset.filter;document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x===b));render();};
$('search').oninput=render;$('sort').onchange=render;$('refresh').onclick=refresh;$('add-open').onclick=openAdd;
function render(){const list=$('list');list.replaceChildren();$('count').textContent=torrents.length;let items=torrents.filter(t=>t.name.toLowerCase().includes($('search').value.toLowerCase())&&(filter==='all'||filter==='down'&&[3,4].includes(t.status)||filter==='seed'&&[5,6].includes(t.status)||filter==='stop'&&t.status===0||filter==='error'&&t.error));const sort=$('sort').value;items.sort((a,b)=>sort==='name'?a.name.localeCompare(b.name):b[sort]-a[sort]);if(!items.length){const e=node('div','empty');e.append(node('strong','',torrents.length?'Ничего не найдено':'Здесь начинается ваша библиотека'),node('div','','Добавьте торрент или magnet-ссылку, чтобы начать.'));list.append(e);return;}
for(const t of items){const card=node('article','torrent'),top=node('div','torrent-top'),name=node('button','torrent-name',t.name);name.onclick=()=>details(t);top.append(name,node('span','badge',t.error?'Ошибка':states[t.status]||'Ожидание'));const progress=node('div','progress'),bar=node('div','progress-bar');bar.style.setProperty('--progress',`${Math.max(0,Math.min(100,t.percentDone*100))}%`);progress.append(bar);const bottom=node('div','torrent-bottom'),metrics=node('div','metrics');for(const value of [`${(t.percentDone*100).toFixed(1)}% · ${bytes(t.haveValid)} / ${bytes(t.totalSize)}`,`↓ ${bytes(t.rateDownload)}/с`,`↑ ${bytes(t.rateUpload)}/с`,t.eta>=0?`Осталось ${Math.ceil(t.eta/60)} мин`:`Пиры: ${t.peersConnected}`])metrics.append(node('span','',value));const actions=node('div','actions');const filesButton=node('button','','Файлы');filesButton.onclick=()=>details(t);actions.append(filesButton);const locationButton=node('button','','Папка');locationButton.onclick=()=>openLocation(t);actions.append(locationButton);for(const [label,method] of [[t.status===0?'▶ Старт':'Ⅱ Пауза',t.status===0?'torrent-start':'torrent-stop'],['↻ Проверить','torrent-verify']]){const b=node('button','',label);b.onclick=()=>action(b,method,{ids:[t.id]});actions.append(b);}const del=node('button','','Удалить');del.onclick=()=>{removing=t.id;$('remove-name').textContent=t.name;$('delete-data').checked=false;$('remove-dialog').showModal();};actions.append(del);bottom.append(metrics,actions);card.append(top,progress,bottom);if(t.errorString)card.append(node('div','error',t.errorString));list.append(card);}}
async function action(button,method,args){button.disabled=true;try{await rpc(method,args);notify('');await refresh();}catch(e){notify(e);}finally{button.disabled=false;}}
async function refresh(){if(loading)return;loading=true;try{const [data,stats,session]=await Promise.all([rpc('torrent-get',{fields:['id','name','status','percentDone','totalSize','haveValid','rateDownload','rateUpload','eta','peersConnected','error','errorString','addedDate']}),rpc('session-stats'),rpc('session-get')]);torrents=data.torrents;render();$('download').textContent=bytes(stats.downloadSpeed)+'/с';$('upload').textContent=bytes(stats.uploadSpeed)+'/с';$('active').textContent=stats.activeTorrentCount;$('total').textContent=`Всего торрентов: ${stats.torrentCount}`;$('space').textContent=bytes(session['download-dir-free-space']);$('connection').textContent='● Движок подключён';$('connection').style.color='var(--accent)';}catch(e){notify(e);$('connection').textContent='● Нет связи с движком';$('connection').style.color='#e6aa76';}finally{loading=false;}}
let previewToken=null, previewFiles=[], previewGeneration=0, defaultDirectory='';
function resetPreview(){previewFiles=[];$('add-preview').hidden=true;$('add-source').hidden=false;$('preview-reset').hidden=true;$('add-submit').textContent='Получить список файлов';$('add-status').textContent='';}
async function cancelPreview(){const token=previewToken;previewToken=null;previewGeneration++;if(token)await api('/api/preview-cancel',{token}).catch(()=>{});}
$('add-dialog').addEventListener('close',()=>{cancelPreview();resetPreview();$('add-form').reset();});
$('preview-reset').onclick=async()=>{await cancelPreview();resetPreview();};
async function openAdd(){
 $('add-dialog').showModal();
 try{const s=await rpc('session-get');defaultDirectory=s['download-dir'];$('directory').placeholder=defaultDirectory;$('paused').checked=!s['start-added-torrents'];}
 catch(e){$('add-status').textContent=e.message;}
}
function previewSummary(){
 const selected=previewFiles.filter(f=>f.wanted);
 $('preview-total').textContent=`Выбрано ${selected.length} из ${previewFiles.length} · ${bytes(selected.reduce((n,f)=>n+f.length,0))}`;
}
function renderPreview(data){
 $('preview-name').textContent=data.name;previewFiles=data.files.map(f=>({...f,wanted:true,priority:0}));
 const root=$('preview-files');root.replaceChildren();
 previewFiles.forEach((file,i)=>{
  const row=node('div','file'),label=node('label','file-name'),check=node('input');check.type='checkbox';check.checked=true;check.dataset.previewIndex=i;
  check.onchange=()=>{file.wanted=check.checked;previewSummary();};label.append(check,node('span','',file.name));row.append(label,node('small','',bytes(file.length)));
  const pl=node('label','file-priority','Приоритет'),select=node('select');select.setAttribute('aria-label',`Приоритет до добавления: ${file.name}`);
  for(const [value,title] of [[-1,'Низкий'],[0,'Обычный'],[1,'Высокий']]){const option=node('option','',title);option.value=value;select.append(option);}select.value='0';select.onchange=()=>{file.priority=Number(select.value);};pl.append(select);row.append(pl);root.append(row);
 });
 previewSummary();$('add-preview').hidden=false;$('add-source').hidden=true;$('preview-reset').hidden=false;$('add-submit').textContent='Добавить выбранные файлы';$('add-status').textContent='';
}
for(const [id,wanted] of [['preview-all',true],['preview-none',false]])$(id).onclick=()=>{previewFiles.forEach(f=>{f.wanted=wanted;});document.querySelectorAll('[data-preview-index]').forEach(e=>{e.checked=wanted;});previewSummary();};
async function showPathCheck(path,status,write=true){
 const target=$(status);target.textContent='Проверка…';target.className='muted';
 try{const result=await api('/api/path-check',{path,write});target.textContent=`${write?'Запись доступна':'Чтение доступно'} · свободно ${bytes(result.free)} · ${result.path}`;target.className='success';return result;}
 catch(e){target.textContent=e.message;target.className='error';throw e;}
}
$('add-path-check').onclick=()=>showPathCheck($('directory').value.trim()||defaultDirectory,'add-path-status').catch(()=>{});
$('add-form').onsubmit=async event=>{
 event.preventDefault();const button=event.submitter;button.disabled=true;
 const generation=++previewGeneration;
 try{
  if(previewToken && previewFiles.length){
   if(!previewFiles.some(f=>f.wanted))throw Error('Выберите хотя бы один файл');
   const result=await api('/api/add',{token:previewToken,files:previewFiles.map(({wanted,priority})=>({wanted,priority})),directory:$('directory').value.trim(),paused:$('paused').checked});
   previewToken=null;$('add-dialog').close();notify(result['torrent-duplicate']?'Этот торрент уже добавлен. Его настройки не изменены.':'Торрент добавлен с выбранными файлами');await refresh();return;
  }
  const file=$('torrent-file').files[0],magnet=$('magnet').value.trim(),request={};
  if(Boolean(file)===Boolean(magnet))throw Error('Укажите либо magnet-ссылку, либо один .torrent-файл');
  if(file){
   if(file.size>5*1024*1024)throw Error('Максимальный размер .torrent — 5 МиБ');
   const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));request.metainfo=btoa(binary);
  }else{if(!magnet.startsWith('magnet:?'))throw Error('Нужна magnet-ссылка');request.magnet=magnet;}
  $('add-status').textContent=magnet?'Получение метаданных без загрузки файлов. Обычно это занимает несколько секунд, максимум — 90 секунд.':'Чтение списка файлов…';
  const started=await api('/api/preview',request);
  if(generation!==previewGeneration){await api('/api/preview-cancel',{token:started.token});return;}
  previewToken=started.token;
  while(generation===previewGeneration){
   const data=await api('/api/preview-status',{token:previewToken});
   if(generation!==previewGeneration)return;
   if(data.state==='ready'){renderPreview(data);return;}
   if(data.state==='error'){await cancelPreview();throw Error(data.error);}
   await new Promise(resolve=>setTimeout(resolve,800));
  }
 }catch(e){if(previewToken&&!previewFiles.length)await cancelPreview();if($('add-dialog').open)$('add-status').textContent=e.message;}
 finally{button.disabled=false;}
};
let locationTorrent=null;
async function openLocation(t){
 try{
  const result=await rpc('torrent-get',{ids:[t.id],fields:['downloadDir']});if(!result.torrents.length)throw Error('Торрент уже удалён');
  locationTorrent=t;$('location-name').textContent=t.name;$('location-current').textContent='Сейчас: '+result.torrents[0].downloadDir;
  $('location-path').value=result.torrents[0].downloadDir;$('location-move').checked=true;$('location-status').textContent='';$('location-dialog').showModal();
 }catch(e){notify(e);}
}
$('location-check').onclick=()=>showPathCheck($('location-path').value.trim(),'location-status',$('location-move').checked).catch(()=>{});
$('location-form').onsubmit=async event=>{
 event.preventDefault();const button=event.submitter;button.disabled=true;$('location-status').textContent='Передача запроса движку…';
 try{
  const result=await api('/api/relocate',{id:locationTorrent.id,path:$('location-path').value.trim(),move:$('location-move').checked});
  $('location-status').className='success';$('location-status').textContent=result.message;
  for(let i=0;i<15 && $('location-dialog').open;i++){
   const data=await rpc('torrent-get',{ids:[locationTorrent.id],fields:['downloadDir','errorString']});const t=data.torrents[0];
   if(!t)throw Error('Торрент удалён');if(t.errorString)throw Error(t.errorString);
   if(t.downloadDir===result.path){$('location-current').textContent='Сейчас: '+t.downloadDir;break;}
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
  await refresh();
 }catch(e){$('location-status').className='error';$('location-status').textContent=e.message;}finally{button.disabled=false;}
};
$('remove-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{await rpc('torrent-remove',{ids:[removing],'delete-local-data':$('delete-data').checked});$('remove-dialog').close();await refresh();}catch(e){notify(e);}finally{b.disabled=false;}};
// Settings are applied through RPC, so Transmission owns persistence.
const settingFields = [
 ['Папки', 'download-dir', 'Папка загрузки по умолчанию', 'path'],
 ['', 'incomplete-dir-enabled', 'Отдельная папка для незавершённых загрузок', 'bool'],
 ['', 'incomplete-dir', 'Папка незавершённых загрузок', 'path'],
 ['', 'start-added-torrents', 'Запускать новые торренты автоматически', 'bool'],
 ['', 'rename-partial-files', 'Добавлять .part к незавершённым файлам', 'bool'],
 ['Скорость', 'speed-limit-down-enabled', 'Ограничивать загрузку', 'bool'],
 ['', 'speed-limit-down', 'Загрузка, КиБ/с', 'number', 0, 10000000],
 ['', 'speed-limit-up-enabled', 'Ограничивать отдачу', 'bool'],
 ['', 'speed-limit-up', 'Отдача, КиБ/с', 'number', 0, 10000000],
 ['', 'alt-speed-enabled', 'Альтернативные лимиты скорости (режим черепахи)', 'bool'],
 ['Очередь и раздача', 'download-queue-enabled', 'Ограничивать число одновременных загрузок', 'bool'],
 ['', 'download-queue-size', 'Одновременных загрузок', 'number', 1, 10000],
 ['', 'seed-queue-enabled', 'Ограничивать число одновременных раздач', 'bool'],
 ['', 'seed-queue-size', 'Одновременных раздач', 'number', 1, 10000],
 ['', 'seedRatioLimited', 'Останавливать раздачу по рейтингу', 'bool'],
 ['', 'seedRatioLimit', 'Рейтинг отдачи (отдано / скачано)', 'number', 0, 100000, '0.01'],
 ['Соединения', 'peer-port', 'Входящий порт пиров, TCP/UDP', 'number', 1, 65535],
 ['', 'peer-limit-global', 'Максимум пиров всего', 'number', 1, 100000],
 ['', 'peer-limit-per-torrent', 'Максимум пиров на торрент', 'number', 1, 100000],
 ['', 'dht-enabled', 'DHT — поиск пиров без трекера', 'bool'],
 ['', 'pex-enabled', 'PEX — обмен пирами', 'bool'],
 ['', 'lpd-enabled', 'Поиск пиров в локальной сети', 'bool'],
 ['', 'port-forwarding-enabled', 'Автоматический проброс порта (UPnP / NAT-PMP)', 'bool'],
 ['', 'encryption', 'Шифрование соединений с пирами', 'select']
];
let settingsSnapshot = {}, detailTorrent = null, fileDraft = [];
function settingId(key) { return 'setting-' + key; }
$('settings-open').onclick = async () => {
 const button = $('settings-open'); button.disabled = true;
 try {
  settingsSnapshot = await rpc('session-get');
  const root = $('settings-fields'); root.replaceChildren();
  for (const [section,key,title,type,min,max,step] of settingFields) {
   if (section) root.append(node('h3', '', section));
   if (!(key in settingsSnapshot)) continue;
   const label = node('label', type === 'bool' ? 'check' : '', type === 'bool' ? undefined : title);
   const input = node(type === 'select' ? 'select' : 'input'); input.id = settingId(key);
   if (type === 'select') {
    for (const [value,text] of [['preferred','Предпочитать'],['required','Требовать'],['tolerated','Разрешать без шифрования']]) {
     const option = node('option','',text); option.value=value; input.append(option);
    }
   } else input.type = type === 'bool' ? 'checkbox' : type === 'number' ? 'number' : 'text';
   if (type === 'bool') { input.checked = settingsSnapshot[key]; label.append(input,document.createTextNode(title)); }
   else {
    input.value = settingsSnapshot[key]; input.required = true;
    if (type === 'number') { input.min=min; input.max=max; input.step=step||'1'; }
    if (type === 'path') input.pattern='/.*';
    label.append(input);
    if(type==='path'){
     const button=node('button','','Проверить папку');button.type='button';const status=node('p','muted');status.id='check-'+key;
     button.onclick=()=>showPathCheck(input.value.trim(),status.id).catch(()=>{});label.append(button,status);
    }
   }
   root.append(label);
  }
  root.append(node('p','muted','Папки должны быть доступны пользователю torrent-harbor на запись. Смена папки не перемещает существующие торренты.'));
  $('settings-status').textContent=''; $('settings-dialog').showModal();
 } catch (e) { notify(e); } finally { button.disabled=false; }
};
$('settings-form').onsubmit = async e => {
 e.preventDefault(); const button=e.submitter; button.disabled=true;
 try {
  const changes={};
  for (const [,key,,type] of settingFields) {
   const input=$(settingId(key)); if(!input) continue;
   const value=type==='bool'?input.checked:type==='number'?Number(input.value):input.value.trim();
   if(value!==settingsSnapshot[key]) changes[key]=value;
  }
  if(Object.keys(changes).length) await rpc('session-set',changes);
  $('settings-dialog').close(); notify('Настройки сохранены'); await refresh();
 } catch(e) { $('settings-status').textContent=e.message; } finally { button.disabled=false; }
};
async function details(t) {
 try {
  const d=await rpc('torrent-get',{ids:[t.id],fields:['files','fileStats','metadataPercentComplete','downloadDir','uploadRatio','trackerStats']});
  if(!d.torrents.length) { notify('Торрент уже удалён'); return; }
  const x=d.torrents[0]; detailTorrent=t; fileDraft=[];
  $('detail-title').textContent=t.name; $('files-status').textContent=''; $('files-status').classList.remove('success');
  const root=$('detail-content');
  root.replaceChildren(node('p','muted',`Папка: ${x.downloadDir}`),node('p','muted',`Рейтинг отдачи: ${Number(x.uploadRatio).toFixed(2)}`));
  const ready=x.metadataPercentComplete>=1 && x.files.length>0 && x.fileStats.length===x.files.length;
  $('files-save').disabled=!ready;
  if(!ready) {
   root.append(node('p','muted','Список файлов появится после получения метаданных. Для magnet-ссылки может понадобиться временно запустить торрент.'));
   const retry=node('button','','Обновить список'); retry.type='button'; retry.onclick=()=>details(t); root.append(retry);
  } else {
   root.append(node('p','muted','Снимите отметку, чтобы пропустить файл. Приоритет определяет порядок загрузки; уже скачанные данные не удаляются. Выбор применяется после сохранения.'));
   const tools=node('div','file-tools');
   for(const [title,wanted] of [['Выбрать все',true],['Снять все',false]]) {
    const b=node('button','',title); b.type='button'; b.onclick=()=>{
     root.querySelectorAll('input[data-file-index]').forEach(input=>{input.checked=wanted; fileDraft[Number(input.dataset.fileIndex)].wanted=wanted;});
    }; tools.append(b);
   }
   root.append(tools);
   x.files.forEach((f,i)=>{
    const stats=x.fileStats[i], original={wanted:stats.wanted,priority:stats.priority};
    fileDraft.push({...original,original});
    const row=node('div','file file-choice'), label=node('label','file-name');
    const check=node('input'); check.type='checkbox'; check.checked=stats.wanted; check.dataset.fileIndex=i;
    check.onchange=()=>{fileDraft[i].wanted=check.checked;};
    label.append(check,node('span','',f.name));
    const progress=node('small','',`${bytes(stats.bytesCompleted)} / ${bytes(f.length)} · ${f.length?Math.floor(stats.bytesCompleted/f.length*100):100}%`);
    const priorityLabel=node('label','file-priority','Приоритет'); const priority=node('select'); priority.setAttribute('aria-label',`Приоритет: ${f.name}`);
    for(const [value,text] of [[-1,'Низкий'],[0,'Обычный'],[1,'Высокий']]){const option=node('option','',text);option.value=value;priority.append(option);}
    priority.value=stats.priority; priority.onchange=()=>{fileDraft[i].priority=Number(priority.value);};
    priorityLabel.append(priority);row.append(label,progress,priorityLabel);root.append(row);
   });
  }
  for(const tracker of x.trackerStats||[])root.append(node('p','muted',`${tracker.host}: ${tracker.lastAnnounceResult||'Ожидание анонса'}`));
  if(!$('detail-dialog').open)$('detail-dialog').showModal();
 } catch(e){ $('detail-dialog').open ? $('files-status').textContent=e.message : notify(e); }
}
$('files-form').onsubmit=async e=>{
 e.preventDefault();const button=e.submitter;button.disabled=true;
 try {
  const changes={ids:[detailTorrent.id]};
  fileDraft.forEach((f,i)=>{
   if(f.wanted!==f.original.wanted){const key=f.wanted?'files-wanted':'files-unwanted';(changes[key]??=[]).push(i);}
   if(f.priority!==f.original.priority){const key=f.priority===1?'priority-high':f.priority===-1?'priority-low':'priority-normal';(changes[key]??=[]).push(i);}
  });
  // Never send empty file arrays: Transmission treats [] as "all files".
  if(Object.keys(changes).length>1)await rpc('torrent-set',changes);
  await details(detailTorrent); $('files-status').textContent='Выбор и приоритеты сохранены'; $('files-status').classList.add('success'); await refresh();
 } catch(e){$('files-status').classList.remove('success');$('files-status').textContent=e.message;} finally{button.disabled=false;}
};
refresh();setInterval(refresh,3000);
