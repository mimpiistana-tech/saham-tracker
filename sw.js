const DB_NAME = 'stockradar_background';
const DB_VERSION = 2;
const PAPER_STORE = 'paper_trades';
const ALERT_STORE = 'background_alerts';
const META_STORE = 'monitor_meta';
const API_BASE = 'https://saham-tracker-api.onrender.com';

function openDb(){
  return new Promise((resolve,reject)=>{
    const req = indexedDB.open(DB_NAME,DB_VERSION);

    req.onupgradeneeded = ()=>{
      const db = req.result;

      if(!db.objectStoreNames.contains(PAPER_STORE)){
        db.createObjectStore(PAPER_STORE,{keyPath:'id'});
      }

      if(!db.objectStoreNames.contains(ALERT_STORE)){
        db.createObjectStore(ALERT_STORE,{keyPath:'event_key'});
      }

      if(!db.objectStoreNames.contains(META_STORE)){
        db.createObjectStore(META_STORE,{keyPath:'key'});
      }
    };

    req.onsuccess = ()=>resolve(req.result);
    req.onerror = ()=>reject(req.error);
  });
}

async function getAll(storeName){
  const db = await openDb();

  return new Promise((resolve,reject)=>{
    const tx = db.transaction(storeName,'readonly');
    const store = tx.objectStore(storeName);
    const req = store.getAll();

    req.onsuccess = ()=>resolve(req.result || []);
    req.onerror = ()=>reject(req.error);
  });
}

async function putOne(storeName,value){
  const db = await openDb();

  return new Promise((resolve,reject)=>{
    const tx = db.transaction(storeName,'readwrite');
    tx.objectStore(storeName).put(value);
    tx.oncomplete = ()=>resolve();
    tx.onerror = ()=>reject(tx.error);
  });
}

async function createAlert(item,title,message,eventKey){
  const existing = await getAll(ALERT_STORE);

  if(existing.some(x=>x.event_key === eventKey)){
    return;
  }

  const alertItem = {
    event_key:eventKey,
    id:Date.now(),
    ticker:item.ticker,
    title,
    message,
    created_at:new Date().toISOString()
  };

  await putOne(ALERT_STORE,alertItem);

  await self.registration.showNotification(title,{
    body:message,
    icon:'./icon-192.png',
    badge:'./icon-192.png',
    tag:eventKey,
    renotify:false,
    data:{url:'./'}
  });
}

async function detectAlerts(previous,current){
  const oldStatus = previous?.status || 'WAIT_ENTRY';
  const newStatus = current?.status || oldStatus;

  if(oldStatus === newStatus){
    return;
  }

  const fmt = (v)=>{
    const n = Number(v || 0);
    return n >= 1000 ? (n/1000).toFixed(2)+'K' : n.toFixed(0);
  };

  if(
    oldStatus === 'WAIT_ENTRY' &&
    ['OPEN','TP1_HIT','TP2','CL'].includes(newStatus)
  ){
    await createAlert(
      current,
      '🎯 ENTRY ' + current.ticker,
      'Harga menyentuh entry ' + fmt(current.entry) + '.',
      current.id + ':ENTRY'
    );
  }

  if(
    oldStatus !== 'TP1_HIT' &&
    ['TP1_HIT','TP2'].includes(newStatus)
  ){
    await createAlert(
      current,
      '✅ TP1 ' + current.ticker,
      'TP1 ' + fmt(current.tp1) + ' sudah tersentuh.',
      current.id + ':TP1'
    );
  }

  if(newStatus === 'TP2'){
    await createAlert(
      current,
      '🏆 TP2 ' + current.ticker,
      'TP2 ' + fmt(current.tp2) + ' sudah tersentuh.',
      current.id + ':TP2'
    );
  }

  if(newStatus === 'CL'){
    await createAlert(
      current,
      '🛑 CUT LOSS ' + current.ticker,
      'Level CL ' + fmt(current.cut_loss) + ' sudah tersentuh.',
      current.id + ':CL'
    );
  }
}

