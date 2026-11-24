var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// worker.js
import { DurableObject } from "cloudflare:workers";
var HEADER_LIMIT = 16 * 1024;
var BOUNDARY = "frame";
function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" }
  });
}
__name(json, "json");
var DeviceHub = class extends DurableObject {
  static {
    __name(this, "DeviceHub");
  }
  constructor(ctx, env) {
    super(ctx, env);
    this.device = null;
    this.seq = 0;
    this.streams = /* @__PURE__ */ new Map();
    this.sockets = /* @__PURE__ */ new Map();
  }
  // ---- device side -------------------------------------------------------
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/device") {
      if ((request.headers.get("upgrade") || "").toLowerCase() !== "websocket") {
        return json({ error: "websocket required" }, 400);
      }
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      server.accept();
      this.device = server;
      server.addEventListener("message", (event) => this.fromDevice(event.data));
      server.addEventListener("close", () => {
        if (this.device === server) this.device = null;
        for (const controller of this.streams.values()) {
          try {
            controller.close();
          } catch {
          }
        }
        this.streams.clear();
      });
      return new Response(null, { status: 101, webSocket: client });
    }
    if (!this.device) return json({ error: "device offline" }, 503);
    const relayPath = url.pathname.replace(/^\/d\/[^/]+/, "") || "/";
    const wantsSocket = (request.headers.get("upgrade") || "").toLowerCase() === "websocket";
    if (wantsSocket || relayPath === "/stream") {
      const id2 = ++this.seq;
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      server.accept();
      this.sockets.set(id2, server);
      this.device.send(JSON.stringify({ t: "ws-open", id: id2 }));
      server.addEventListener("message", (event) => {
        const data = typeof event.data === "string" ? event.data : null;
        if (data !== null) this.device.send(JSON.stringify({ t: "ws-msg", id: id2, data }));
      });
      server.addEventListener("close", () => {
        this.sockets.delete(id2);
        this.device?.send(JSON.stringify({ t: "ws-close", id: id2 }));
      });
      return new Response(null, { status: 101, webSocket: client });
    }
    const id = ++this.seq;
    const headers = {};
    for (const [k, v] of request.headers) {
      if (k.toLowerCase() === "host" || k.toLowerCase() === "cf-") continue;
      headers[k] = v;
    }
    const wantsStream = relayPath === "/mjpeg";
    if (!wantsStream) {
      const answer = new Promise((resolve) => {
        this.pending = this.pending || /* @__PURE__ */ new Map();
        this.pending.set(id, resolve);
      });
      this.device.send(JSON.stringify({ t: "req", id, method: request.method, path: relayPath, headers }));
      const timeout = new Promise((resolve) => setTimeout(() => resolve(null), 3e4));
      const result = await Promise.race([answer, timeout]);
      if (!this.pending.delete(id)) {
      }
      if (!result) return json({ error: "device timeout" }, 504);
      return new Response(result.body, {
        status: result.status || 200,
        headers: {
          "content-type": result.contentType || "application/octet-stream",
          "cache-control": "no-store",
          "access-control-allow-origin": "*"
        }
      });
    }
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    this.streams.set(id, writer);
    this.device.send(JSON.stringify({ t: "open", id, path: relayPath }));
    request.signal?.addEventListener("abort", () => {
      this.streams.delete(id);
      this.device?.send(JSON.stringify({ t: "close", id }));
      writer.close().catch(() => {
      });
    });
    return new Response(readable, {
      headers: {
        "content-type": `multipart/x-mixed-replace; boundary=${BOUNDARY}`,
        "cache-control": "no-store",
        "access-control-allow-origin": "*"
      }
    });
  }
  fromDevice(data) {
    if (typeof data === "string") {
      let msg;
      try {
        msg = JSON.parse(data);
      } catch {
        return;
      }
      if (msg.t === "res") {
        const resolve = this.pending?.get(msg.id);
        if (resolve) {
          this.pending.delete(msg.id);
          resolve(msg);
        }
        return;
      }
      if (msg.t === "ws-msg") {
        const socket = this.sockets.get(msg.id);
        if (socket && socket.readyState === 1) socket.send(msg.data);
        return;
      }
      if (msg.t === "ws-close") {
        const socket = this.sockets.get(msg.id);
        if (socket) {
          try {
            socket.close();
          } catch {
          }
          this.sockets.delete(msg.id);
        }
        return;
      }
      if (msg.t === "gone") {
        const writer2 = this.streams.get(msg.id);
        if (writer2) {
          try {
            writer2.close();
          } catch {
          }
          this.streams.delete(msg.id);
        }
      }
      return;
    }
    const view = new DataView(data);
    if (data.byteLength < 4) return;
    const id = view.getUint32(0);
    const payload = data.slice(4);
    const writer = this.streams.get(id);
    if (!writer) return;
    const head = new TextEncoder().encode(
      `--${BOUNDARY}\r
Content-Type: image/jpeg\r
Content-Length: ${payload.byteLength}\r
\r
`
    );
    const tail = new TextEncoder().encode("\r\n");
    writer.write(head).then(() => writer.write(payload)).then(() => writer.write(tail)).catch(() => {
      this.streams.delete(id);
      this.device?.send(JSON.stringify({ t: "close", id }));
    });
  }
};
var worker_default = {
  async fetch(request, env) {
    const url = new URL(request.url);
    const match = url.pathname.match(/^\/d\/([A-Za-z0-9_-]{6,40})(\/.*)?$/);
    if (!match) {
      if (url.pathname === "/health") return json({ ok: true, service: "carwithin-relay" });
      return json({ error: "use /d/<deviceKey>/...", service: "carwithin-relay" }, 404);
    }
    const key = match[1];
    const id = env.DEVICE.idFromName(key);
    const stub = env.DEVICE.get(id);
    const inner = new URL(request.url);
    inner.pathname = url.pathname.replace(/^\/d\/[^/]+/, "") || "/";
    if (inner.pathname === "/device") inner.pathname = "/device";
    return stub.fetch(new Request(inner.toString(), request));
  }
};

