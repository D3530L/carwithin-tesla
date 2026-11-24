"""Push HEAD to main with retries (the connection drops intermittently here)."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from push_to_github import api, secret  # noqa: E402

ROOT = r'D:\AI\tmp\carwithin-src'


def main() -> int:
    user, token = secret()
    url = f'https://{user}:{token}@github.com/{user}/carwithin-tesla.git'
    clean = f'https://github.com/{user}/carwithin-tesla.git'
    subprocess.run(['git', '-C', ROOT, 'remote', 'set-url', 'origin', url], check=True)
    ok = False
    for attempt in range(1, 5):
        result = subprocess.run(['git', '-C', ROOT, 'push', 'origin', 'HEAD:main'],
                                capture_output=True, text=True)
        tail = ((result.stdout or '') + (result.stderr or '')).replace(token, '***').strip()[-160:]
        print(f'attempt {attempt}: rc={result.returncode} {tail}')
        if result.returncode == 0:
            ok = True
            break
        time.sleep(4)
    subprocess.run(['git', '-C', ROOT, 'remote', 'set-url', 'origin', clean], check=True)
    if not ok:
        return 1
    head = subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()
    status, branch = api('GET', f'/repos/{user}/carwithin-tesla/branches/main', token)
    remote = branch.get('commit', {}).get('sha', '')
    print(f'local={head[:12]} remote={remote[:12]} match={head == remote}')
    return 0 if head == remote else 1


if __name__ == '__main__':
    raise SystemExit(main())
