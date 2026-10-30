"""Desktop launcher: start the local Crewroom server if needed, then open its window."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from teamchat import paths  # noqa: E402

URL = f'http://127.0.0.1:{paths.PORT}/'
EDGE = [Path(os.environ.get('ProgramFiles(x86)', '')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('ProgramFiles', '')) / 'Microsoft/Edge/Application/msedge.exe']


def running():
    try:
        with urllib.request.urlopen(URL + 'api/ping', timeout=1) as r:
            return json.load(r).get('app') == 'teamchat'
    except OSError:
        return False


if not running():
    exe = Path(sys.executable).with_name('pythonw.exe')
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    log = open(paths.LOGS / 'server.log', 'a', encoding='utf-8')  # if the window says "can't reach this page", look here
    subprocess.Popen([str(exe if exe.exists() else sys.executable), str(ROOT / 'serve.py')], cwd=str(ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    for _ in range(50):
        if running():
            break
        time.sleep(0.1)

edge = next((e for e in EDGE if e.exists()), None)
if edge:
    subprocess.Popen([str(edge), f'--app={URL}', '--window-size=1280,860'])
else:
    os.startfile(URL)