async function checkOne(item){
  const createdTs = Number(
    item.created_ts ||
    Math.floor(new Date(item.created_at || Date.now()).getTime()/1000)
  );

  const url =
    API_BASE +
    '/api/paper-check?ticker=' + encodeURIComponent(item.ticker) +
    '&since=' + encodeURIComponent(createdTs) +
    '&entry=' + encodeURIComponent(item.entry) +
    '&tp1=' + encodeURIComponent(item.tp1) +
    '&tp2=' + encodeURIComponent(item.tp2) +
    '&cl=' + encodeURIComponent(item.cut_loss);

  const response = await fetch(url,{cache:'no-store'});

  if(!response.ok){
    throw new Error('HTTP ' + response.status);
  }

  const data = await response.json();

  const current = {
    ...item,
    created_ts:createdTs,
    status:data.state || item.status,
    last_price:Number(data.last_price || 0),
    pnl_pct:data.pnl_pct == null ? null : Number(data.pnl_pct),
    monitor_note:data.note || '',
    tp1_hit:Boolean(data.tp1_hit),
    entry_triggered:Boolean(data.entry_triggered),
    high_since:Number(data.high_since || 0),
    low_since:Number(data.low_since || 0),
    last_checked_at:data.checked_at || null,
    auto_source:data.source || '',
    exit_price:data.exit_price == null ? item.exit_price : Number(data.exit_price),
    exit_time:data.exit_time || item.exit_time || null,
    realized_pnl_pct:
      ['TP2','CL'].includes(data.state) &&
      Number(item.entry || 0) > 0 &&
      Number(data.exit_price || 0) > 0
      ? ((Number(data.exit_price)/Number(item.entry))-1)*100
      : item.realized_pnl_pct
  };

  await detectAlerts(item,current);
  await putOne(PAPER_STORE,current);
}

async function checkAllPaperTrades(trigger='background'){
  const startedAt = Date.now();

  await putOne(META_STORE,{
    key:'health',
    state:'RUNNING',
    trigger,
    last_started_at:startedAt,
    last_finished_at:null,
    checked:0,
    failures:0,
    last_error:null
  });

  const rows = await getAll(PAPER_STORE);

  const active = rows.filter(x =>
    ['WAIT_ENTRY','OPEN','TP1_HIT'].includes(x.status)
  );

  let checked = 0;
  let failures = 0;
  let lastError = null;

  for(const item of active){
    try{
      await checkOne(item);
      checked += 1;
    }catch(e){
      failures += 1;
      lastError = String(e?.message || e);
      console.log('Background paper check failed',item.ticker,e);
    }
  }

  const finishedAt = Date.now();

  await putOne(META_STORE,{
    key:'health',
    state:failures > 0 ? 'DEGRADED' : 'OK',
    trigger,
    last_started_at:startedAt,
    last_finished_at:finishedAt,
    checked,
    failures,
    active_positions:active.length,
    duration_ms:finishedAt - startedAt,
    last_error:lastError
  });
}

self.addEventListener('install',event=>{
  self.skipWaiting();
});

self.addEventListener('activate',event=>{
  event.waitUntil(self.clients.claim());
});

self.addEventListener('periodicsync',event=>{
  if(event.tag === 'stockradar-paper-monitor'){
    event.waitUntil(checkAllPaperTrades('periodic-sync'));
  }
});

self.addEventListener('sync',event=>{
  if(event.tag === 'stockradar-paper-sync'){
    event.waitUntil(checkAllPaperTrades('background-sync'));
  }
});

self.addEventListener('message',event=>{
  if(event.data?.type === 'CHECK_PAPER_NOW'){
    event.waitUntil(checkAllPaperTrades('manual-message'));
  }
});

self.addEventListener('notificationclick',event=>{
  event.notification.close();

  event.waitUntil(
    self.clients.matchAll({
      type:'window',
      includeUncontrolled:true
    }).then(clients=>{
      for(const client of clients){
        if('focus' in client){
          client.navigate('./');
          return client.focus();
        }
      }

      if(self.clients.openWindow){
        return self.clients.openWindow('./');
      }
    })
  );
});
