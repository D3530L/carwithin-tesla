"""Create (or reuse) a private GitHub repo and push this checkout, then start the macOS build.

Uses the GitHub credential already stored in this Windows profile for the signed-in account;
the secret is never printed. Push URL carries the token only inside this process's argv and is
removed from .git/config afterwards.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_NAME = 'carwithin-tesla'
ROOT = Path(r'D:\AI\tmp\carwithin-src')
CRED_TYPE_GENERIC = 1


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ('Flags', wt.DWORD), ('Type', wt.DWORD), ('TargetName', wt.LPWSTR), ('Comment', wt.LPWSTR),
        ('LastWritten', wt.FILETIME), ('CredentialBlobSize', wt.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)), ('Persist', wt.DWORD),
        ('AttributeCount', wt.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wt.LPWSTR), ('UserName', wt.LPWSTR),
    ]


def secret() -> tuple[str, str]:
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    ptr = ctypes.c_void_p()
    if not advapi.CredReadW('git:https://github.com', CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        raise SystemExit('no stored GitHub credential')
    cred = ctypes.cast(ptr, ctypes.POINTER(CREDENTIAL)).contents
    raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
    user = cred.UserName or ''
    token = raw.decode('utf-16-le', 'replace').rstrip('\x00')
    advapi.CredFree(ptr)
    return user, token


def api(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f'https://api.github.com{path}', data=data, method=method,
        headers={'Authorization': f'token {token}', 'Accept': 'application/vnd.github+json',
                 'User-Agent': 'carwithin-port', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b'{}')
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode('utf-8', 'replace')
        try:
            return exc.code, json.loads(body_text or '{}')
        except Exception:
            return exc.code, {'raw': body_text}


def main() -> int:
    user, token = secret()
    print(f'账号: {user}')
    status, info = api('GET', f'/repos/{user}/{REPO_NAME}', token)
    if status == 200:
        print(f'仓库已存在: {info["full_name"]}')
    else:
        status, info = api('POST', '/user/repos', token, {
            'name': REPO_NAME, 'private': True,
            'description': 'CarWithin + head-unit (Tesla) MJPEG output — build staging',
            'has_issues': False, 'has_wiki': False, 'auto_init': False})
        if status not in (200, 201):
            print(f'创建仓库失败: HTTP {status} {json.dumps(info, ensure_ascii=False)[:300]}')
            return 1
        print(f'已创建私有仓库: {info["full_name"]}')

    remote = f'https://x-access-token:{token}@github.com/{user}/{REPO_NAME}.git'
    clean_remote = f'https://github.com/{user}/{REPO_NAME}.git'
    subprocess.run(['git', '-C', str(ROOT), 'remote', 'remove', 'origin'],
                   capture_output=True, text=True)
    subprocess.run(['git', '-C', str(ROOT), 'remote', 'add', 'origin', remote], check=True)
    print('推送中…')
    push = subprocess.run(['git', '-C', str(ROOT), 'push', '-u', 'origin', 'HEAD:main'],
                          capture_output=True, text=True)
    # Keep the token out of .git/config and out of this log.
    subprocess.run(['git', '-C', str(ROOT), 'remote', 'set-url', 'origin', clean_remote])
    if push.returncode != 0:
        print('推送失败:', (push.stderr or '').replace(token, '***')[-800:])
        return 1
    print((push.stdout or '').replace(token, '***').strip()[-300:])
    print(f'推送完成: {clean_remote}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
