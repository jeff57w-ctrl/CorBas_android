// CorBas Service Worker - Offline Support
const CACHE_NAME = 'corbas-v1';
const RUNTIME_CACHE = 'corbas-runtime-v1';

// Files to cache immediately on install
const PRECACHE_URLS = [
  '/',
  '/corbas.html',
  '/manifest.json',
  '/icons/icon-192x192.png',
  '/icons/icon-512x512.png',
  'https://cdn.tailwindcss.com'
];

// Install event - cache essential files
self.addEventListener('install', event => {
  console.log('CorBas Service Worker: Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('CorBas Service Worker: Caching app shell');
        return cache.addAll(PRECACHE_URLS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
  console.log('CorBas Service Worker: Activating...');
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames
          .filter(cacheName => {
            return cacheName !== CACHE_NAME && cacheName !== RUNTIME_CACHE;
          })
          .map(cacheName => {
            console.log('CorBas Service Worker: Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Skip chrome extensions and non-http requests
  if (!url.protocol.startsWith('http')) {
    return;
  }

  // API requests - Network first, then cache
  if (url.pathname.startsWith('/analyze') || 
      url.pathname.startsWith('/health') || 
      url.pathname.startsWith('/highlight_pdf')) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Static assets - Cache first, then network
  event.respondWith(cacheFirst(request));
});

// Cache first strategy - for static assets
async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  
  if (cached) {
    console.log('CorBas Service Worker: Serving from cache:', request.url);
    return cached;
  }

  try {
    const response = await fetch(request);
    
    // Cache successful responses
    if (response.status === 200) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(request, response.clone());
    }
    
    return response;
  } catch (error) {
    console.error('CorBas Service Worker: Fetch failed:', error);
    
    // Return offline page if available
    const offlineResponse = await cache.match('/offline.html');
    if (offlineResponse) {
      return offlineResponse;
    }
    
    // Return a basic offline response
    return new Response(
      '<html><body><h1>Offline</h1><p>Please check your internet connection.</p></body></html>',
      { headers: { 'Content-Type': 'text/html' } }
    );
  }
}

// Network first strategy - for API calls
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    
    // Cache successful API responses
    if (response.status === 200) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(request, response.clone());
    }
    
    return response;
  } catch (error) {
    console.log('CorBas Service Worker: Network failed, trying cache:', request.url);
    
    // Try to serve from cache
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    
    // Return error response
    return new Response(
      JSON.stringify({ 
        error: 'You are offline. Please connect to the internet to analyze text.' 
      }),
      { 
        status: 503,
        headers: { 'Content-Type': 'application/json' }
      }
    );
  }
}

// Handle messages from the app
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});