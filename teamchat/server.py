"""Local web server for the Team Chat window. Listens on 127.0.0.1 only."""
import json
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import re
import subprocess

from . import __version__, agents, members as team, paths, projects, setup, status, system, transcripts, worker, worklog
from .db import OPEN, Mailbox

WEB = paths.ROOT / 'web'
PAGE_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
FILE_CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
_lock = threading.Lock()
_sessions_cache = {'at': 0, 'value': []}
_window = {'seen': 0}  # when a Crewroom window last asked for news; the tray uses it to notice the window closed
DEV = {'on': False}   # serve(dev=True): the window reloads itself when web/ changes (see web_stamp)


def web_manifest(port):
    """Makes Crewroom installable as an app in Edge or Chrome. Installed, it can draw its own title bar (Window Controls
    Overlay): the control bar becomes the title bar. A dev copy gets its own name, so the two never mix."""
    dev = DEV['on']
    return {'id': '/', 'name': 'Crewroom (dev)' if dev else 'Crewroom', 'short_name': 'Crewroom', 'description': 'Your AI team, together',
            'start_url': '/', 'scope': '/', 'display': 'standalone', 'display_override': ['window-controls-overlay'],
            'background_color': '#1c1a18', 'theme_color': '#141210',
            'icons': [{'src': f'assets/app-icon-{s}.png', 'sizes': f'{s}x{s}', 'type': 'image/png', 'purpose': 'any'} for s in (192, 512)]}


def web_stamp():
    """Newest change time of the window's files, so a dev window can reload itself after an edit."""
    return max((p.stat().st_mtime for p in WEB.rglob('*') if p.is_file()), default=0)
ONBOARDED = paths.DATA / 'onboarded'


def mailbox():
    # One connection per request keeps SQLite thread use simple; WAL makes it cheap.
    return Mailbox()


