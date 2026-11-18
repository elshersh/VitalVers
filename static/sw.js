/* Vitalverse minimal PWA Service Worker (Web Push + notification click routing) */
self.addEventListener('install', function () {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', function (event) {
  var data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'Vitalverse Alert', body: event.data ? event.data.text() : 'New mission health alert.' };
  }
  var title = data.title || 'Vitalverse Alert';
  var options = {
    body: data.body || 'Open Alerts Center to inspect details.',
    icon: '/img/icon-192.png',
    badge: '/img/icon-192.png',
    data: { url: data.url || '/alerts.html' }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var targetUrl = (event.notification.data && event.notification.data.url) || '/alerts.html';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clients) {
      for (var i = 0; i < clients.length; i++) {
        if ('focus' in clients[i]) {
          clients[i].navigate(targetUrl);
          return clients[i].focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
