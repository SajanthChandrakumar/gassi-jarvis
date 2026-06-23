/*
 * Gassi-Jarvis service worker.
 *
 * Goal: make the PWA installable and load the shell instantly — WITHOUT ever
 * serving stale UI or interfering with the live backend.
 *
 *   - /api/* and any non-GET request: never touched, always hits the network.
 *   - Navigations: network-first, so a redeployed UI shows immediately;
 *     falls back to the cached shell only when offline.
 *   - /static/* assets: cache-first for speed.
 */
const CACHE = 'jarvis-shell-v1';
const SHELL = [
    '/',
    '/static/manifest.json',
    '/static/icon-192.png',
    '/static/icon-512.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const req = event.request;
    const url = new URL(req.url);

    if (req.method !== 'GET' || url.pathname.startsWith('/api/')) return;

    if (req.mode === 'navigate') {
        event.respondWith(fetch(req).catch(() => caches.match('/')));
        return;
    }

    if (url.pathname.startsWith('/static/')) {
        event.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
    }
});
