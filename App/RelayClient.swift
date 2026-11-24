import Foundation

/// Dials out to the CarWithin relay Worker so a head unit can reach this iPhone without any
/// inbound access and without a private IP (Tesla's browser rejects RFC 1918 addresses).
///
/// Wire format matches `relay/worker.js`:
///   Worker -> device : JSON text  {t:"open"|"close"|"req"|"ws-open"|"ws-msg"|"ws-close", ...}
///   device -> Worker : JSON text  {t:"res"|"ws-msg"|"ws-close", ...}
///                      binary     [u32 big-endian requestId][JPEG bytes]
final class RelayClient {
    var onLog: ((String) -> Void)?
    /// Source id and normalised fingers, same contract as VideoOutputServer.onTouches.
    var onTouches: ((String, [TouchPoint]) -> Void)?
    /// Served for GET /tesla from a car browser.
    var pageHTML = Data()

    private let host: String
    private let key: String
    private let queue = DispatchQueue(label: "CarPlays.relay", qos: .utility)
    private var session: URLSession?
    private var task: URLSessionWebSocketTask?
    private var streams = Set<UInt32>()
    private var sockets = Set<UInt32>()
    private var retryDelay: TimeInterval = 1
    private var stopped = false
    private var lastFrameAt: TimeInterval = 0
    private var framesSent = 0
    private var droppedFrames = 0
    /// Bytes handed to the WebSocket but not yet written: JPEG must never queue up behind a slow
    /// cellular uplink, so frames are dropped instead of growing latency.
    private var pendingBytes = 0
    private let maximumPendingBytes = 1_500_000

    init(host: String, key: String) {
        self.host = host
        self.key = key
    }

    /// The address to type into the head unit's browser.
    var address: String { "https://\(host)/d/\(key)/tesla" }

    var isConnected: Bool { task?.state == .running }

    /// True while a car browser is attached through the relay (frame pump gate).
    var wantsFrames: Bool { !streams.isEmpty }

    func connect() {
        queue.async { [weak self] in self?.open() }
    }

    func stop() {
        queue.async { [weak self] in
            self?.stopped = true
            self?.task?.cancel(with: .goingAway, reason: nil)
            self?.task = nil
            self?.streams.removeAll()
            self?.sockets.removeAll()
        }
    }

    private func open() {
        guard !stopped, task == nil else { return }
        guard let url = URL(string: "wss://\(host)/d/\(key)/device") else {
            onLog?("中继地址无效：\(host)")
            return
        }
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = true
        config.timeoutIntervalForRequest = 30
        let session = URLSession(configuration: config)
        self.session = session
        let socket = session.webSocketTask(with: url)
        task = socket
        socket.resume()
        onLog?("中继已连接：\(address)")
        receive()
        schedulePing()
    }

    private func schedulePing() {
        queue.asyncAfter(deadline: .now() + 20) { [weak self] in
            guard let self, let socket = self.task else { return }
            socket.sendPing { error in
                if let error {
                    self.onLog?("中继心跳失败：\(error.localizedDescription)")
                    self.dropAndRetry()
                } else {
                    self.schedulePing()
                }
            }
        }
    }

