import asyncio, io, json, struct, threading, time, urllib.request
import websockets
from PIL import Image

HOST = 'carwithin-relay.poki-yg.workers.dev'
KEY = 'probe' + 'a1b2c3d4'
PROXY = 'http://127.0.0.1:7890'

def jpeg(colour):
    buf = io.BytesIO(); Image.new('RGB', (320, 180), colour).save(buf, 'JPEG', quality=70); return buf.getvalue()

seen = {}

async def device():
    async with websockets.connect(f'wss://{HOST}/d/{KEY}/device', proxy=PROXY,
                                  open_timeout=25, ping_interval=None) as ws:
        seen['device_connected'] = True
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=25)
            except asyncio.TimeoutError:
                return
            if isinstance(raw, str):
                m = json.loads(raw); seen.setdefault('msgs', []).append(m.get('t'))
                if m['t'] == 'open':
                    for i in range(4):
                        await ws.send(struct.pack('>I', m['id']) + jpeg((i*40, 100, 180)))
                        await asyncio.sleep(0.05)
                elif m['t'] == 'req':
                    await ws.send(json.dumps({'t':'res','id':m['id'],'status':200,
                        'contentType':'text/html; charset=utf-8','body':'<html>tesla-prod</html>'}))
            else:
                pass

def browser():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
    try:
        with opener.open(f'https://{HOST}/d/{KEY}/tesla', timeout=30) as r:
            seen['page'] = (r.status, r.read()[:40].decode('utf-8','replace'))
    except Exception as e:
        seen['page_err'] = repr(e)
    try:
        with opener.open(f'https://{HOST}/d/{KEY}/mjpeg', timeout=25) as r:
            data = b''; end = time.time() + 6
            while time.time() < end:
                chunk = r.read(4096)
                if not chunk: break
                data += chunk
                if data.count(b'--frame') >= 2: break
            seen['stream'] = (r.headers.get('content-type',''), data.count(b'--frame'), b'\xff\xd8' in data)
    except Exception as e:
        seen['stream_err'] = repr(e)

async def main():
    t = asyncio.create_task(device()); await asyncio.sleep(2)
    threading.Thread(target=browser, daemon=True).start()
    await asyncio.sleep(12)
    t.cancel()
    print(json.dumps(seen, ensure_ascii=False, default=str)[:900])

asyncio.run(main())
