"""Hold a fake iPhone connection to the production relay so curl can verify the car side."""
from __future__ import annotations

import asyncio
import io
import json
import struct
import sys

import websockets
from PIL import Image

HOST = 'carwithin-relay.poki-yg.workers.dev'
KEY = sys.argv[1] if len(sys.argv) > 1 else 'probea1b2c3d4'
PROXY = 'http://127.0.0.1:7890'
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 45


def jpeg(colour: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (640, 360), colour).save(buf, 'JPEG', quality=70)
    return buf.getvalue()


async def main() -> int:
    print(f'连接到 wss://{HOST}/d/{KEY}/device', flush=True)
    async with websockets.connect(f'wss://{HOST}/d/{KEY}/device', proxy=PROXY,
                                  open_timeout=25, ping_interval=None) as ws:
        print('已连接', flush=True)
        deadline = asyncio.get_running_loop().time() + SECONDS
        i = 0
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, deadline - asyncio.get_running_loop().time()))
            except asyncio.TimeoutError:
                break
            if isinstance(raw, str):
                msg = json.loads(raw)
                kind = msg.get('t')
                print('收到', kind, msg.get('path', ''), flush=True)
                if kind == 'open':
                    for _ in range(60):
                        i += 1
                        await ws.send(struct.pack('>I', msg['id']) + jpeg((i * 5 % 255, 120, 200)))
                        await asyncio.sleep(0.1)
                elif kind == 'req':
                    body = ('<html><body><h1>carwithin relay OK</h1>'
                            f'<p>path={msg.get("path")}</p></body></html>')
                    await ws.send(json.dumps({'t': 'res', 'id': msg['id'], 'status': 200,
                                              'contentType': 'text/html; charset=utf-8',
                                              'body': body}))
                elif kind == 'ws-msg':
                    print('触控数据:', msg.get('data', '')[:120], flush=True)
            else:
                print('浏览器断开/关闭', flush=True)
    print('结束', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
