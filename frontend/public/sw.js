/* No patient data or authenticated responses are cached. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let tag = 'pharmascan-reminder';
  let chinese = false;
  let test = false;
  try {const data = event.data?.json();chinese=data?.language==='zh';test=data?.purpose==='test';if(typeof data?.tag === 'string' && /^[a-f0-9]{32}$/.test(data.tag))tag=data.tag;} catch { /* Fixed private message also handles malformed payloads. */ }
  event.waitUntil(self.registration.showNotification('MediThread', {
    body: test?(chinese?'这是一条测试通知。':'This is a test notification.'):(chinese?'请查看您的用药计划。':"It's time to check your medication plan."), tag, icon:'/icon.svg', data:{url:'/#today'},
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async()=>{
    const url=new URL('/#today',self.location.origin).href;
    const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    const existing=windows.find(client=>new URL(client.url).origin===self.location.origin);
    if(existing){await existing.navigate(url);await existing.focus();}else await self.clients.openWindow(url);
  })());
});
