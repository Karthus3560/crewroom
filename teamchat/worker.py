"""Background workers: hand a request to Claude or Codex and report back when done.

Each project keeps ONE ongoing chat per agent. The first request in a project starts a chat
("<Project> · Team Chat"); later requests continue that same chat, so the agent remembers the
project. Codex chats are started through Codex's app server, so they show in the Codex app's chat
list. Requests for the same agent and project run one at a time; others wait as "queued".
"""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import paths, projects, system
from . import agents, dispatch, members as team
from .db import Mailbox

HIDDEN = system.hidden()  # Popen options: no console window on Windows
SKIP_DIRS = {'.git', 'node_modules', '.venv', '__pycache__', 'bin', 'obj', 'graphify-out'}
MEDIA = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.pdf', '.mp4', '.mp3', '.wav'}
TIMEOUT = int(os.environ.get('TEAMCHAT_WORK_TIMEOUT', '1800'))

PROMPT = '''[Crewroom request {rid} from {asker}]

# {title}

{body}

Work folder: {cwd}
{team}- This chat is your ongoing workspace for the "{project}" project; earlier requests here are context.
- Do the whole task without asking follow-up questions; make sensible choices and say what you chose.
- Save every image or file you create inside the work folder (images as PNG unless asked otherwise).
- Images: save each generated image straight to its file path. Never paste image or base64 data into a
  shell command (Windows limits command length); resize or convert with a short script that reads the file.
- Never publish, buy, send messages, change accounts or touch other projects.

Finish with a short, friendly Markdown note for the team chat: what you did, the files you made
(paths relative to the work folder) and anything left undone. Do not claim checks you did not run.'''

SHELL_YES = ('- You may run commands in the work folder: checks, tests, builds, snapshots, renders. Run the checks your '
             'work needs yourself and report their real output. Never delete folders, push, or install anything system-wide.\n')
SHELL_NO = ('- You cannot run commands here. Do the file work, then list the exact commands someone else should run '
            '(and what to look for) in your reply.\n')

NOTE = '''[Crewroom] A note from the lead arrived while you were working on this request:

{text}

Adapt your work if it applies, even if that changes what you are doing right now. In your final note, say what you changed because of it.'''

FIRST = '''You are {name}, a member of a small AI team working through the local "Crewroom" app with the
human lead and other Claude/Codex members. Requests arrive in this chat; each one says who asked and what they need.
Team and roles: TEAM.md in the project folder, or run `team roles`.
{recap}
'''

RECAP = '''This is a fresh chat (older chats are kept short to save tokens). What you did recently in this project:
{items}
'''


class Cancelled(Exception):
    pass


def start(rid):
    """Launch the worker as a detached process so the asker can keep working."""
    proc = subprocess.Popen([system.background_python(), str(paths.ROOT / 'team.py'), '_work', rid], cwd=str(paths.ROOT),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **system.detached())
    mb = Mailbox()
    mb.link(rid, worker_pid=proc.pid)
    mb.close()
    return proc.pid


# --- files ------------------------------------------------------------------
def snapshot(root):
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = os.path.join(dirpath, f)
            try:
                seen[p] = os.path.getmtime(p)
            except OSError:
                pass
            if len(seen) > 20000:
                return seen
    return seen


def changed_files(before, root, limit=24):
    after = snapshot(root)
    new = [p for p, m in after.items() if before.get(p) != m and not p.endswith('.prompt.txt')]
    new.sort(key=lambda p: (Path(p).suffix.lower() not in MEDIA, -after[p]))
    return new[:limit]


# --- one request at a time per project and agent ------------------------------
class ProjectLock:
    def __init__(self, project, provider):
        paths.DATA.mkdir(parents=True, exist_ok=True)
        self.path = paths.DATA / f'lock-{project}-{provider}'
        self.file = None

    def acquire(self, should_stop):
        self.file = open(self.path, 'a+')
        while not system.try_lock(self.file):
            if should_stop():
                self.file.close()
                raise Cancelled()
            time.sleep(2)

    def release(self):
        if self.file:
            system.unlock(self.file)
            self.file.close()


