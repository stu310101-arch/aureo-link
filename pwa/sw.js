const CACHE = 'aureo-shell-v3';
const SHELL = ['/', '/app.css', '/app.js', '/manifest.webmanifest', '/icons/icon-192.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || request.url.includes('/api/') || request.url.includes('/ws/')) return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Network-first for HTML so pairing links update immediately. Cache only the shell assets.
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/')));
  } else {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request)));
  }
});
