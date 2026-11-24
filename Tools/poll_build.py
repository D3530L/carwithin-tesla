"""Poll the GitHub Actions build, then download and unpack the unsigned IPA.

Prints progress only; the token stays in memory. Writes the IPA to D:\\AI\\builds\\carwithin\\.
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from push_to_github import api, secret  # noqa: E402

OUT = Path(r'D:\AI\builds\carwithin')
MAX_WAIT = 40 * 60


def main() -> int:
    user, token = secret()
    repo = f'{user}/carwithin-tesla'
    deadline = time.time() + MAX_WAIT
    run = None
    while time.time() < deadline:
        status, data = api('GET', f'/repos/{repo}/actions/runs?per_page=3', token)
        runs = data.get('workflow_runs', []) if status == 200 else []
        if not runs:
            print(f'[{time.strftime("%H:%M:%S")}] 还没有 run…', flush=True)
            time.sleep(20)
            continue
        run = runs[0]
        print(f"[{time.strftime('%H:%M:%S')}] #{run['run_number']} status={run['status']} conclusion={run['conclusion']}",
              flush=True)
        if run['status'] == 'completed':
            break
        time.sleep(30)

    if run is None or run['status'] != 'completed':
        print('等待超时，构建可能仍在跑')
        return 1
    if run['conclusion'] != 'success':
        print(f"构建失败: {run['conclusion']}")
        # Pull the job log tail so the failure is actionable.
        st, jobs = api('GET', f"/repos/{repo}/actions/runs/{run['id']}/jobs", token)
        for job in jobs.get('jobs', []):
            print(f"  job {job['name']}: {job['conclusion']}")
            for step in job.get('steps', []):
                if step.get('conclusion') not in ('success', 'skipped', None):
                    print(f"    失败步骤: {step['name']} -> {step['conclusion']}")
        print(f"  日志: {run['html_url']}")
        return 2

    status, artifacts = api('GET', f"/repos/{repo}/actions/runs/{run['id']}/artifacts", token)
    items = artifacts.get('artifacts', [])
    if not items:
        print('构建成功但没有 artifact')
        return 3
    OUT.mkdir(parents=True, exist_ok=True)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    for art in items:
        print(f"下载 artifact: {art['name']} ({art['size_in_bytes']} 字节)")
        req = urllib.request.Request(art['archive_download_url'],
                                     headers={'Authorization': f'token {token}',
                                              'User-Agent': 'carwithin-port'})
        try:
            with opener.open(req, timeout=60) as resp:
                blob = resp.read()
        except urllib.error.HTTPError as exc:
            location = exc.headers.get('Location')
            if exc.code not in (301, 302, 303, 307, 308) or not location:
                raise
            with urllib.request.urlopen(
                    urllib.request.Request(location, headers={'User-Agent': 'carwithin-port'}),
                    timeout=180) as resp:
                blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                target = OUT / Path(name).name
                target.write_bytes(z.read(name))
                print(f'  解出 {target} ({target.stat().st_size} 字节)')
    import shutil
    desktop = Path.home() / 'Desktop'
    for ipa in OUT.glob('CarWithin-unsigned.ipa'):
        print(f'IPA 就绪: {ipa}')
        if desktop.is_dir():
            dest = desktop / 'CarWithin-1.0.4-tesla-unsigned.ipa'
            shutil.copy2(ipa, dest)
            print(f'已放到桌面: {dest} ({dest.stat().st_size} 字节)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
