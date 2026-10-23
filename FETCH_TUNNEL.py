"""Fetch the official Windows tunnel binary and verify GitHub's asset digest."""
import hashlib
import json
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parent / 'tools'
root.mkdir(exist_ok=True)
metadata = root / 'cloudflared-release.json'
if metadata.exists():
    release = json.loads(metadata.read_text(encoding='utf-8-sig'))
else:
    request = urllib.request.Request('https://api.github.com/repos/cloudflare/cloudflared/releases/latest',
                                     headers={'User-Agent': 'AureoLink-build'})
    with urllib.request.urlopen(request, timeout=60) as response:
        info = json.load(response)
    asset = next(item for item in info['assets'] if item['name'] == 'cloudflared-windows-amd64.exe')
    release = {'Tag': info['tag_name'], 'Url': asset['browser_download_url'],
               'Digest': asset['digest'], 'Size': asset['size']}
    metadata.write_text(json.dumps(release, indent=2), encoding='utf-8')
target = root / 'cloudflared.exe'
expected = release['Digest'].removeprefix('sha256:')
if len(expected) != 64:
    raise RuntimeError('Official release is missing a SHA256 digest')
if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
    print('Downloading official cloudflared ' + release['Tag'], flush=True)
    temporary = target.with_suffix('.part')
    with urllib.request.urlopen(release['Url'], timeout=120) as response, temporary.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Official cloudflared download failed SHA256 verification')
    temporary.replace(target)
license_file = root / 'LICENSE-cloudflared.txt'
if not license_file.exists():
    with urllib.request.urlopen(f"https://raw.githubusercontent.com/cloudflare/cloudflared/{release['Tag']}/LICENSE", timeout=60) as response:
        license_file.write_bytes(response.read())
print('cloudflared SHA256 verified: ' + expected)
