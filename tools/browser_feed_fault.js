// Installed explicitly by Docker browser checks; never served by the viewer.
// Only the browser/media boundary is substituted. The backend keeps running.
(() => {
  const original = window.fetch.bind(window);
  const fault = window.mediaFault = {attempts:0, next:null, active:null, bytes:0};
  window.checkOwnedSessions = [];
  window.fetch = async (...args) => {
    const path = String(args[0]);
    if (!path.includes('/media/live/') && !path.includes('/media/playback/')) {
      const response = await original(...args);
      if (args[1]?.method==='POST' && /^\/api\/(live|playback)\/sessions$/.test(path) && response.ok) {
        const {id} = await response.clone().json();
        checkOwnedSessions.push(`${path}/${id}`);
      }
      return response;
    }
    ++fault.attempts;
    if (fault.next === 'empty') return new Response(new Uint8Array(0));
    if (fault.next === 'forbidden') return new Response('', {status:403});
    if (fault.next === 'hang-once') {
      fault.next = null;
      return new Promise((_, reject) => {
        const signal=args[1].signal;
        const cancelled=()=>reject(new DOMException('Simulated header timeout','AbortError'));
        signal.addEventListener('abort',cancelled,{once:true});
        if (signal.aborted) cancelled();
      });
    }
    const response = await original(...args);
    if (!response.ok) return response;
    const reader = response.body.getReader();
    let closed = false, discard = false;
    return new Response(new ReadableStream({
      start(controller) {
        fault.active = kind => {
          if (closed) return;
          if (kind === 'stall') { discard = true; return; }
          closed = true;
          if (kind === 'error') controller.error(new TypeError('Simulated media disconnect'));
          else controller.close();
          reader.cancel().catch(() => {});
        };
        (async () => {
          try {
            while (!closed) {
              const {value, done} = await reader.read();
              if (closed) return;
              if (done) { closed = true; controller.close(); return; }
              fault.bytes += value.length;
              if (!discard) controller.enqueue(value);
            }
          } catch (error) { if (!closed) { closed = true; controller.error(error); } }
        })();
      },
      cancel() { closed = true; return reader.cancel().catch(() => {}); }
    }), {status:response.status, headers:response.headers});
  };
})();
