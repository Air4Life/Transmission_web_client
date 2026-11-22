'use strict';
const $ = id => document.getElementById(id);
let torrents=[], filter='all', removing=null, loading=false;
const states=['На паузе','В очереди проверки','Проверка','В очереди загрузки','Загрузка','В очереди раздачи','Раздача'];
function node(tag, cls, text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function bytes(n){n=Number(n)||0;const units=['Б','КиБ','МиБ','ГиБ','ТиБ'];let i=0;while(n>=1024&&i<4){n/=1024;i++;}return `${n.toFixed(i?1:0)} ${units[i]}`;}
function notify(e){$('notice').textContent=e instanceof Error?e.message:String(e);}
async function rpc(method,args={}){const r=await fetch('/api/rpc',{method:'POST',headers:{'Content-Type':'application/json','X-Harbor-Request':'1'},body:JSON.stringify({method,arguments:args}),signal:AbortSignal.timeout(25000)});if(!r.ok){let body=await r.json().catch(()=>({}));throw Error(body.error||`HTTP ${r.status}`);}const data=await r.json();if(data.result!=='success')throw Error(data.result||'Ошибка движка');return data.arguments;}
function applyTheme(){const v=$('theme').value;document.documentElement.dataset.theme=v==='system'?(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'):v;localStorage.setItem('harbor-theme',v);}
$('theme').value=localStorage.getItem('harbor-theme')||'system';applyTheme();$('theme').onchange=applyTheme;matchMedia('(prefers-color-scheme: light)').addEventListener('change',applyTheme);
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('filters').onclick=e=>{const b=e.target.closest('button');if(!b)return;filter=b.dataset.filter;document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x===b));render();};
$('search').oninput=render;$('sort').onchange=render;$('refresh').onclick=refresh;$('add-open').onclick=()=>$('add-dialog').showModal();
function render(){const list=$('list');list.replaceChildren();$('count').textContent=torrents.length;let items=torrents.filter(t=>t.name.toLowerCase().includes($('search').value.toLowerCase())&&(filter==='all'||filter==='down'&&[3,4].includes(t.status)||filter==='seed'&&[5,6].includes(t.status)||filter==='stop'&&t.status===0||filter==='error'&&t.error));const sort=$('sort').value;items.sort((a,b)=>sort==='name'?a.name.localeCompare(b.name):b[sort]-a[sort]);if(!items.length){const e=node('div','empty');e.append(node('strong','',torrents.length?'Ничего не найдено':'Здесь начинается ваша библиотека'),node('div','','Добавьте торрент или magnet-ссылку, чтобы начать.'));list.append(e);return;}
for(const t of items){const card=node('article','torrent'),top=node('div','torrent-top'),name=node('button','torrent-name',t.name);name.onclick=()=>details(t);top.append(name,node('span','badge',t.error?'Ошибка':states[t.status]||'Ожидание'));const progress=node('div','progress'),bar=node('div','progress-bar');bar.style.setProperty('--progress',`${Math.max(0,Math.min(100,t.percentDone*100))}%`);progress.append(bar);const bottom=node('div','torrent-bottom'),metrics=node('div','metrics');for(const value of [`${(t.percentDone*100).toFixed(1)}% · ${bytes(t.haveValid)} / ${bytes(t.totalSize)}`,`↓ ${bytes(t.rateDownload)}/с`,`↑ ${bytes(t.rateUpload)}/с`,t.eta>=0?`Осталось ${Math.ceil(t.eta/60)} мин`:`Пиры: ${t.peersConnected}`])metrics.append(node('span','',value));const actions=node('div','actions');const filesButton=node('button','','Файлы');filesButton.onclick=()=>details(t);actions.append(filesButton);for(const [label,method] of [[t.status===0?'▶ Старт':'Ⅱ Пауза',t.status===0?'torrent-start':'torrent-stop'],['↻ Проверить','torrent-verify']]){const b=node('button','',label);b.onclick=()=>action(b,method,{ids:[t.id]});actions.append(b);}const del=node('button','','Удалить');del.onclick=()=>{removing=t.id;$('remove-name').textContent=t.name;$('delete-data').checked=false;$('remove-dialog').showModal();};actions.append(del);bottom.append(metrics,actions);card.append(top,progress,bottom);if(t.errorString)card.append(node('div','error',t.errorString));list.append(card);}}
async function action(button,method,args){button.disabled=true;try{await rpc(method,args);notify('');await refresh();}catch(e){notify(e);}finally{button.disabled=false;}}
async function refresh(){if(loading)return;loading=true;try{const [data,stats,session]=await Promise.all([rpc('torrent-get',{fields:['id','name','status','percentDone','totalSize','haveValid','rateDownload','rateUpload','eta','peersConnected','error','errorString','addedDate']}),rpc('session-stats'),rpc('session-get')]);torrents=data.torrents;render();$('download').textContent=bytes(stats.downloadSpeed)+'/с';$('upload').textContent=bytes(stats.uploadSpeed)+'/с';$('active').textContent=stats.activeTorrentCount;$('total').textContent=`Всего торрентов: ${stats.torrentCount}`;$('space').textContent=bytes(session['download-dir-free-space']);$('connection').textContent='● Движок подключён';$('connection').style.color='var(--accent)';}catch(e){notify(e);$('connection').textContent='● Нет связи с движком';$('connection').style.color='#e6aa76';}finally{loading=false;}}
$('add-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{const file=$('torrent-file').files[0],magnet=$('magnet').value.trim();if(Boolean(file)===Boolean(magnet))throw Error('Укажите либо magnet-ссылку, либо один .torrent-файл.');const args={paused:$('paused').checked};if(file){if(file.size>5*1024*1024)throw Error('Максимальный размер .torrent — 5 МиБ');const data=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<data.length;i+=8192)binary+=String.fromCharCode(...data.subarray(i,i+8192));args.metainfo=btoa(binary);}else{if(!magnet.startsWith('magnet:?'))throw Error('Нужна magnet-ссылка');args.filename=magnet;}if($('directory').value.trim())args['download-dir']=$('directory').value.trim();const result=await rpc('torrent-add',args);$('add-dialog').close();$('add-form').reset();notify(result['torrent-duplicate']?'Этот торрент уже добавлен.':'Торрент добавлен');await refresh();}catch(e){notify(e);alert(e.message);}finally{b.disabled=false;}};
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
