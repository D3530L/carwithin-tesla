"""Extract the embedded HTML/JS from a Swift file, apply Swift escaping, and syntax-check the JS.

Catches what the macOS build would only tell us minutes later: invalid escape sequences reach the
compiler, and a broken JS string only shows up in the car.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

SWIFT_ESCAPES = {
    '\\\\': '\\', '\\n': '\n', '\\t': '\t', '\\"': '"', "\\'": "'", '\\0': '\0',
}


def swift_unescape(text: str) -> str:
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            pair = text[i:i + 2]
            if pair in SWIFT_ESCAPES:
                out.append(SWIFT_ESCAPES[pair])
                i += 2
                continue
            # \( interpolation and unknown escapes are left visible so we notice them.
            out.append(pair)
            i += 2
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def check(path: Path) -> int:
    source = path.read_text(encoding='utf-8')
    bad_escapes = [m.group(0) for m in re.finditer(r'\\[^nrt"\'\\0(]', source)]
    if bad_escapes:
        print(f'{path.name}: 可疑转义 {sorted(set(bad_escapes))}')

    blocks = re.findall(r'"""(.*?)"""', source, re.S)
    if not blocks:
        print(f'{path.name}: 没找到多行字符串')
        return 1
    html = swift_unescape(blocks[0])
    scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
    if not scripts:
        print(f'{path.name}: 没有 <script>')
        return 1
    tmp = Path(tempfile.gettempdir()) / (path.stem + '.check.js')
    tmp.write_text('\n'.join(scripts), encoding='utf-8')
    node = subprocess.run(['node', '--check', str(tmp)], capture_output=True, text=True)
    status = 'OK' if node.returncode == 0 else 'FAIL'
    print(f'{path.name}: JS 语法 {status}  ({len(html)} 字符 HTML, {len(scripts)} 段 script)')
    if node.returncode != 0:
        print(node.stderr.strip()[:1200])
    return node.returncode


if __name__ == '__main__':
    files = [Path(p) for p in (sys.argv[1:] or ['App/TeslaReceiverPage.swift'])]
    worst = 0
    for f in files:
        worst |= check(f)
    raise SystemExit(worst)
