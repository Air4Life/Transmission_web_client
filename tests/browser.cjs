const {chromium}=require('playwright');
const {spawn}=require('child_process');
const fs=require('fs');
(async()=>{
const config='/tmp/harbor-browser-config.json';fs.writeFileSync(config,JSON.stringify({listen:'127.0.0.1',port:18080,username:'admin',password:'test'}),{mode:0o600});
const server=spawn('python3',['server.py'],{env:{...process.env,HARBOR_CONFIG:config}});
let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({httpCredentials:{username:'admin',password:'test'}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const calls=[];
 let settings={'download-dir':'/downloads','incomplete-dir':'/partial','incomplete-dir-enabled':false,'start-added-torrents':true,'rename-partial-files':true,'speed-limit-down-enabled':false,'speed-limit-up-enabled':false,'speed-limit-down':1000,'speed-limit-up':500,'download-dir-free-space':500000000000,'download-queue-size':5,'seedRatioLimit':2,'encryption':'preferred'};
 let stats=[{wanted:true,priority:0,bytesCompleted:42},{wanted:true,priority:0,bytesCompleted:0}];
 let failFiles=false, metadataReady=true;

 await page.route('**/api/rpc',async route=>{
 const p=route.request().postDataJSON();calls.push(p);
 let arguments={};
 if(p.method==='torrent-get')arguments={torrents:[{id:1,name:'Ubuntu 24.04 LTS.iso',status:4,percentDone:.42,totalSize:6000000000,haveValid:2520000000,rateDownload:12500000,rateUpload:140000,eta:300,peersConnected:12,error:0,errorString:'',addedDate:1}]};
 if(p.method==='session-stats')arguments={downloadSpeed:12500000,uploadSpeed:140000,activeTorrentCount:1,torrentCount:1};
 if(p.method==='session-get')arguments={...settings};
 if(p.method==='session-set')Object.assign(settings,p.arguments);
 if(p.method==='torrent-get' && p.arguments.fields.includes('fileStats'))arguments={torrents:[{downloadDir:'/downloads',uploadRatio:0.5,metadataPercentComplete:metadataReady?1:0,trackerStats:[],files:[{name:'video.mkv',length:100},{name:'extras/readme.txt',length:100}],fileStats:stats.map(s=>({...s}))}]};
 if(p.method==='torrent-set'){
  if(failFiles){failFiles=false;return route.fulfill({json:{result:'simulated engine error',arguments:{}}});}
  for(const [key,value] of [['files-wanted',true],['files-unwanted',false]])for(const i of p.arguments[key]||[])stats[i].wanted=value;
  for(const [key,value] of [['priority-high',1],['priority-normal',0],['priority-low',-1]])for(const i of p.arguments[key]||[])stats[i].priority=value;
 }

 await route.fulfill({json:{result:'success',arguments}});
 });
 await page.goto('http://127.0.0.1:18080');
 await page.getByText('Ubuntu 24.04 LTS.iso',{exact:true}).waitFor();
 await page.locator('#theme').selectOption('light');
 if(await page.locator('html').getAttribute('data-theme')!=='light')throw Error('Theme failed');
 await page.locator('#theme').selectOption('dark');
 await page.getByText('Ⅱ Пауза',{exact:true}).click();
 await page.locator('#add-open').click();await page.locator('#magnet').fill('magnet:?xt=urn:btih:0123456789012345678901234567890123456789');await page.locator('#add-form button[type=submit]').click();
 await page.waitForFunction(()=>!document.querySelector('#add-dialog').open);
 // Settings: persistence in RPC state after reload, changed-only payload, server error display.
 await page.locator('#settings-open').click();
 await page.locator('#setting-download-dir').fill('/mnt/media');
 await page.locator('#setting-incomplete-dir-enabled').check();
 await page.locator('#setting-incomplete-dir').fill('/mnt/partial');
 await page.locator('#setting-download-queue-size').fill('3');
 await page.locator('#settings-form button.primary').click();
 await page.waitForFunction(()=>!document.querySelector('#settings-dialog').open);
 await page.reload();await page.locator('.torrent-name').waitFor();
 await page.locator('#settings-open').click();
 if(await page.locator('#setting-download-dir').inputValue()!=='/mnt/media')throw Error('Directory not restored');
 if(!(await page.locator('#setting-incomplete-dir-enabled').isChecked()))throw Error('Incomplete not restored');
 await page.locator('#settings-dialog [data-close]').click();
 // File indices are zero-based; preserve unrelated priorities and omit empty arrays.
 await page.locator('.torrent-name').click();
 await page.locator('[data-file-index="1"]').uncheck();
 await page.getByLabel('Приоритет: video.mkv',{exact:true}).selectOption('1');
 failFiles=true;await page.locator('#files-save').click();
 await page.getByText('simulated engine error',{exact:true}).waitFor();
 if(await page.locator('[data-file-index="1"]').isChecked())throw Error('Lost draft on failure');
 await page.locator('#files-save').click();
 await page.getByText('Выбор и приоритеты сохранены',{exact:true}).waitFor();
 const saved=calls.filter(c=>c.method==='torrent-set').at(-1).arguments;
 if(JSON.stringify(saved)!==JSON.stringify({ids:[1],'priority-high':[0],'files-unwanted':[1]}))throw Error('Wrong file payload '+JSON.stringify(saved));
 await page.locator('#detail-dialog [data-close]').click();await page.locator('.torrent-name').click();
 if(await page.locator('[data-file-index="1"]').isChecked())throw Error('Unwanted file not restored');
 if(await page.getByLabel('Приоритет: video.mkv',{exact:true}).inputValue()!=='1')throw Error('Priority not restored');
 const before=calls.filter(c=>c.method==='torrent-set').length;
 await page.locator('#files-save').click();await page.getByText('Выбор и приоритеты сохранены',{exact:true}).waitFor();
 if(calls.filter(c=>c.method==='torrent-set').length!==before)throw Error('Unchanged files sent');
 await page.getByText('Снять все',{exact:true}).click();await page.locator('#files-save').click();
 await page.getByText('Выбор и приоритеты сохранены',{exact:true}).waitFor();
 if(stats.some(s=>s.wanted))throw Error('Unselect all failed');
 await page.getByText('Выбрать все',{exact:true}).click();await page.locator('#files-save').click();
 await page.getByText('Выбор и приоритеты сохранены',{exact:true}).waitFor();
 if(stats.some(s=>!s.wanted))throw Error('Select all failed');
 await page.setViewportSize({width:390,height:844});
 if(await page.evaluate(()=>document.querySelector('#detail-dialog').scrollWidth>document.querySelector('#detail-dialog').clientWidth))throw Error('File dialog overflow');
 await page.screenshot({path:'dist/files-mobile.png',fullPage:true});
 await page.locator('#detail-dialog [data-close]').click();
 await page.setViewportSize({width:1280,height:800});
 metadataReady=false;
 await page.getByRole('button',{name:'Файлы',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#detail-dialog').open);
 if(!(await page.locator('#files-save').isDisabled()))throw Error('Metadata pending allows save');
 await page.getByText('Список файлов появится после получения метаданных.',{exact:false}).waitFor();
 metadataReady=true;await page.getByRole('button',{name:'Обновить список',exact:true}).click();
 await page.locator('[data-file-index="0"]').waitFor();
 await page.locator('#detail-dialog [data-close]').click();
 await page.screenshot({path:'dist/desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'dist/mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 if(!calls.some(c=>c.method==='torrent-add')||!calls.some(c=>c.method==='torrent-stop'))throw Error('Action missing');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Browser checks passed: rendering, themes, pause, magnet, settings persistence, file selection, priorities, retry, mobile width; no JS errors.');
}finally{if(browser)await browser.close();server.kill();fs.unlinkSync(config);}
})().catch(e=>{console.error(e);process.exitCode=1;});
