"""Desktop launcher: start this folder's Crewroom server if needed, then open its window.

If a Crewroom from a different folder is already running, it is stopped first, so the copy you open is always
the copy you get. Its background requests keep running. `team status` shows which copy is running.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from teamchat import paths, status, system  # noqa: E402


def log(text):
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    with open(paths.LOGS / 'server.log', 'a', encoding='utf-8') as f:
        f.write(f'launcher: {text}\n')


def start_server():
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    out = open(paths.LOGS / 'server.log', 'a', encoding='utf-8')  # if the window says "can't reach this page", look here
    subprocess.Popen([system.background_python(), str(ROOT / 'serve.py')], cwd=str(ROOT),
                     stdin=subprocess.DEVNULL, stdout=out, stderr=out, **system.detached())
    for _ in range(80):
        if status.ping():
            return True
        time.sleep(0.1)
    return False


info = status.ping()
if info and not status.same(status.running_root(info), ROOT):
    log(f"another Crewroom ({info.get('version', '1.0')}, {status.running_root(info) or 'unknown folder'}) was running; "
        f'switching to {ROOT}')
    status.stop()
    info = None
if not info and not start_server():
    log('the server did not answer within 8 seconds')
system.open_window(status.url())