// ../../poki-sign/cf-relay/node_modules/wrangler/templates/middleware/middleware-ensure-req-body-drained.ts
var drainBody = /* @__PURE__ */ __name(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } finally {
    try {
      if (request.body !== null && !request.bodyUsed) {
        const reader = request.body.getReader();
        while (!(await reader.read()).done) {
        }
      }
    } catch (e) {
      console.error("Failed to drain the unused request body.", e);
    }
  }
}, "drainBody");
var middleware_ensure_req_body_drained_default = drainBody;

// ../../poki-sign/cf-relay/node_modules/wrangler/templates/middleware/middleware-miniflare3-json-error.ts
function reduceError(e) {
  return {
    name: e?.name,
    message: e?.message ?? String(e),
    stack: e?.stack,
    cause: e?.cause === void 0 ? void 0 : reduceError(e.cause)
  };
}
__name(reduceError, "reduceError");
var jsonError = /* @__PURE__ */ __name(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } catch (e) {
    const error = reduceError(e);
    const body = JSON.stringify(error);
    const headers = {
      "Content-Type": "application/json",
      "MF-Experimental-Error-Stack": "true"
    };
    const encoded = encodeURIComponent(body);
    if (encoded.length <= 8192) {
      headers["MF-Experimental-Error-Stack-Payload"] = encoded;
    }
    return new Response(body, { status: 500, headers });
  }
}, "jsonError");
var middleware_miniflare3_json_error_default = jsonError;

// .wrangler/tmp/bundle-eNxfUT/middleware-insertion-facade.js
var __INTERNAL_WRANGLER_MIDDLEWARE__ = [
  middleware_ensure_req_body_drained_default,
  middleware_miniflare3_json_error_default
];
var middleware_insertion_facade_default = worker_default;

