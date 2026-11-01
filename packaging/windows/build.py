"""Build dist/CrewroomSetup-<version>.exe: a normal Windows installer with its own Python inside.

    python packaging/windows/build.py

Needs Inno Setup 6 (https://jrsoftware.org/isinfo.php). The first run downloads Python's official embeddable
package from python.org into packaging/windows/.cache; later runs reuse it.
"""
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CACHE = HERE / '.cache'
DIST = REPO / 'dist'
PYTHON = '3.13.15'  # the Python bundled into the installer
PY_ZIP = f'python-{PYTHON}-embed-amd64.zip'
PY_URL = f'https://www.python.org/ftp/python/{PYTHON}/{PY_ZIP}'


def version():
    for line in (REPO / 'teamchat' / '__init__.py').read_text(encoding='utf-8').splitlines():
        if line.startswith('__version__'):
            return line.split('=', 1)[1].strip().strip('\'"')
    raise SystemExit('No __version__ in teamchat/__init__.py')


def iscc():
    for base in (os.environ.get('LOCALAPPDATA', ''), os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')):
        exe = Path(base) / ('Programs/Inno Setup 6' if base == os.environ.get('LOCALAPPDATA') else 'Inno Setup 6') / 'ISCC.exe'
        if base and exe.exists():
            return str(exe)
    found = shutil.which('iscc')
    if not found:
        raise SystemExit('Inno Setup 6 is needed: https://jrsoftware.org/isinfo.php')
    return found


def python_runtime():
    """Python's embeddable package, unpacked. Checked by running it before it goes into the installer."""
    CACHE.mkdir(exist_ok=True)
    archive = CACHE / PY_ZIP
    if not archive.exists():
        print(f'Downloading {PY_URL}')
        tmp = archive.with_suffix('.part')
        with urllib.request.urlopen(PY_URL, timeout=120) as r, open(tmp, 'wb') as f:
            shutil.copyfileobj(r, f)
        tmp.replace(archive)
    out = CACHE / f'python-{PYTHON}'
    if out.exists():
        shutil.rmtree(out)
    with zipfile.ZipFile(archive) as z:
        z.extractall(out)
    check = subprocess.run([str(out / 'python.exe'), '-I', '-c',
                            'import sqlite3, json, http.server, urllib.request, ctypes, sys; print(sys.version.split()[0])'],
                           capture_output=True, text=True, cwd=str(CACHE))
    if check.returncode != 0 or check.stdout.strip() != PYTHON:
        raise SystemExit(f'The bundled Python did not start correctly: {check.stdout}{check.stderr}')
    if not (out / 'pythonw.exe').exists():
        raise SystemExit('The bundled Python has no pythonw.exe')
    return out


def main():
    v = version()
    py = python_runtime()
    DIST.mkdir(exist_ok=True)
    subprocess.run([iscc(), f'/DAppVersion={v}', f'/DSrc={REPO}', f'/DPyDir={py}', f'/O{DIST}', '/Q',
                    str(HERE / 'crewroom.iss')], check=True)
    out = DIST / f'CrewroomSetup-{v}.exe'
    shutil.copy2(out, DIST / 'CrewroomSetup.exe')  # the name the website links to: releases/latest/download/CrewroomSetup.exe
    print(f'{out} ({out.stat().st_size / 1e6:.1f} MB), also as CrewroomSetup.exe')


if __name__ == '__main__':
    sys.exit(main())
