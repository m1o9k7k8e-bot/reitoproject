const V='azabu-social-v4.1';
const A=['./','./index.html','./style.css','./app.js','./visual-bank.js','./patch-v4.js','./manifest.webmanifest','./icon.svg','./bank00.js','./bank01.js','./bank02.js','./bank03.js','./bank04.js','./bank05.js','./bank06.js','./bank07.js','./bank08.js','./bank09a.js','./bank09b.js','./bank09c.js','./bank09d.js','./bank09e.js'];
self.addEventListener('install',e=>e.waitUntil(caches.open(V).then(c=>c.addAll(A)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(Promise.all([self.clients.claim(),caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==V).map(k=>caches.delete(k))))])));
self.addEventListener('fetch',e=>e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request))));