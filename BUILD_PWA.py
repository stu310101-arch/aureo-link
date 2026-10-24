"""Copy the permanent PWA shell into its fixed GitHub Pages location."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parent
def build():
    source=ROOT/'pwa';target=ROOT/'docs/phone'
    target.mkdir(parents=True,exist_ok=True)
    for path in source.rglob('*'):
        if path.is_file():
            dest=target/path.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,dest)
    obsolete=target/'connect.js'
    if obsolete.exists():obsolete.unlink()
    print('Fixed installable PWA: docs/phone/')
if __name__=='__main__':build()
