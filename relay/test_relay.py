"""End-to-end test of the relay Worker against `wrangler dev` (local).

Simulates the iPhone (device WebSocket) and the car browser (HTTP MJPEG + touch WebSocket).
"""
from __future__ import annotations

import asyncio
import io
import json
import struct
import threading
import time
import urllib.request

import websockets
from PIL import Image

BASE = 'http://127.0.0.1:8787'
WS = 'ws://127.0.0.1:8787'
KEY = 'testkey123'


def jpeg(colour: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (320, 180), colour).save(buf, 'JPEG', quality=70)
    return buf.getvalue()


received: dict[str, object] = {}


async def device() -> None:
    async with websockets.connect(f'{WS}/d/{KEY}/device') as ws:
        received['device_connected'] = True
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
            except asyncio.TimeoutError:
                return
            if isinstance(raw, str):
                msg = json.loads(raw)
                received.setdefault('device_msgs', []).append(msg)
                if msg['t'] == 'open':
                    for i in range(5):
                        await ws.send(struct.pack('>I', msg['id']) + jpeg((10 * i, 120, 200)))
                        await asyncio.sleep(0.05)
                elif msg['t'] == 'req':
                    if msg['path'] == '/tesla':
                        await ws.send(json.dumps({'t': 'res', 'id': msg['id'], 'status': 200,
                                                  'contentType': 'text/html; charset=utf-8',
                                                  'body': '<html>tesla</html>'}))
                elif msg['t'] == 'ws-msg':
                    received.setdefault('touch', []).append(msg['data'])
            else:
                received.setdefault('binary_in', 0)
                received['binary_in'] = int(received.get('binary_in', 0)) + 1


def browser_stream() -> None:
    try:
        with urllib.request.urlopen(f'{BASE}/d/{KEY}/mjpeg', timeout=15) as resp:
            received['stream_type'] = resp.headers.get('content-type', '')
            data = b''
            deadline = time.time() + 5
            while time.time() < deadline:
                chunk = resp.read(4096)
                if not chunk:
                    break
                data += chunk
                if data.count(b'--frame') >= 3:
                    break
            received['stream_bytes'] = len(data)
            received['frames'] = data.count(b'--frame')
            received['has_jpeg'] = b'\xff\xd8' in data and b'\xff\xd9' in data
    except Exception as exc:  # noqa: BLE001
        received['stream_error'] = repr(exc)


def browser_page() -> None:
    try:
        with urllib.request.urlopen(f'{BASE}/d/{KEY}/tesla', timeout=10) as resp:
            received['page_status'] = resp.status
            received['page_body'] = resp.read()[:64].decode('utf-8', 'replace')
    except Exception as exc:  # noqa: BLE001
        received['page_error'] = repr(exc)


async def main() -> int:
    task = asyncio.create_task(device())
    await asyncio.sleep(1.2)  # let the device register

    threading.Thread(target=browser_page, daemon=True).start()
    threading.Thread(target=browser_stream, daemon=True).start()
    await asyncio.sleep(4)

    # Touch channel: browser -> device
    try:
        async with websockets.connect(f'{WS}/d/{KEY}/stream') as car:
            await asyncio.sleep(0.4)
            await car.send(json.dumps({'type': 'touches', 'points': [{'id': 1, 'x': 0.5, 'y': 0.5}]}))
            await asyncio.sleep(0.6)
    except Exception as exc:  # noqa: BLE001
        received['ws_error'] = repr(exc)

    await asyncio.sleep(1)
    task.cancel()

    print('=== 结果 ===')
    for k in sorted(received):
        v = received[k]
        if k in ('device_msgs',):
            print(f'{k}: {json.dumps(v, ensure_ascii=False)[:300]}')
        else:
            print(f'{k}: {v}')

    ok = (received.get('device_connected') and received.get('frames', 0) >= 2
          and received.get('has_jpeg') and received.get('page_status') == 200
          and received.get('touch'))
    print('\n判定:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