# --- Codex through its app server ----------------------------------------------
class CodexChat:
    """Minimal JSON-RPC client for `codex app-server --stdio` (the protocol the Codex app uses)."""

    def __init__(self, log):
        exe = paths.find_codex()
        if not exe:
            raise RuntimeError('Codex not found. Is the Codex app installed and signed in?')
        self.log = log
        self.proc = subprocess.Popen([exe, 'app-server', '--stdio'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, **HIDDEN, text=True, encoding='utf-8', errors='replace')
        self.events, self.replies, self.seq = queue.Queue(), {}, 0
        threading.Thread(target=self._read, daemon=True).start()
        self.call('initialize', {'clientInfo': {'name': 'team_chat', 'version': '1.1'}, 'capabilities': {'experimentalApi': True}})
        self.send({'method': 'initialized'})

    def _read(self):
        for line in self.proc.stdout:
            self.log.write(line)
            self.log.flush()
            try:
                self.events.put(json.loads(line))
            except ValueError:
                continue
        self.events.put({'method': '_eof'})

    def send(self, payload):
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
        self.proc.stdin.flush()

    def call(self, method, params, timeout=60):
        self.seq += 1
        rid = self.seq
        self.send({'id': rid, 'method': method, 'params': params})
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = self.events.get(timeout=1)
            except queue.Empty:
                continue
            if msg.get('id') == rid and 'method' not in msg:
                if 'error' in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message', msg['error'])}")
                return msg.get('result', {})
            if msg.get('method') == '_eof':
                raise RuntimeError('Codex app server stopped')
            self._answer_request(msg)
        raise TimeoutError(f'{method} timed out')

    def _answer_request(self, msg):
        # Background work never gets interactive approvals: decline anything Codex asks permission for.
        if 'id' in msg and msg.get('method'):
            if msg['method'].endswith('requestApproval'):
                self.send({'id': msg['id'], 'result': {'decision': 'decline'}})
            else:
                self.send({'id': msg['id'], 'error': {'code': -32601, 'message': 'Not available in background work'}})

    def open(self, cwd, thread=None, name=None, model=None):
        config = {'cwd': cwd, 'approvalPolicy': 'never', 'sandbox': 'workspace-write'}
        if model:
            config['model'] = model
        if thread:
            try:
                return self.call('thread/resume', config | {'threadId': thread})['thread']['id'], False
            except RuntimeError:
                pass  # chat was deleted or archived: start a new one
        tid = self.call('thread/start', config)['thread']['id']
        if name:
            try:
                self.call('thread/name/set', {'threadId': tid, 'name': name})
            except (RuntimeError, TimeoutError):
                pass
        return tid, True

    def turn(self, thread, prompt, should_stop, notes=lambda: [], delivered=lambda nid, ok: None):
        turn = self.call('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': prompt, 'text_elements': []}]})['turn']['id']
        final, end, steering, polled = '', time.time() + TIMEOUT, {}, 0
        while True:
            if time.time() - polled > 2:  # notes from the lead go into the running turn
                polled = time.time()
                for nid, body in notes():
                    self.seq += 1
                    steering[self.seq] = nid
                    self.send({'id': self.seq, 'method': 'turn/steer', 'params': {'threadId': thread, 'expectedTurnId': turn,
                               'input': [{'type': 'text', 'text': NOTE.format(text=body), 'text_elements': []}]}})
            if should_stop():
                try:
                    self.call('turn/interrupt', {'threadId': thread, 'turnId': turn}, timeout=10)
                except (RuntimeError, TimeoutError):
                    pass
                raise Cancelled()
            if time.time() > end:
                raise TimeoutError(f'Stopped after {TIMEOUT // 60} minutes')
            try:
                msg = self.events.get(timeout=2)
            except queue.Empty:
                continue
            method, params = msg.get('method', ''), msg.get('params', {})
            if msg.get('id') in steering and not method:
                delivered(steering.pop(msg['id']), 'error' not in msg)
            elif 'id' in msg and method:
                self._answer_request(msg)
            elif method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
                final = params['item'].get('text', '') or final
            elif method == 'turn/completed' and params.get('turn', {}).get('id') == turn:
                t = params['turn']
                if t.get('status') != 'completed':
                    raise RuntimeError(f"Codex turn {t.get('status')}: {t.get('error') or ''}")
                return final
            elif method == '_eof':
                raise RuntimeError('Codex app server stopped before finishing')

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _chat_name(project, member):
    return f"Crewroom · {project['name']}" + ('' if member['id'] == member['app'] else f" · {member['name']}")


