const CACHE = 'bez-odciec-shell-v2';
self.addEventListener('install', (event) => { event.waitUntil((async()=>{const cache=await caches.open(CACHE);const response=await fetch('/precache-manifest.json',{cache:'no-store'});if(!response.ok)throw new Error('Brak manifestu zasobów offline.');const assets=await response.json();await cache.addAll(['/', '/favicon.svg', '/manifest.webmanifest', ...assets.filter(path=>path.startsWith('/assets/'))]);await self.skipWaiting();})()); });
self.addEventListener('activate', (event) => { event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))); self.clients.claim(); });
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api') || url.pathname.startsWith('/health')) return;
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok && (url.pathname.startsWith('/assets/') || url.pathname === '/' || url.pathname.endsWith('.svg'))) {
      const copy = response.clone(); caches.open(CACHE).then((cache) => cache.put(event.request, copy));
    }
    return response;
  }).catch(async () => (await caches.match(event.request)) || (event.request.mode === 'navigate' ? await caches.match('/') : undefined) || new Response('Brak zapisanego zasobu offline', {status: 503})));
});
