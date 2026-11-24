// CarWithin public relay: lets a head unit reach the iPhone's receiver page even when the car
// only sees RFC1918 addresses (Tesla blocks those) — the iPhone dials out, so no inbound access
// and no port forwarding are needed. Same idea as Tesmirror's cloud hop, self-hosted.
//
//   iPhone  : wss://<host>/device?k=<deviceKey>
//   Car     : https://<host>/d/<deviceKey>/tesla      (HTML page)
//             https://<host>/d/<deviceKey>/mjpeg      (MJPEG stream)
//             wss://<host>/d/<deviceKey>/stream       (touch channel)
//
// Device wire format (binary frames after the JSON preamble):
//   [u32 requestId][payload]
// Control messages are JSON text frames.
import { DurableObject } from 'cloudflare:workers';

const HEADER_LIMIT = 16 * 1024;
const BOUNDARY = 'frame';

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

export class DeviceHub extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.device = null;
    this.seq = 0;
    this.streams = new Map(); // requestId -> ReadableStreamDefaultController
    this.sockets = new Map(); // requestId -> WebSocket (browser side)
  }

  // ---- device side -------------------------------------------------------
  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === '/device') {
      if ((request.headers.get('upgrade') || '').toLowerCase() !== 'websocket') {
        return json({ error: 'websocket required' }, 400);
      }
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      server.accept();
      this.device = server;
      server.addEventListener('message', (event) => this.fromDevice(event.data));
      server.addEventListener('close', () => {
        if (this.device === server) this.device = null;
        for (const controller of this.streams.values()) {
          try { controller.close(); } catch { /* already closed */ }
        }
        this.streams.clear();
      });
      return new Response(null, { status: 101, webSocket: client });
    }

    if (!this.device) return json({ error: 'device offline' }, 503);

    // ---- browser side ----------------------------------------------------
    const relayPath = url.pathname.replace(/^\/d\/[^/]+/, '') || '/';
    const wantsSocket = (request.headers.get('upgrade') || '').toLowerCase() === 'websocket';

    if (wantsSocket || relayPath === '/stream') {
      const id = ++this.seq;
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      server.accept();
      this.sockets.set(id, server);
      this.device.send(JSON.stringify({ t: 'ws-open', id }));
      server.addEventListener('message', (event) => {
        const data = typeof event.data === 'string' ? event.data : null;
        if (data !== null) this.device.send(JSON.stringify({ t: 'ws-msg', id, data }));
      });
      server.addEventListener('close', () => {
        this.sockets.delete(id);
        this.device?.send(JSON.stringify({ t: 'ws-close', id }));
      });
      return new Response(null, { status: 101, webSocket: client });
    }

    const id = ++this.seq;
    const headers = {};
    for (const [k, v] of request.headers) {
      if (k.toLowerCase() === 'host' || k.toLowerCase() === 'cf-') continue;
      headers[k] = v;
    }
    const wantsStream = relayPath === '/mjpeg';

    if (!wantsStream) {
      // Buffered request (pages, test clips, JSON): wait for the device's answer.
      const answer = new Promise((resolve) => {
        this.pending = this.pending || new Map();
        this.pending.set(id, resolve);
      });
      this.device.send(JSON.stringify({ t: 'req', id, method: request.method, path: relayPath, headers }));
      const timeout = new Promise((resolve) => setTimeout(() => resolve(null), 30_000));
      const result = await Promise.race([answer, timeout]);
      if (!this.pending.delete(id)) { /* timed out */ }
      if (!result) return json({ error: 'device timeout' }, 504);
      return new Response(result.body, {
        status: result.status || 200,
        headers: {
          'content-type': result.contentType || 'application/octet-stream',
          'cache-control': 'no-store',
          'access-control-allow-origin': '*',
        },
      });
    }

    // Streaming (MJPEG): keep the response open and forward binary frames as they arrive.
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    this.streams.set(id, writer);
    this.device.send(JSON.stringify({ t: 'open', id, path: relayPath }));
    request.signal?.addEventListener('abort', () => {
      this.streams.delete(id);
      this.device?.send(JSON.stringify({ t: 'close', id }));
      writer.close().catch(() => {});
    });
    return new Response(readable, {
      headers: {
        'content-type': `multipart/x-mixed-replace; boundary=${BOUNDARY}`,
        'cache-control': 'no-store',
        'access-control-allow-origin': '*',
      },
    });
  }

  fromDevice(data) {
    if (typeof data === 'string') {
      let msg;
      try { msg = JSON.parse(data); } catch { return; }
      if (msg.t === 'res') {
        const resolve = this.pending?.get(msg.id);
        if (resolve) { this.pending.delete(msg.id); resolve(msg); }
        return;
      }
      if (msg.t === 'ws-msg') {
        const socket = this.sockets.get(msg.id);
        if (socket && socket.readyState === 1) socket.send(msg.data);
        return;
      }
      if (msg.t === 'ws-close') {
        const socket = this.sockets.get(msg.id);
        if (socket) { try { socket.close(); } catch { /* ignore */ } this.sockets.delete(msg.id); }
        return;
      }
      if (msg.t === 'gone') {
        const writer = this.streams.get(msg.id);
        if (writer) { try { writer.close(); } catch { /* ignore */ } this.streams.delete(msg.id); }
      }
      return;
    }
    // Binary: [u32 requestId][payload]
    const view = new DataView(data);
    if (data.byteLength < 4) return;
    const id = view.getUint32(0);
    const payload = data.slice(4);
    const writer = this.streams.get(id);
    if (!writer) return;
    const head = new TextEncoder().encode(
      `--${BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: ${payload.byteLength}\r\n\r\n`);
    const tail = new TextEncoder().encode('\r\n');
    writer.write(head).then(() => writer.write(payload)).then(() => writer.write(tail)).catch(() => {
      this.streams.delete(id);
      this.device?.send(JSON.stringify({ t: 'close', id }));
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const match = url.pathname.match(/^\/d\/([A-Za-z0-9_-]{6,40})(\/.*)?$/);
    if (!match) {
      if (url.pathname === '/health') return json({ ok: true, service: 'carwithin-relay' });
      return json({ error: 'use /d/<deviceKey>/...', service: 'carwithin-relay' }, 404);
    }
    const key = match[1];
    const id = env.DEVICE.idFromName(key);
    const stub = env.DEVICE.get(id);
    const inner = new URL(request.url);
    inner.pathname = url.pathname.replace(/^\/d\/[^/]+/, '') || '/';
    if (inner.pathname === '/device') inner.pathname = '/device';
    return stub.fetch(new Request(inner.toString(), request));
  },
};
