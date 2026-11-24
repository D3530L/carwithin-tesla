"""Fetch the failing Actions job log and print the compiler errors."""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from push_to_github import api, secret  # noqa: E402


def main() -> int:
    user, token = secret()
    repo = f'{user}/carwithin-tesla'
    status, runs = api('GET', f'/repos/{repo}/actions/runs?per_page=3', token)
    run = runs['workflow_runs'][0]
    print(f"run #{run['run_number']} {run['status']} {run['conclusion']}")
    status, jobs = api('GET', f"/repos/{repo}/actions/runs/{run['id']}/jobs", token)
    job = jobs['jobs'][0]
    print(f"job: {job['name']} {job['conclusion']} id={job['id']}")

    url = f"https://api.github.com/repos/{repo}/actions/jobs/{job['id']}/logs"
    req = urllib.request.Request(url, headers={
        'Authorization': f'token {token}', 'User-Agent': 'carwithin-port',
        'Accept': 'application/vnd.github+json'})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        location = exc.headers.get('Location')
        if exc.code not in (301, 302, 303, 307, 308) or not location:
            raise
        # The storage host rejects the GitHub token, so follow the redirect without it.
        with urllib.request.urlopen(
                urllib.request.Request(location, headers={'User-Agent': 'carwithin-port'}),
                timeout=120) as resp:
            raw = resp.read()
    text = raw.decode('utf-8', 'replace')
    if text.lstrip().startswith('PK'):
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            text = '\n'.join(z.read(n).decode('utf-8', 'replace') for n in z.namelist())
    print(f'日志 {len(text)} 字符')

    lines = text.splitlines()
    interesting = [ln for ln in lines
                   if re.search(r'error:|warning: .*deprecat|The following build commands failed|'
                                r'failed with a nonzero exit|Command line invocation|'
                                r'note: Building targets', ln)]
    head = [ln for ln in lines if 'xcodebuild -project' in ln or 'xcode-select' in ln or 'Xcode ' in ln][:6]
    for ln in head:
        print('LOG>', ln.strip()[:200])
    print('--- 关键行 ---')
    for ln in interesting[:80]:
        print(ln.strip()[:400])
    target = Path(r'D:\AI\builds\carwithin\build-run-%d.log' % run['run_number'])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    print(f'\n完整日志: {target}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
