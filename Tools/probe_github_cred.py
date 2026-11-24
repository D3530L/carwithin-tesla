"""Read the stored GitHub credential (username only in output) and report whether it works.

Prints no secret. Exit codes: 0 = credential found, 2 = none, 3 = API rejected it.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import sys
import urllib.error
import urllib.request

CRED_TYPE_GENERIC = 1


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ('Flags', wt.DWORD),
        ('Type', wt.DWORD),
        ('TargetName', wt.LPWSTR),
        ('Comment', wt.LPWSTR),
        ('LastWritten', wt.FILETIME),
        ('CredentialBlobSize', wt.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)),
        ('Persist', wt.DWORD),
        ('AttributeCount', wt.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wt.LPWSTR),
        ('UserName', wt.LPWSTR),
    ]


def read_credential(target: str) -> tuple[str, str] | None:
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    ptr = ctypes.c_void_p()
    if not advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        return None
    try:
        cred = ctypes.cast(ptr, ctypes.POINTER(CREDENTIAL)).contents
        size = cred.CredentialBlobSize
        raw = ctypes.string_at(cred.CredentialBlob, size) if size else b''
        secret = raw.decode('utf-16-le', 'replace').rstrip('\x00')
        return (cred.UserName or ''), secret
    finally:
        advapi.CredFree(ptr)


def main() -> int:
    for target in ('git:https://github.com', 'github.com'):
        found = read_credential(target)
        if not found:
            print(f'[{target}] 无凭据')
            continue
        user, secret = found
        print(f'[{target}] 用户名={user!r}  密钥长度={len(secret)}  前缀={secret[:4]!r}')
        if not secret:
            continue
        for scheme, header in (('token', f'token {secret}'), ('bearer', f'Bearer {secret}')):
            req = urllib.request.Request('https://api.github.com/user',
                                         headers={'Authorization': header,
                                                  'Accept': 'application/vnd.github+json',
                                                  'User-Agent': 'carwithin-port'})
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read())
                    print(f'  GitHub API OK ({scheme}): login={data.get("login")} id={data.get("id")}')
                    scopes = resp.headers.get('x-oauth-scopes')
                    print(f'  scopes: {scopes}')
                    return 0
            except urllib.error.HTTPError as exc:
                print(f'  {scheme} 被拒: HTTP {exc.code} {exc.reason}')
            except Exception as exc:
                print(f'  {scheme} 出错: {exc}')
    return 2


if __name__ == '__main__':
    sys.exit(main())