    private func receive() {
        guard let socket = task else { return }
        socket.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let error):
                self.onLog?("中继断开：\(error.localizedDescription)")
                self.dropAndRetry()
            case .success(let message):
                switch message {
                case .string(let text): self.handle(text)
                case .data(let data): self.onLog?("中继收到意外的二进制 \(data.count) 字节")
                @unknown default: break
                }
                self.receive()
            }
        }
    }

    private func dropAndRetry() {
        queue.async { [weak self] in
            guard let self, !self.stopped else { return }
            self.task?.cancel(with: .goingAway, reason: nil)
            self.task = nil
            self.session?.invalidateAndCancel()
            self.session = nil
            self.streams.removeAll()
            self.sockets.removeAll()
            let delay = self.retryDelay
            self.retryDelay = min(self.retryDelay * 2, 30)
            self.onLog?("中继 \(Int(delay)) 秒后重连")
            self.queue.asyncAfter(deadline: .now() + delay) { self.open() }
        }
    }

    // MARK: inbound

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = object["type"] as? String ?? object["t"] as? String else { return }
        switch type {
        case "open":
            guard let id = uint32(object["id"]) else { return }
            queue.async {
                self.streams.insert(id)
                self.retryDelay = 1
                self.onLog?("车机开始拉流（#\(id)）")
            }
        case "close":
            guard let id = uint32(object["id"]) else { return }
            queue.async { self.streams.remove(id) }
        case "req":
            guard let id = uint32(object["id"]), let path = object["path"] as? String else { return }
            respond(id: id, path: path)
        case "ws-open":
            guard let id = uint32(object["id"]) else { return }
            queue.async { self.sockets.insert(id) }
        case "ws-msg":
            guard let id = uint32(object["id"]), let payload = object["data"] as? String else { return }
            handleTouchPayload("relay-\(id)", payload)
        case "ws-close":
            guard let id = uint32(object["id"]) else { return }
            queue.async { self.sockets.remove(id) }
        default:
            break
        }
    }

    private func handleTouchPayload(_ source: String, _ payload: String) {
        guard let data = payload.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = object["type"] as? String else { return }
        if type == "touches" {
            guard let list = object["points"] as? [[String: Any]] else { return }
            let points: [TouchPoint] = list.compactMap { item in
                guard let id = (item["id"] as? NSNumber)?.intValue,
                      let x = (item["x"] as? NSNumber)?.doubleValue,
                      let y = (item["y"] as? NSNumber)?.doubleValue,
                      (0...255).contains(id), (0...1).contains(x), (0...1).contains(y) else { return nil }
                return TouchPoint(id: id, x: x, y: y)
            }
            onTouches?(source, points)
        } else if type == "info" {
            if let text = object["text"] as? String { onLog?("车机：\(text.prefix(200))") }
        }
    }

    private func respond(id: UInt32, path: String) {
        let page = path.hasPrefix("/tesla") || path.hasPrefix("/headunit") || path == "/"
        guard page, !pageHTML.isEmpty else {
            sendText(["t": "res", "id": Int(id), "status": 404,
                      "contentType": "text/plain; charset=utf-8", "body": "not via relay"])
            return
        }
        sendText(["t": "res", "id": Int(id), "status": 200,
                  "contentType": "text/html; charset=utf-8",
                  "body": String(decoding: pageHTML, as: UTF8.self)])
    }

    // MARK: outbound

    /// Called for every encoded JPEG; drops frames when no car is attached or the uplink lags.
    func send(jpeg: Data) {
        queue.async { [weak self] in
            guard let self, let socket = self.task, !self.streams.isEmpty else { return }
            guard self.pendingBytes < self.maximumPendingBytes else {
                self.droppedFrames += 1
                if self.droppedFrames % 50 == 1 {
                    self.onLog?("中继上行跟不上，已丢 \(self.droppedFrames) 帧")
                }
                return
            }
            self.lastFrameAt = ProcessInfo.processInfo.systemUptime
            self.framesSent += 1
            let ids = self.streams
            for id in ids {
                var frame = Data(capacity: jpeg.count + 4)
                frame.append(UInt8((id >> 24) & 0xff)); frame.append(UInt8((id >> 16) & 0xff))
                frame.append(UInt8((id >> 8) & 0xff)); frame.append(UInt8(id & 0xff))
                frame.append(jpeg)
                let size = frame.count
                self.pendingBytes += size
                socket.send(.data(frame)) { [weak self] error in
                    self?.queue.async { self?.pendingBytes -= size }
                    if let error { self?.onLog?("中继发送失败：\(error.localizedDescription)") }
                }
            }
        }
    }

    private func sendText(_ object: [String: Any]) {
        guard let socket = task, JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8) else { return }
        socket.send(.string(text)) { [weak self] error in
            if let error { self?.onLog?("中继回包失败：\(error.localizedDescription)") }
        }
    }

    private func uint32(_ value: Any?) -> UInt32? {
        if let n = value as? NSNumber { return UInt32(truncatingIfNeeded: n.intValue) }
        if let s = value as? String { return UInt32(s) }
        return nil
    }
}