class Handler(BaseHTTPRequestHandler):
    server_version = 'TeamChat/1'

    def log_message(self, *args):
        pass

    # --- guards ---------------------------------------------------------------
    def _allowed_host(self):
        port = self.server.server_address[1]
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def _allowed_origin(self):
        port = self.server.server_address[1]
        return self.headers.get('Origin') in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')

    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', PAGE_CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code, text):
        self._send(code, {'error': text})

    # --- routes ---------------------------------------------------------------
    def do_GET(self):
        if not self._allowed_host():
            return self._error(403, 'Bad host')
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == '/api/state':
                _window['seen'] = time.time()
                return self._send(200, self.state(int(q.get('after', 0))))
            if url.path == '/api/sessions':
                return self._send(200, sessions_and_projects())
            if url.path == '/api/transcript':
                return self._send(200, transcripts.messages(q.get('provider'), q.get('id', '')))
            if url.path.startswith('/api/file/'):
                return self.file(url.path.rsplit('/', 1)[1], q.get('download') == '1')
            if url.path == '/api/setup-info':
                return self._send(200, {'skills': setup.list_skills(),
                                        'models': {'claude': setup.CLAUDE_MODELS, 'codex': setup.codex_models(),
                                                   **{a: setup.cli_models(a) for a in agents.CLI_AGENTS}},
                                        'apps': [{'id': a.id, 'name': a.name, 'color': a.color, 'blurb': a.blurb,
                                                  'shell': a.shell, 'liveNotes': a.live_notes, 'found': bool(agents.command(a.id)),
                                                  'install': a.install} for a in agents.AGENTS.values()],
                                        'presets': setup.ROLE_PRESETS, 'defaults': setup.DEFAULT_ROLES,
                                        'freshEvery': team.DEFAULT_FRESH_EVERY, 'humanRole': team.DEFAULT_HUMAN_ROLE,
                                        'hues': team.HUES,
                                        'desktop': str(Path.home() / 'Desktop')})
            if url.path == '/api/project':
                mb = mailbox()
                try:
                    found = mb.project(q.get('key', ''))
                    if found:  # older projects: show their two agents as members
                        found['settings'] = found['settings'] | {'members': team.team(found['settings']),
                                                                 'humanRole': team.human_role(found['settings'])}
                    return self._send(200, found or {})
                finally:
                    mb.close()
            if url.path == '/api/worklog':
                return self._send(200, worklog.read(q.get('id', '')))
            if url.path == '/api/setup-check':
                return self._send(200, setup_check())
            if url.path == '/manifest.webmanifest':
                return self._send(200, web_manifest(self.server.server_address[1]), 'application/manifest+json; charset=utf-8')
            if url.path == '/api/ping':
                rec = status.installed() or {}
                return self._send(200, {'ok': True, 'app': 'teamchat', 'version': __version__, 'root': str(paths.ROOT),
                                        'pid': os.getpid(), 'data': str(paths.DATA), 'installedRoot': rec.get('root'),
                                        'installedVersion': rec.get('version'), 'installer': rec.get('installer'),
                                        **({'dev': True, 'stamp': web_stamp()} if DEV['on'] else {}), 'uninstall': status.uninstall_hint(rec.get('root') or paths.ROOT),
                                        'system': 'windows' if system.WINDOWS else 'mac' if system.MAC else 'linux'})
            return self.static(url.path)
        except KeyError:
            return self._error(404, 'Not found')

    def do_POST(self):
        if not self._allowed_host() or not self._allowed_origin():
            return self._error(403, 'Bad origin')
        if not self.headers.get('Content-Type', '').startswith('application/json'):
            return self._error(415, 'JSON only')
        size = int(self.headers.get('Content-Length') or 0)
        if size > 1_000_000:
            return self._error(413, 'Too large')
        try:
            body = json.loads(self.rfile.read(size) or b'{}')
        except ValueError:
            return self._error(400, 'Bad JSON')
        if self.path == '/api/pick-folder':  # the Browse… buttons: the computer's own folder picker
            try:
                start = str(body.get('start') or '')
                chosen = system.pick_folder(start if start and Path(start).is_dir() else None, str(body.get('title') or 'Choose a folder')[:120])
            except (OSError, ValueError) as error:
                return self._error(400, str(error))
            return self._send(200, {'path': chosen})
        if self.path == '/api/onboarded':
            paths.DATA.mkdir(parents=True, exist_ok=True)
            ONBOARDED.write_text(__version__, encoding='utf-8')
            return self._send(200, {'ok': True})
        if self.path == '/api/uninstall':  # the window's Uninstall button (macOS app, Linux package, script installs)
            rec = status.installed() or {}
            if rec.get('installer') == 'setup':
                return self._error(409, 'Uninstall Crewroom from Windows Settings > Apps > Installed apps.')
            if not status.same(rec.get('root'), paths.ROOT):  # only the installed copy may remove what it installed
                return self._error(409, 'This copy of Crewroom is not the installed one, so it has nothing to uninstall.')
            done = subprocess.run([sys.executable, str(paths.ROOT / 'install.py'), '--uninstall',
                                   '--from-app' if rec.get('installer') == 'app' else '--yes'],
                                  capture_output=True, text=True, timeout=120, **system.hidden())
            if done.returncode != 0:
                return self._error(500, (done.stdout + done.stderr).strip()[-400:] or 'Could not uninstall')
            removed = remove_linux_package()
            self._send(200, {'ok': True, 'mac': system.MAC, 'removedFolder': removed})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        if self.path == '/api/shutdown':  # the window's Stop button, the launcher and the installer
            self._send(200, {'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        mb = mailbox()
        try:
            if self.path == '/api/ask':
                to, title = body.get('to'), str(body.get('title', '')).strip()
                if team.app_of(to) == 'human' or to not in mb.member_ids() or not title:
                    return self._error(400, 'Pick a teammate and write a request')
                cwd = str(body.get('cwd') or '').strip().strip('"') or None
                if cwd and not Path(cwd).is_dir():
                    return self._error(400, f'Folder not found: {cwd}')
                req = mb.ask('human', to, title[:200], str(body.get('body', ''))[:20000], cwd=cwd)
                saved = mb.project(projects.root_of(cwd)[0]) if cwd else None
                if body.get('run') and not team.is_manual(saved and saved['settings'], to):
                    worker.start(req['id'])
                return self._send(200, req | {'project': projects.root_of(cwd)[0]})
            if self.path == '/api/say':
                text = str(body.get('body', '')).strip()
                if not text:
                    return self._error(400, 'Empty message')
                channel = body.get('channel') if body.get('channel') in ('general', 'discussion') else None
                rid = body.get('requestId') or None
                mid = mb.say('human', text[:20000], rid=rid,
                             kind='reply' if rid else 'message', project=body.get('project') or None,
                             channel=None if rid else channel or 'general')
                if rid:  # a reply on a running request reaches the agent while it works
                    return self._send(200, {'id': mid, 'note': note_running(mb, mb.request(rid), text)})
                tagged = mention_members(mb, body.get('project'), channel or 'general', text)
                routed = None if tagged else route_to_coordinator(mb, body.get('project'), channel or 'general', text)
                return self._send(200, {'id': mid, 'routedTo': routed, 'mentions': tagged})
            if self.path == '/api/cancel':
                req = mb.request(str(body.get('id', '')))
                if req['status'] not in OPEN:
                    return self._error(409, 'This request is not running')
                mb.set_status(req['id'], 'cancelled', 'human', 'Cancelled.')
                return self._send(200, {'ok': True})
            if self.path == '/api/release':
                req = mb.request(str(body.get('id', '')))
                if req['status'] != 'held':
                    return self._error(409, 'This order is not waiting for you')
                mb.set_status(req['id'], 'asked', 'human', 'Sent by the lead.', kind='note')
                saved = mb.project(projects.root_of(req['cwd'])[0]) if req['cwd'] else None
                if not team.is_manual(saved and saved['settings'], req['recipient']):
                    worker.start(req['id'])
                return self._send(200, {'ok': True})
            if self.path == '/api/retry':
                old = mb.request(str(body.get('id', '')))
                if old['status'] in OPEN:
                    return self._error(409, 'Still running')
                new = mb.ask(old['sender'], old['recipient'], old['title'], old['body'], cwd=old['cwd'],
                             session=old['sender_session'])
                mb.say('human', 'Trying again as a new request.', rid=old['id'], kind='note')
                worker.start(new['id'])
                return self._send(200, new | {'project': projects.root_of(new['cwd'])[0]})
            if self.path in ('/api/projects', '/api/projects/update'):
                made = setup.create(body, mb) if self.path == '/api/projects' else setup.update(body, mb)
                _sessions_cache['at'] = 0
                if body.get('openCodex'):
                    exe = paths.find_codex()
                    if exe:
                        subprocess.Popen([exe, 'app', made['root']], **worker.HIDDEN,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self._send(200, made)
            if self.path == '/api/projects/clear':
                key, mode = str(body.get('key', '')), body.get('mode')
                reqs = [r for r in mb.requests() if projects.root_of(r['cwd'])[0] == key]
                if any(r['status'] in OPEN for r in reqs):
                    return self._error(409, 'Someone is still working in this project. Wait or cancel those requests first.')
                if mode == 'fresh':
                    mb.start_fresh(key)
                elif mode == 'delete':
                    mb.delete_history(key, [r['id'] for r in reqs])
                else:
                    return self._error(400, 'Unknown option')
                _sessions_cache['at'] = 0
                return self._send(200, {'ok': True, 'removed': len(reqs) if mode == 'delete' else 0})
            if self.path == '/api/open':
                return self._send(200, {'message': open_action(mb, body)})
            return self._error(404, 'Not found')
        except (KeyError, ValueError, OSError) as error:
            return self._error(400, str(error).strip("'"))
        finally:
            mb.close()

    # --- helpers --------------------------------------------------------------
    def state(self, after):
        mb = mailbox()
        try:
            msgs = mb.messages(after=after)
            last = msgs[-1]['seq'] if msgs else after
            reqs = mb.requests()[:300]
            projects.set_saved_roots(mb.saved_projects())
            for r in reqs:
                r['project'] = projects.root_of(r['cwd'])[0]
            saved = mb.saved_projects()
            members = {}
            for k, v in team.display(saved).items():
                pic = 'you' if v['app'] == 'human' else v['app']
                members[k] = v | ({'avatar': f'assets/avatar-{pic}.png'} if (WEB / 'assets' / f'avatar-{pic}.png').exists() else {})
            teams = {sp['key']: [m['id'] for m in team.team(sp['settings'])] for sp in saved}
            manual = {sp['key']: [m['id'] for m in team.team(sp['settings']) if m.get('manual')] for sp in saved}
            return {'members': members, 'teams': teams, 'manual': manual, 'requests': reqs, 'messages': msgs, 'last': last,
                    'cleared': mb.cleared()}
        finally:
            mb.close()

    def file(self, aid, download):
        mb = mailbox()
        try:
            a = mb.attachment(aid)
        finally:
            mb.close()
        if not a or not Path(a['path']).is_file():
            return self._error(404, 'File is gone')
        data = Path(a['path']).read_bytes()
        inline = a['mime'].startswith(('image/', 'video/', 'audio/')) or a['mime'] == 'application/pdf'
        disposition = 'inline' if inline and not download else 'attachment'
        self.send_response(200)
        self.send_header('Content-Type', a['mime'])
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Content-Disposition', f'{disposition}; filename="{a["name"].replace(chr(34), "")}"')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', FILE_CSP)
        self.end_headers()
        self.wfile.write(data)

    def static(self, path):
        rel = 'index.html' if path in ('/', '') else path.lstrip('/')
        target = (WEB / rel).resolve()
        if not target.is_relative_to(WEB.resolve()) or not target.is_file():
            raise KeyError(path)
        ctype = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype.endswith('javascript'):
            ctype += '; charset=utf-8'
        self._send(200, target.read_bytes(), ctype)


def sessions_and_projects():
    """The project list (from Crewroom's own projects and requests), cached briefly. Crewroom no longer lists the
    agents' app chats: a hand-off needs only its request and result, and each request has its own work log."""
    with _lock:
        if time.time() - _sessions_cache['at'] > 5:
            mb = mailbox()
            try:
                saved = mb.saved_projects()
                projects.set_saved_roots(saved)
                reqs = mb.requests()
            finally:
                mb.close()
            _sessions_cache.update(at=time.time(), value={'sessions': [], 'projects': projects.group(reqs, [], saved)})
        return _sessions_cache['value']


def known_folders(mb):
    """Folders the window may open: project roots and request folders, nothing else."""
    found = {projects._norm(r['cwd']) for r in mb.requests() if r['cwd']}
    for p in sessions_and_projects()['projects']:
        if p['root']:
            found.add(projects._norm(p['root']))
    return found


def _inside_known(path, mb):
    path = projects._norm(path)
    return any(path == f or path.startswith(f.rstrip('\\/') + os.sep) for f in known_folders(mb))


reveal = system.reveal


def open_action(mb, body):
    action = body.get('action')
    if action in ('reveal-file', 'open-file'):
        a = mb.attachment(str(body.get('id', '')))
        if not a or not Path(a['path']).exists():
            raise ValueError('That file is gone')
        if action == 'reveal-file':
            reveal(a['path'])
            return f'Opened in {system.FILE_MANAGER}'
        system.open_path(a['path'])
        return f"Opened {a['name']}"
    if action in ('folder', 'codex-app'):
        path = str(body.get('path', ''))
        if not path or not Path(path).is_dir() or not _inside_known(path, mb):
            raise ValueError('Unknown folder')
        if action == 'folder':
            system.open_path(path)
            return f'Opened in {system.FILE_MANAGER}'
        exe = paths.find_codex()
        if not exe:
            raise ValueError('Codex is not installed')
        subprocess.Popen([exe, 'app', path], **worker.HIDDEN,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 'Opening this project in the Codex app'
    if action == 'claude-desktop':
        sid = str(body.get('session', ''))
        if not re.fullmatch(r'[0-9a-f-]{36}', sid) or not list(paths.CLAUDE_PROJECTS.glob(f'*/{sid}.jsonl')):
            raise ValueError('Unknown Claude chat')
        if any(r['worker_session'] == sid and r['status'] in OPEN for r in mb.requests()):
            raise ValueError('Claude is still working in this chat; open it when the request is done')
        exe = paths.find_claude()
        if not exe:
            raise ValueError('Claude Code is not installed')
        subprocess.Popen([exe, '--desktop', '--resume', sid], **worker.HIDDEN,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 'Opening the chat in Claude Desktop'
    if action == 'link':
        target = resolve_link(mb, str(body.get('href', '')), str(body.get('base', '')))
        if body.get('mode') == 'path':
            return str(target)
        if body.get('mode') == 'open' or not target.is_file():
            system.open_path(target)
            return f'Opened {target.name}'
        reveal(target)
        return f'Opened in {system.FILE_MANAGER}'
    raise ValueError('Unknown action')


SEARCH_SKIP = {'.git', 'node_modules', '.venv', '__pycache__', 'graphify-out'}


def resolve_link(mb, href, base):
    """A path a message mentions, inside the project folders only. Bare names are looked up under the base folder."""
    href = href.strip().strip('`').replace('/', os.sep)
    if not base or not _inside_known(base, mb):
        raise ValueError('Crewroom only opens files inside your project folders')
    target = Path(href) if Path(href).is_absolute() else Path(base) / href
    if not target.exists() and not Path(href).is_absolute():
        target = _find(Path(base), Path(href)) or target
    if not _inside_known(target, mb):
        raise ValueError('Crewroom only opens files inside your project folders')
    if not target.exists():
        raise ValueError(f'Not found: {href}')
    return target


def _find(base, rel, limit=4000):
    """Find `rel` (e.g. "t0.25.png" or "team-setup/NOTES.md") somewhere under base; nearest match wins."""
    parts = rel.parts
    seen = 0
    for folder, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SEARCH_SKIP and not d.startswith('.'))
        candidate = Path(folder) / rel
        if candidate.exists():
            return candidate
        seen += len(files) + len(dirs)
        if seen > limit or len(parts) == 0:
            return None
    return None


def note_running(mb, req, text):
    """Give a note to a request that hasn't finished. 'live' = the agent reads it mid-run, 'start' = before it starts,
    'after' = it is working and can't read notes mid-run (Cursor, Antigravity): the note becomes a follow-up request."""
    saved = mb.project(projects.root_of(req['cwd'])[0]) if req['cwd'] else None
    if req['status'] not in ('asked', 'queued', 'working') or team.is_manual(saved and saved['settings'], req['recipient']):
        return None
    mb.nudge(req['id'], text)
    if req['status'] != 'working':
        return 'start'
    return 'live' if agents.AGENTS[team.app_of(req['recipient'])].live_notes else 'after'


def mention_members(mb, key, channel, text):
    """@Name in a channel message: a working member gets it as a note mid-run, a free one gets a new request."""
    p = mb.project(key) if key else None
    if not p:
        return []
    out = []
    for mid in team.mentions(text, p['settings']):
        name = team.find(p['settings'], mid)['name']
        working = [r for r in mb.requests(recipient=mid) if r['status'] == 'working' and r['cwd']
                   and projects.root_of(r['cwd'])[0] == key]
        how = note_running(mb, working[0], text) if working else None
        if how:
            mb.say(mid, f"Working on **{working[0]['title']}**. " + ("I'll read your note between steps and adapt." if how == 'live'
                   else "I'll pick up your note as soon as I finish this."), project=key, channel=channel, kind='note')
            out.append({'id': mid, 'how': how, 'request': working[0]['id']})
            continue
        first = ' '.join(text.split())[:80]
        req = mb.ask('human', mid, f'{first}', f'The lead wrote in #{channel} and tagged you:\n\n> ' + text.replace('\n', '\n> '),
                     cwd=p['root'], channel=channel)
        if team.is_manual(p['settings'], mid):
            out.append({'id': mid, 'how': 'inbox', 'request': req['id']})
        else:
            worker.start(req['id'])
            out.append({'id': mid, 'how': 'new', 'request': req['id']})
    return out


def route_to_coordinator(mb, key, channel, text):
    """A lead's channel message goes to the project's coordinator (Producer), if it has one."""
    p = mb.project(key) if key else None
    coordinator = p and p['settings'].get('coordinator')
    if not coordinator or coordinator not in {m['id'] for m in team.team(p['settings'])}:
        return None
    first = ' '.join(text.split())[:70]
    req = mb.ask('human', coordinator, f'Lead in #{channel}: {first}',
                 f'The lead wrote in #{channel}:\n\n> ' + text.replace('\n', '\n> ') +
                 '\n\nReply to them briefly. If it needs work, refine it into clear orders and dispatch them.',
                 cwd=p['root'], channel=channel)
    worker.start(req['id'])
    return coordinator


LINUX_HOME = Path.home() / '.local' / 'lib' / 'crewroom'  # where the Linux package installs the program


def remove_linux_package():
    """The Linux package lives in one folder of its own; uninstalling removes it (Linux lets a running program
    delete its files). Never touches anything else, and never the data folder."""
    if system.WINDOWS or system.MAC or not status.same(paths.ROOT, LINUX_HOME):
        return None
    import shutil
    shutil.rmtree(paths.ROOT, ignore_errors=True)
    return str(paths.ROOT)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return  # the window closed mid-answer: normal, not worth a scary log entry
        super().handle_error(request, client_address)


def setup_check():
    """What the welcome screen shows: are the agents and the team skill in place on this computer?"""
    def skill(rel):
        try:
            return str(paths.ROOT / 'team.py') in (Path.home() / rel / 'SKILL.md').read_text(encoding='utf-8')
        except OSError:
            return False
    return {'version': __version__, 'system': 'windows' if system.WINDOWS else 'mac' if system.MAC else 'linux',
            'claude': paths.find_claude(), 'codex': paths.find_codex(),
            'skills': {'claude': skill('.claude/skills/team-chat'), 'codex': skill('.agents/skills/team-chat')},
            'agents': agents.setup_status(),
            'onboarded': ONBOARDED.exists(), 'tray': system.WINDOWS and not os.environ.get('TEAMCHAT_NO_TRAY')}


def tray_status():
    """(tooltip, menu lines, working count) for the tray icon."""
    mb = mailbox()
    try:
        open_reqs = mb.requests(open_only=True)
    finally:
        mb.close()
    working = sum(r['status'] == 'working' for r in open_reqs)
    waiting = sum(r['status'] in ('queued', 'asked') for r in open_reqs)
    news = [f'{working} request{"s" if working != 1 else ""} working' if working else 'Nobody is working right now']
    if waiting:
        news.append(f'{waiting} waiting to start')
    return f'Crewroom {__version__} is running\n' + ' · '.join(news), [f'Crewroom {__version__} is running', *news], working


def serve(port=paths.PORT, dev=False):
    """dev=True: a second copy for working on the window next to the installed Crewroom, on the same data. It runs
    no Supervisor (two would restart and retry the same requests) and shows no tray icon."""
    httpd = Server(('127.0.0.1', port), Handler)
    DEV['on'] = dev
    from . import supervisor
    if not dev:
        supervisor.start_thread()
    tray = None
    if system.WINDOWS and not dev and not os.environ.get('TEAMCHAT_NO_TRAY'):
        from .tray import Tray
        tray = Tray(WEB / 'assets' / 'app-icon.ico', open_window=lambda: system.open_window(status.url(port)),
                    stop=lambda: threading.Thread(target=httpd.shutdown, daemon=True).start(),
                    status=tray_status, seen=lambda: _window['seen'])
        tray.start()
    try:
        httpd.serve_forever()
    finally:
        if tray:  # take the icon away with us, so it never lingers after Crewroom stopped
            tray.close()
            time.sleep(0.3)


if __name__ == '__main__':
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else paths.PORT)
