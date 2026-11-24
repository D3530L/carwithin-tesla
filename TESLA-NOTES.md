# 特斯拉车机投屏：限制与可行路线（CarWithin 适配笔记）

更新：2026-11-25

## 1. 特斯拉浏览器到底拦什么

固件黑名单是 RFC 1918 三段：`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`。
表现为「无法访问 / 被拦截」，与证书、DNS、端口无关。

证据：

- SideDisplay 作者（HN）：*Tesla's browser blocks all RFC 1918 private IP ranges…workaround was configuring the bridge interface to assign public IP addresses*
- TFF 论坛：即使路由器把域名 DNS 重写到内网 IP，照样连不上
- DashPlay 文档：「特斯拉：浏览器拒绝任何局域网地址，**用名称也不行**，也不走 IPv6」

**关键推论**：`100.64.0.0/10`（CGNAT 段）不属于 RFC 1918，不在黑名单内。
DashPlay 的「特斯拉模式」正是用它：`特斯拉用设置页显示的共享地址（默认 100.96.0.1）`。
2026-10-15 斐讯 N1 + 特斯拉实车通过（有线/无线均出画）。

## 2. DashPlay 的完整做法（供对照）

| 手段 | 说明 |
|---|---|
| 特斯拉模式 | 给接收端一个 `100.96.0.1` 形式的 CGNAT 地址，车机访问它而不是 192.168.x |
| 自己的域名 | DuckDNS 子域名 + Let's Encrypt 正式证书（DNS-01），车机按 HTTPS 访问 |
| HTTP 兼容方式（实验） | 无需域名/证书，**优先 WebRTC，连接失败时改用 JPEG 图片** |
| 公网 IPv6 | 部分车机可用；特斯拉明确不走 IPv6 |

## 3. CarWithin 的现象与差距

CarWithin 的接收页只有两条解码路径（`App/BrowserReceiverPage.swift`）：

- HTTPS + WebCodecs（低延迟）
- HTTP + MediaSource（fMP4 over WebSocket）

两条都不满足时报「此浏览器缺少兼容播放器」。特斯拉既无 MSE 也无 WebCodecs → 必黑屏。
网络侧 CarWithin 支持 HTTP/HTTPS + 本地 IP / sslip.io / DuckDNS，但都在 RFC 1918 范围内 → 特斯拉一律拒绝。

## 4. 本次适配的改动（源码已落地）

| 文件 | 改动 |
|---|---|
| `App/MJPEGTranscoder.swift` | 新增：H.264/H.265 → VideoToolbox 解码 → JPEG，15 fps、宽 ≤1280、质量 0.55 |
| `App/TeslaReceiverPage.swift` | 新增：ES5 车机页，`<img src="/mjpeg">` 收流，触控走原 WebSocket 协议 |
| `App/VideoOutputServer.swift` | 新增 `/mjpeg`、`/tesla` 路由与 MJPEG 广播；积压 >1.5 MB 丢帧不排队 |
| `App/BrowserReceiverPage.swift` | 无 MSE/WebCodecs 时自动 `location.replace('/tesla')` |
| `.github/workflows/build-ios-unsigned.yml` | 新增：macOS runner 出 unsigned IPA（无需证书） |

## 5. 网络路径的三条选择

1. **把 Wi-Fi 网段改成 `100.64.0.0/10`**（如 `100.96.0.0/24`）：路由器 DHCP 改网段，iPhone 与车机都在此段，车机访问 `http://100.96.0.x:9888/` → 不在黑名单，直连、不经外网、不耗流量。需要路由器可自定义 DHCP 网段。
2. **Cloudflare 隧道**：`cloudflared tunnel --url http://<iPhone IP>:9888`，车机访问 `https://xxx.trycloudflare.com`。已验证国内直连可达（200）；代价是依赖电脑、流量绕公网。
3. **外部小盒子**（DashPlay 路线）：OpenWrt/随身 Wi-Fi 开热点并自定义网段，iPhone 与车机都连它。

## 6. 待验证

- 特斯拉浏览器对 `/tesla` 页面的实测（MJPEG `<img>` 流、WebSocket 触控）
- 100.64 网段实车可达性（需路由器改 DHCP 网段）