def run_codex(mb, req, project, cwd, prompt, log, should_stop):
    member = project['member']
    chat = CodexChat(log)
    try:
        tid, new = chat.open(project['root'] or cwd, project['session'], _chat_name(project, member), member.get('model'))
        turns = 1 if new else project['turns'] + 1
        mb.remember_session(project['key'], member['id'], tid, turns)
        mb.link(req['id'], worker_session=tid)
        text = (FIRST.format(name=member['name'], recap=project['recap']) if new else '') + prompt
        return chat.turn(tid, text, should_stop, lambda: mb.take_nudges(req['id']), lambda nid, ok: _delivered(mb, req, nid, ok)), tid
    finally:
        chat.close()


READ_WRITE = 'Read,Glob,Grep,Edit,Write,WebSearch,WebFetch'
# Members allowed to run commands still never get these: they lose work or reach outside the project.
NEVER = ['git push', 'git reset --hard', 'git clean', 'git checkout --', 'rm -rf', 'rm -r', 'rmdir', 'del ', 'erase',
         'format', 'shutdown', 'reg ', 'Remove-Item', 'Clear-Content', 'Stop-Computer', 'Restart-Computer']


def claude_tools(member):
    """Tool flags for a background Claude member. Commands only when the lead ticked "Can run commands"."""
    if not member.get('shell'):
        return ['--allowedTools', READ_WRITE]
    denied = [f'{tool}({cmd.strip()}:*)' for tool in ('Bash', 'PowerShell') for cmd in NEVER]
    return ['--allowedTools', READ_WRITE + ',Bash,PowerShell', '--disallowedTools', ','.join(denied)]


def run_claude(mb, req, project, cwd, prompt, log, should_stop):
    exe = paths.find_claude()
    if not exe:
        raise RuntimeError('Claude Code not found. Is Claude Desktop installed and signed in?')
    member = project['member']
    known = project['session']
    session = known or str(uuid.uuid4())
    root = project['root'] or cwd
    args = [exe, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose', '--permission-mode', 'acceptEdits',
            *claude_tools(member), '--add-dir', cwd]
    if member.get('model'):
        args += ['--model', member['model']]
    args += ['--resume', session] if known else ['--session-id', session, '--name', _chat_name(project, member)]
    mb.remember_session(project['key'], member['id'], session, project['turns'] + 1 if known else 1)
    mb.link(req['id'], worker_session=session)
    text = (FIRST.format(name=member['name'], recap=project['recap']) if not known else '') + prompt
    proc = subprocess.Popen(args, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        **HIDDEN, text=True, encoding='utf-8', errors='replace')
    def user(message):
        proc.stdin.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': message}}, ensure_ascii=False) + '\n')
        proc.stdin.flush()

    user(text)
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout] + [lines.put(None)], daemon=True).start()
    final, end, finals, polled, open_ = '', time.time() + TIMEOUT, [], 0, True
    while True:
        if should_stop() or time.time() > end:
            proc.kill()
            raise Cancelled() if should_stop() else TimeoutError(f'Stopped after {TIMEOUT // 60} minutes')
        if open_ and time.time() - polled > 2:  # notes from the lead are read between the agent's steps
            polled = time.time()
            for nid, body in mb.take_nudges(req['id']):
                try:
                    user(NOTE.format(text=body))
                    _delivered(mb, req, nid, True)
                except OSError:
                    _delivered(mb, req, nid, False)
        try:
            line = lines.get(timeout=2)
        except queue.Empty:
            continue
        if line is None:
            break
        log.write(line)
        log.flush()
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'result':
            if event.get('result'):
                finals.append(event['result'])
            final = '\n\n'.join(finals) or final
            if open_:  # no new notes after the turn ends; late ones become a follow-up request
                open_ = False
                proc.stdin.close()
            if event.get('is_error'):
                if known and 'No conversation found' in (final or ''):
                    mb.forget_session(project['key'], member['id'])
                raise RuntimeError(final or 'Claude reported an error')
    if proc.wait() != 0 and not final:
        raise RuntimeError(f'Claude exited with code {proc.returncode}')
    return final, session


