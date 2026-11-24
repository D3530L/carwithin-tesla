# 特斯拉车机投屏：交付说明（CarWithin 1.0.4 派生）

更新：2026-11-25

## 1. 为什么原生 CarWithin 在特斯拉上不行

特斯拉浏览器拒绝一切 RFC 1918 地址（`10/8`、`172.16/12`、`192.168/16`），用域名指向私网也拒绝，且不走 IPv6。
iPhone 个人热点固定 `172.20.10.0/28` 且不可修改 → 车机连热点后直连必然失败，与解码能力无关。

同类上架 App（Tesmirror）的做法是**云中转**：`ios.tesmirror.com → 47.104.111.183`（阿里云），8888 端口开放。
本仓库按同一思路实现了自托管版本。

## 2. 交付物

| 产物 | 位置 | 说明 |
|---|---|---|
| unsigned IPA | `C:\Users\Fujitsu\Desktop\CarWithin-1.0.4-tesla-unsigned.ipa` | 3,043,993 B，SHA256 `FE4F0CC4482AD91303F92F47181F99E0156DCE131F252C91D85E21A5E7C62D11` |
| 构建 | GitHub Actions `#8 success`（macOS-15 / Xcode 26.3） | 仓库 main = `703ca6a` |
| 中继 Worker | `https://carwithin-relay.poki-yg.workers.dev` | Durable Object `DeviceHub`，版本 `df48fbd0` |
| 源码仓库 | `https://github.com/D3530L/carwithin-tesla` | public，随时可切回 private |

## 3. 改动清单

| 文件 | 作用 |
|---|---|
| `App/MJPEGTranscoder.swift` | H.264/H.265 → VideoToolbox 解码 → JPEG；默认 12 fps、宽 ≤1024、质量 0.5；关键帧不受限流影响 |
| `App/TeslaReceiverPage.swift` | ES5 车机页：`<img src=base+'mjpeg'>` 收流，`WebSocket(base+'stream?headunit=1')` 回传触控；路径按页面目录解析，直连与中继通用 |
| `App/RelayClient.swift` | 出站 WSS 连 Worker；收 `open/close/req/ws-*`，发 `[u32 id][jpeg]` 与 `res/ws-msg`；1.5 MB 背压丢帧；1→30 s 退避重连；20 s ping |
| `App/VideoOutputServer.swift` | `/mjpeg`、`/tesla` 路由；`broadcastMJPEG` 同时喂本地与中继；`headunit=1` 不抢主浏览器分辨率；MJPEG 参数可被 UserDefaults 覆盖 |
| `App/BrowserReceiverPage.swift` | 无 MSE 且无 WebCodecs → `location.replace('/tesla')` |
| `App/Info.plist` | `CarWithinRelayHost = carwithin-relay.poki-yg.workers.dev` |
| `.github/workflows/build-ios-unsigned.yml` | macOS 出 unsigned IPA；从官方 IPA 取 MFi 身份文件（不入仓库） |
| `relay/worker.js` | 设备 WSS 接入 + 车机 HTTP/WS 转发（Durable Object 单实例按 deviceKey 分片） |
| `Tools/check_embedded_js.py` | 本地提取 Swift 内嵌 HTML、按 Swift 规则反转义、`node --check` 验 JS（避免烧构建次数） |
| `Tools/push_retry.py` / `Tools/poll_build.py` / `Tools/fetch_build_log.py` | 推送重试、构建轮询+产物落地、失败日志抓取 |

## 4. 验证记录

**本地（wrangler dev + 模拟设备/车机）**

```
device_connected: True
stream_type: multipart/x-mixed-replace; boundary=frame   frames: 3
page_status: 200        touch: [{"id":1,"x":0.5,"y":0.5}] 回传到设备
判定: PASS
```

**生产 Worker**

```
GET /health                                  → 200 {"ok":true,"service":"carwithin-relay"}
设备离线 GET /d/<key>/tesla                  → 503 {"error":"device offline"}
设备在线 GET /d/<key>/tesla                  → 200 <html>…</html>
设备在线 GET /d/<key>/mjpeg                  → 4 秒 144,180 B / 33 帧 multipart
```

**MJPEG 转码桥（不需要重构 app 的临时方案，`tesla-probe/mjpeg_bridge.py`）**

拉 `http://<iPhone>:9888/video.h264` → ffmpeg → MJPEG：6 秒 135 帧，1280×720，42.5 KB/帧，首帧 PIL 可解码。

**IPA 内字符串核验**（全部命中）：`base+'mjpeg?t='`、`location.host+base+'stream?headunit=1'`、`replace(/[^/]*$/,'')`、`multipart/x-mixed-replace`、`CarWithin · 车机模式`、`carwithin.mjpegFPS`、`中继上行跟不上`。

## 5. 使用

1. 用 `M46ZQ47MG8`（Sinan Candemir）那张证书签名桌面 IPA 并安装；桌面文件未签名
2. 打开 CarWithin → 启动 CarPlay，日志里找：`中继：https://carwithin-relay.poki-yg.workers.dev/d/<16位密钥>/tesla`
3. 车机连 iPhone 热点（或任意有网 Wi-Fi），**P 挡驻车**，浏览器打开该地址

调参（UserDefaults，改后重启 CarPlay）：`carwithin.mjpegFPS`、`carwithin.mjpegWidth`、`carwithin.mjpegQuality`。

## 6. 排错对照

| 车机页显示 | 含义 | 处理 |
|---|---|---|
| `正在连接 CarWithin…` 一直不消失 | HTML 到了但 MJPEG 没到 | 看 iPhone 日志有没有“车机开始拉流”；没有则是 `/mjpeg` 没命中 |
| `画面 ?×? · 0 fps` | `<img>` 没收到帧 | Worker 到设备的链路断，或 MJPEG 编码器没启动 |
| `画面 1024×576 · 0.3 fps` | 上行带宽不够 | 降 `mjpegWidth` 到 800、`mjpegFPS` 到 8 |
| `画面 … · 触控 未连接` | WebSocket 未通 | 检查 Worker 的 `/d/<key>/stream` 是否 101 |
| 一直转圈无响应 | 域名/网络到 Worker 不通 | 车机需能访问 `*.workers.dev`（可用 `cw.poki-yg.workers.dev` 探活） |

## 7. 未完成

- **实车验证**：特斯拉浏览器打开中继地址，确认画面与触控（本轮无车机接入记录）
- 若要走纯局域网（不经公网），需要把 LAN 网段改到 `100.64.0.0/10`：特斯拉黑名单只含 RFC 1918，DashPlay 的特斯拉模式正是给接收端 `100.96.0.1`
