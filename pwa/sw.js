const PREFIX='amos-link-mobile-';
const CACHE=PREFIX+'v3.0.0';
const ROOT=new URL('./',self.location.href).href;
const SHELL=['./','app.css','app.js','connection.js','scanner.js','vendor/jsQR.js','manifest.webmanifest','icons/icon-192.png','icons/icon-512.png'];
self.addEventListener('install',event=>{
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL.map(path=>new URL(path,ROOT).href))).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',event=>{
  event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith(PREFIX)&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET'||!request.url.startsWith(ROOT))return;
  const url=new URL(request.url);
  if(url.pathname.includes('/api/')||url.pathname.includes('/ws/'))return;
  if(request.mode==='navigate'){
    event.respondWith(fetch(request).catch(()=>caches.match(ROOT)));
  }else{
    event.respondWith(caches.open(CACHE).then(cache=>cache.match(request).then(cached=>cached||fetch(request))));
  }
});
