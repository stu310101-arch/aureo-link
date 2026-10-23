"""Collect license texts for the runtime bundled by PyInstaller."""
from pathlib import Path
import shutil
import sys
import sysconfig

root = Path(__file__).resolve().parent
target = root / 'licenses'
target.mkdir(exist_ok=True)
for info in Path(sysconfig.get_paths()['purelib']).glob('*.dist-info'):
    for path in info.rglob('*'):
        if path.is_file() and path.name.lower().startswith(('license', 'copying')):
            dest = target / info.name / path.relative_to(info)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
for name in ('LICENSE.txt', 'tcl/tcl8.6/license.terms', 'tcl/tk8.6/license.terms'):
    path = Path(sys.base_prefix) / name
    if path.is_file():
        dest = target / 'Python' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
print('Prepared runtime licenses in licenses/')