// ../../poki-sign/cf-relay/node_modules/wrangler/templates/middleware/common.ts
var __facade_middleware__ = [];
function __facade_register__(...args) {
  __facade_middleware__.push(...args.flat());
}
__name(__facade_register__, "__facade_register__");
function __facade_invokeChain__(request, env, ctx, dispatch, middlewareChain) {
  const [head, ...tail] = middlewareChain;
  const middlewareCtx = {
    dispatch,
    next(newRequest, newEnv) {
      return __facade_invokeChain__(newRequest, newEnv, ctx, dispatch, tail);
    }
  };
  return head(request, env, ctx, middlewareCtx);
}
__name(__facade_invokeChain__, "__facade_invokeChain__");
function __facade_invoke__(request, env, ctx, dispatch, finalMiddleware) {
  return __facade_invokeChain__(request, env, ctx, dispatch, [
    ...__facade_middleware__,
    finalMiddleware
  ]);
}
__name(__facade_invoke__, "__facade_invoke__");

// .wrangler/tmp/bundle-eNxfUT/middleware-loader.entry.ts
var __Facade_ScheduledController__ = class ___Facade_ScheduledController__ {
  constructor(scheduledTime, cron, noRetry) {
    this.scheduledTime = scheduledTime;
    this.cron = cron;
    this.#noRetry = noRetry;
  }
  scheduledTime;
  cron;
  static {
    __name(this, "__Facade_ScheduledController__");
  }
  #noRetry;
  noRetry() {
    if (!(this instanceof ___Facade_ScheduledController__)) {
      throw new TypeError("Illegal invocation");
    }
    this.#noRetry();
  }
};
function wrapExportedHandler(worker) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__ === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__.length === 0) {
    return worker;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__) {
    __facade_register__(middleware);
  }
  const fetchDispatcher = /* @__PURE__ */ __name(function(request, env, ctx) {
    if (worker.fetch === void 0) {
      throw new Error("Handler does not export a fetch() function.");
    }
    return worker.fetch(request, env, ctx);
  }, "fetchDispatcher");
  return {
    ...worker,
    fetch(request, env, ctx) {
      const dispatcher = /* @__PURE__ */ __name(function(type, init) {
        if (type === "scheduled" && worker.scheduled !== void 0) {
          const controller = new __Facade_ScheduledController__(
            Date.now(),
            init.cron ?? "",
            () => {
            }
          );
          return worker.scheduled(controller, env, ctx);
        }
      }, "dispatcher");
      return __facade_invoke__(request, env, ctx, dispatcher, fetchDispatcher);
    }
  };
}
__name(wrapExportedHandler, "wrapExportedHandler");
function wrapWorkerEntrypoint(klass) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__ === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__.length === 0) {
    return klass;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__) {
    __facade_register__(middleware);
  }
  return class extends klass {
    #fetchDispatcher = /* @__PURE__ */ __name((request, env, ctx) => {
      this.env = env;
      this.ctx = ctx;
      if (super.fetch === void 0) {
        throw new Error("Entrypoint class does not define a fetch() function.");
      }
      return super.fetch(request);
    }, "#fetchDispatcher");
    #dispatcher = /* @__PURE__ */ __name((type, init) => {
      if (type === "scheduled" && super.scheduled !== void 0) {
        const controller = new __Facade_ScheduledController__(
          Date.now(),
          init.cron ?? "",
          () => {
          }
        );
        return super.scheduled(controller);
      }
    }, "#dispatcher");
    fetch(request) {
      return __facade_invoke__(
        request,
        this.env,
        this.ctx,
        this.#dispatcher,
        this.#fetchDispatcher
      );
    }
  };
}
__name(wrapWorkerEntrypoint, "wrapWorkerEntrypoint");
var WRAPPED_ENTRY;
if (typeof middleware_insertion_facade_default === "object") {
  WRAPPED_ENTRY = wrapExportedHandler(middleware_insertion_facade_default);
} else if (typeof middleware_insertion_facade_default === "function") {
  WRAPPED_ENTRY = wrapWorkerEntrypoint(middleware_insertion_facade_default);
}
var middleware_loader_entry_default = WRAPPED_ENTRY;
export {
  DeviceHub,
  __INTERNAL_WRANGLER_MIDDLEWARE__,
  middleware_loader_entry_default as default
};
//# sourceMappingURL=worker.js.map
