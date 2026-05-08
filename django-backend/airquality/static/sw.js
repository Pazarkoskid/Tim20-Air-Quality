self.addEventListener('push', function(event) {
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'Air Quality AI – Скопје';
  const options = {
    body: data.body || 'Ново известување за квалитет на воздух',
    icon: '/static/avatars/avatar1.svg',
    badge: '/static/avatars/avatar1.svg',
    tag: 'airquality-notification',
    renotify: true,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  event.waitUntil(clients.openWindow('/notifications/'));
});
