"""Prepare the pinned official Inno Setup compiler in portable mode."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
VERSION = '6.7.3'
URL = 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe'
SHA256 = '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'


def prepare():
    tools = ROOT / '.build-tools'
    tools.mkdir(exist_ok=True)
    archive = tools / f'innosetup-{VERSION}.exe'
    compiler = tools / f'inno-setup-{VERSION}' / 'ISCC.exe'
    if not compiler.is_file():
        if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            request = urllib.request.Request(URL, headers={'User-Agent': 'AureoLink-build'})
            with urllib.request.urlopen(request, timeout=120) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != SHA256:
                raise RuntimeError('Official Inno Setup SHA256 mismatch')
            archive.write_bytes(content)
        subprocess.run([str(archive), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                        '/SP-', '/PORTABLE=1', '/CURRENTUSER', '/NOICONS',
                        '/DIR=' + str(compiler.parent)], check=True, timeout=120)
    if not compiler.is_file():
        raise RuntimeError('Inno Setup compiler was not extracted')
    for path in compiler.parent.iterdir():
        if path.name.lower() == 'license.txt':
            target = ROOT / 'licenses' / 'InnoSetup'
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target / 'LICENSE.txt')
            break
    else:
        raise RuntimeError('Inno Setup license text was not found')
    print(compiler)


if __name__ == '__main__':
    prepare()