def run_cli(mb, req, project, cwd, prompt, log, should_stop):
    """Cursor Agent or the Antigravity CLI: one print-mode turn, continuing the member's chat when it has one.
    Notes from the lead can't reach these mid-run; they are carried into a follow-up request instead."""
    member = project['member']
    app = member['app']
    spec = agents.AGENTS[app]
    if not agents.command(app):
        raise RuntimeError(f'{spec.name} is not installed on this computer. {spec.install}')
    known = project['session']
    root = project['root'] or cwd
    text = agents.brief((FIRST.format(name=member['name'], recap=project['recap']) if not known else '') + prompt, req['id'])
    proc = subprocess.Popen(agents.argv(app, member, root, cwd, known, text), cwd=root, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', **HIDDEN)
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout] + [lines.put(None)], daemon=True).start()
    session, final, failed, end, tail = known, '', False, time.time() + TIMEOUT, []
    remembered = False
    while True:
        if should_stop() or time.time() > end:
            proc.kill()
            raise Cancelled() if should_stop() else TimeoutError(f'Stopped after {TIMEOUT // 60} minutes')
        try:
            line = lines.get(timeout=2)
        except queue.Empty:
            continue
        if line is None:
            break
        log.write(line)
        log.flush()
        try:
            event = json.loads(line)
        except ValueError:
            tail = (tail + [line.strip()])[-12:]  # not JSON: a message from the program itself (login, errors)
            continue
        got = agents.read(app, event)
        if got.get('session') and not remembered:
            session, remembered = got['session'], True
            mb.remember_session(project['key'], member['id'], session, project['turns'] + 1 if known else 1)
            mb.link(req['id'], worker_session=session)
        if 'final' in got:
            final, failed = got['final'], got['error']
    code = proc.wait()
    if failed or (code != 0 and not final):
        if known and not remembered:
            mb.forget_session(project['key'], member['id'])  # the old chat is gone: start a new one next time
        said = final or '\n'.join(tail) or f'{spec.name} exited with code {code}'
        if re.search(r'not logged in|log ?in|sign ?in|authenticat', said, re.I):
            said += f'\n\n{spec.name} needs you to sign in once: {spec.login}'
        raise RuntimeError(said)
    return final, session


# --- the worker process --------------------------------------------------------
def notify(req):
    """Tell an asking Codex chat. Everyone else sees the window or uses `team wait`."""
    if team.app_of(req['sender']) == 'codex' and req.get('sender_session'):
        try:
            r = subprocess.run([paths.find_codex(), 'queue', '--thread', req['sender_session'], '--message',
                f"[Crewroom] {req['recipient']} finished request {req['id']} \"{req['title']}\". Run: team show {req['id']}"],
                capture_output=True, text=True, timeout=30, **HIDDEN)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError, TypeError):
            return False
    return False


