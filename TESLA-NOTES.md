# 特斯拉车机投屏：状态与实现（CarWithin 1.0.4 派生）

更新：2026-11-25

## 1. 结论先说

- **特斯拉浏览器拒绝一切 RFC 1918 地址**（10/8、172.16/12、192.168/16），用域名指向私网也拒绝，且不走 IPv6。因此手机热点（172.20.10.x）直连必然失败。
- 可行路线只有两条：**(a)** 让接收端落在 `100.64.0.0/10`（CGNAT，不在黑名单）；**(b)** 走公网中继，车机只看到公网 HTTPS 域名。
- 上架同类 App（Tesmirror）用的是 **(b)**：`ios.tesmirror.com → 47.104.111.183`（阿里云），8888 端口开放，是云中转而非虚拟 IP。
- 本仓库已实现 **(b)** 并在生产验证；**(a)** 需要路由器/盒子把 DHCP 网段改成 100.64.x（DashPlay 的做法）。

## 2. 已交付

| 产物 | 位置 | 说明 |
|---|---|---|
| unsigned IPA | `C:\Users\Fujitsu\Desktop\CarWithin-1.0.4-tesla-unsigned.ipa` | 3,042,839 B，SHA256 `045B52EC…01B4B5`，由 GitHub Actions #4 构建（macOS-15 / Xcode 26.3） |
| 中继 Worker | `https://carwithin-relay.poki-yg.workers.dev` | Version `df48fbd0`，Durable Object `DeviceHub` |
| 源码仓库 | `https://github.com/D3530L/carwithin-tesla` | public；分支 `main` |

## 3. 客户端改动（相对官方 1.0.4）

| 文件 | 作用 |
|---|---|
| `App/MJPEGTranscoder.swift` | H.264/H.265 → VideoToolbox 解码 → JPEG；15 fps、宽 ≤1280、质量 0.55；关键帧不因限流丢弃 |
| `App/TeslaReceiverPage.swift` | ES5 车机页：`<img src="/mjpeg">` 收流，WebSocket(`?headunit=1`) 回传触控 |
| `App/RelayClient.swift` | 出站 WSS 连 Worker；收 `open/close/req/ws-*`，发 `[u32 id][jpeg]` 与 `res/ws-msg`；自动重连与心跳 |
| `App/VideoOutputServer.swift` | 新增 `/mjpeg`、`/tesla` 路由；`broadcastMJPEG` 同时喂中继；`start/stop` 挂载中继；`headunit=1` 不抢主浏览器分辨率 |
| `App/BrowserReceiverPage.swift` | 无 MSE 且无 WebCodecs → `location.replace('/tesla')` |
| `App/Info.plist` | `CarWithinRelayHost = carwithin-relay.poki-yg.workers.dev` |
| `.github/workflows/build-ios-unsigned.yml` | macOS 构建 unsigned IPA；从官方 IPA 取 MFi 身份文件（不入仓库） |

## 4. 验证记录

本地（wrangler dev + 模拟设备/车机）：

```
device_connected: True
stream_type: multipart/x-mixed-replace; boundary=frame   frames: 3
page_status: 200        touch: [{id:1,x:0.5,y:0.5}] 回传到设备
判定: PASS
```

生产（真实 Worker + 真实 WSS 出口 + HTTP 取流）：

```
/health → 200 {"ok":true}
设备不在线时 /d/<key>/tesla → 503 {"error":"device offline"}
设备在线时 /d/<key>/tesla → 200 <html>carwithin relay OK</html>
设备在线时 /d/<key>/mjpeg → 4 秒 144,180 字节 / 33 帧 multipart
```

MJPEG 桥（不需要重编译的临时方案，`tesla-probe/mjpeg_bridge.py`）：
拉 `http://<iPhone>:9888/video.h264` → ffmpeg → MJPEG，6 秒 135 帧、1280×720、42.5 KB/帧，首帧 PIL 可解码。

## 5. 车机侧用法

1. 装 IPA（自行签名），手机上打开 CarWithin 启动 CarPlay
2. app 日志里找：`中继：https://carwithin-relay.poki-yg.workers.dev/d/<16位密钥>/tesla`
3. 车机连 iPhone 热点（或任意能上网的 Wi-Fi），P 挡驻车，浏览器打开该地址

## 6. 未完成 / 待实测

- **实车验证**：特斯拉浏览器打开中继地址，确认画面与触控（本轮无车机接入记录）
- MJPEG 在车机上的实际帧率与蜂窝上行是否够（预计 720p/8–15 fps 需 2–4 Mbps）
- 若要把网络彻底本地化（不经公网），需把 LAN 网段改到 `100.64.0.0/10`
