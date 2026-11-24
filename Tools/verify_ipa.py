"""Verify the desktop IPA carries the relay-path fix and the new routes."""
import hashlib
import zipfile
from pathlib import Path

IPA = Path(r'C:\Users\Fujitsu\Desktop\CarWithin-1.0.4-tesla-unsigned.ipa')

probes = [
    b"base+'mjpeg?t='",
    b"location.host+base+'stream?headunit=1'",
    b"replace(/[^/]*$/,'')",
    b'/d/<key>/tesla',
    b'multipart/x-mixed-replace',
    'CarWithin · 车机模式'.encode(),
    b'carwithin-relay.poki-yg.workers.dev',
]

data = IPA.read_bytes()
print('文件:', IPA, len(data), '字节')
print('SHA256:', hashlib.sha256(data).hexdigest().upper())

with zipfile.ZipFile(IPA) as z:
    names = z.namelist()
    exe = [n for n in names if n.endswith('.app/TDSCarKit')][0]
    binary = z.read(exe)
    for probe in probes:
        print(f'  {probe[:46]!r:50} -> {probe in binary}')
    print('  文件数:', len(names))
    print('  身份文件:', [n.split("/")[-1] for n in names if 'BundledIdentity' in n] or '在 app 根目录')
    print('  app 根:', sorted({n.split('/')[-1] for n in names if n.count('/') == 2})[:14])