def work(rid):
    mb = Mailbox()
    req = mb.request(rid)
    who = req['recipient']
    if team.app_of(who) == 'human':
        return 1
    cwd = req['cwd'] or str(paths.DATA / 'work' / rid)
    Path(cwd).mkdir(parents=True, exist_ok=True)
    projects.set_saved_roots(mb.saved_projects())
    k, name, root = projects.root_of(cwd)
    saved = mb.project(k)
    settings = saved['settings'] if saved else {}
    member = team.find(settings, who)
    session, turns = mb.agent_session(k, who)
    fresh_every = int(settings.get('freshEvery', team.DEFAULT_FRESH_EVERY) or 0)
    recap = ''
    if session and fresh_every and turns >= fresh_every:
        session, recap = None, _recap(mb, k, who)  # start a fresh chat to keep each turn small
    project = dict(key=k, name=name, root=root, member=member, session=session, turns=turns, recap=recap)
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    log_path = paths.LOGS / f'{rid}.log'

    def should_stop():
        return mb.request(rid)['status'] == 'cancelled'

    lock = ProjectLock(k, who)
    session = None
    try:
        if mb.request(rid)['status'] == 'cancelled':
            return 1
        if _busy(mb, rid, who, k):
            mb.set_status(rid, 'queued', who, f'Queued — I will start after my current **{name}** request.', kind='note')
        lock.acquire(should_stop)
        mb.set_status(rid, 'working', who, f'On it — working in `{cwd}`.')
        before = snapshot(cwd)
        roles_line = ''
        if member.get('roles'):
            roles_line = f"- You are **{member['name']}**. Your roles here: {'; '.join(member['roles'])}\n"
        if agents.AGENTS[member['app']].shell:
            roles_line += (SHELL_YES if member.get('shell') else SHELL_NO)
        names = team.display(mb.saved_projects())
        prompt = PROMPT.format(rid=rid, asker=names.get(req['sender'], {}).get('name', req['sender']), title=req['title'],
            body=req['body'] or '(no extra details)', cwd=cwd, project=name, team=roles_line)
        early = mb.take_nudges(rid)
        if early:
            prompt += '\n\nNotes the lead added after asking (they win over the request where they differ):\n' + \
                '\n'.join(f'- {body}' for _, body in early)
        prompt += dispatch.prompt_section(settings, member)
        if req['sender'] == 'human' and settings.get('coordinator') != member['id'] and settings.get('members'):
            prompt += dispatch.ADDING.format(max=dispatch.MAX_NEW_MEMBERS)
        with open(log_path, 'a', encoding='utf-8') as log:
            run = {'codex': run_codex, 'claude': run_claude}.get(member['app'], run_cli)
            final, session = run(mb, req, project, cwd, prompt, log, should_stop)
        taken = mb.attached_paths()
        files = [f for f in changed_files(before, cwd, limit=200) if str(Path(f).resolve()) not in taken][:24]
        shown, notes = dispatch.handle(mb, req, member, settings, final or '', start, project=k)
        mb.set_status(rid, 'done', who, shown or 'Done.', session=session, files=files)
        if req.get('channel') and shown:  # answer the lead where they wrote
            mb.say(who, shown, project=k, channel=req['channel'])
        for note in notes:
            mb.say(who, note, rid=rid, kind='note')
        if notify(req):
            mb.say(who, 'Sent a done note into the asking Codex chat.', rid=rid, kind='note')
        _carry_notes(mb, req, member, settings)
        return 0
    except Cancelled:
        mb.say(who, 'Stopped as asked. Files may be partly changed.', rid=rid, kind='note')
        return 1
    except Exception as error:
        tail = log_path.read_text(encoding='utf-8', errors='replace')[-1200:] if log_path.exists() else ''
        mb.set_status(rid, 'failed', who, f'**Could not finish:** {error}\n\n<details><summary>Log</summary>\n\n```text\n{tail}\n```\n</details>', session=session)
        return 1
    finally:
        lock.release()
        mb.close()


def _delivered(mb, req, nid, ok):
    if ok:
        mb.say(req['recipient'], 'Got your note mid-run; adapting the work.', rid=req['id'], kind='note')
    else:  # the turn had just ended: the note waits for the follow-up
        mb.nudge_status(nid, 'pending')


def _carry_notes(mb, req, member, settings):
    """Notes that missed the run (it ended first) become one follow-up request in the same chat."""
    late = mb.take_nudges(req['id'])
    if not late:
        return None
    for nid, _ in late:
        mb.nudge_status(nid, 'carried')
    new = mb.ask('human', req['recipient'], f"Follow-up: {req['title']}"[:200],
                 'You just finished this request, and these notes from the lead arrived as you were wrapping up. '
                 'Apply them to the work you did:\n\n' + '\n'.join(f'- {body}' for _, body in late),
                 cwd=req['cwd'], channel=req.get('channel'))
    mb.say(req['recipient'], f"Your note arrived as I finished, so I'll do it next (request `{new['id']}`).", rid=req['id'], kind='note')
    if not team.is_manual(settings, req['recipient']):
        start(new['id'])
    return new


def _recap(mb, key, who, limit=6):
    done = [r for r in mb.requests(recipient=who) if r['status'] == 'done' and projects.root_of(r['cwd'])[0] == key][:limit]
    items = []
    for r in reversed(done):
        last = mb.messages(rid=r['id'])[-1]['body'] if mb.messages(rid=r['id']) else ''
        items.append(f"- {r['title']}: {' '.join(last.split())[:300]}")
    return RECAP.format(items='\n'.join(items)) if items else ''


def _busy(mb, rid, who, key):
    return any(r['id'] != rid and r['recipient'] == who and r['status'] == 'working'
               and projects.root_of(r['cwd'])[0] == key for r in mb.requests())


def wait(rid, timeout=3600, interval=3):
    mb = Mailbox()
    try:
        end = time.time() + timeout
        while time.time() < end:
            req = mb.request(rid)
            if req['status'] in ('done', 'failed', 'cancelled'):
                return req
            time.sleep(interval)
        return mb.request(rid)
    finally:
        mb.close()
