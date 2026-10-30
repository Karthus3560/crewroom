"""The shared mailbox: requests between teammates, chat messages and attached files."""
import contextlib
import json
import mimetypes
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import paths

MEMBERS = {
    'human': {'name': 'You', 'role': 'Lead', 'color': '#c2410c'},
    'claude': {'name': 'Claude', 'role': 'Builder · code, writing, review', 'color': '#d97757'},
    'codex': {'name': 'Codex', 'role': 'Builder · code, images, shell checks', 'color': '#10a37f'},
}
STATUSES = ('held', 'asked', 'queued', 'working', 'done', 'failed', 'cancelled')
OPEN = ('held', 'asked', 'queued', 'working')  # held = an order waiting for the lead's OK
MAX_ATTACHMENT = 50 * 1024 * 1024

SCHEMA = '''
create table if not exists requests(
  id text primary key, sender text not null, recipient text not null, title text not null,
  body text not null default '', status text not null, cwd text, worker_pid integer,
  sender_session text, worker_session text, created text not null, updated text not null);
create table if not exists messages(
  seq integer primary key autoincrement, id text unique not null, request_id text,
  sender text not null, kind text not null, body text not null default '',
  session text, created text not null);
create table if not exists attachments(
  id text primary key, message_id text not null, path text not null, name text not null,
  mime text not null, size integer not null);
create index if not exists messages_request on messages(request_id);
create table if not exists projects(
  key text primary key, name text not null, root text not null, settings text not null default '{}',
  created text not null);
create table if not exists project_marks(key text primary key, cleared_at text);
create table if not exists watch(issue text primary key, at text not null);
create table if not exists nudges(id text primary key, rid text not null, body text not null, status text not null, created text not null);
create table if not exists agent_sessions(
  project text not null, provider text not null, session text not null, updated text not null,
  primary key(project, provider));
'''


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def short_id():
    return uuid.uuid4().hex[:8]


class Mailbox:
    def __init__(self, path=None):
        self.path = Path(path or paths.DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('pragma journal_mode=WAL')
        self.db.execute('pragma busy_timeout=10000')
        with self.db:
            self.db.executescript(SCHEMA)
            cols = {r[1] for r in self.db.execute('pragma table_info(messages)')}
            if 'project' not in cols:  # v1 databases: team-room posts gain a project
                self.db.execute('alter table messages add column project text')
            if 'channel' not in cols:  # v1.3: General / Discussion channels
                self.db.execute('alter table messages add column channel text')
            rcols = {r[1] for r in self.db.execute('pragma table_info(requests)')}
            if 'depth' not in rcols:  # v1.4: hand-off chains and the channel a lead's message came from
                self.db.execute('alter table requests add column depth integer not null default 0')
                self.db.execute('alter table requests add column channel text')
            if 'refereed' not in rcols:  # v1.5: a chain the referee already stepped into
                self.db.execute('alter table requests add column refereed integer not null default 0')
            if 'turns' not in {r[1] for r in self.db.execute('pragma table_info(agent_sessions)')}:
                self.db.execute('alter table agent_sessions add column turns integer not null default 0')

    @contextlib.contextmanager
    def tx(self):
        self.db.execute('begin immediate')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def close(self):
        self.db.close()

    # --- requests -------------------------------------------------------------
    def member_ids(self):
        from .members import display
        return set(display(self.saved_projects()))

    def ask(self, sender, recipient, title, body='', cwd=None, session=None, files=(), depth=0, channel=None, refereed=0):
        known = self.member_ids()
        if recipient not in known or sender not in known:
            raise ValueError(f'Unknown teammate; use one of {", ".join(sorted(known))}')
        if recipient == sender:
            raise ValueError('Ask someone else on the team')
        rid = short_id()
        with self.tx():
            self.db.execute('insert into requests(id,sender,recipient,title,body,status,cwd,worker_pid,sender_session,'
                            'worker_session,created,updated,depth,channel,refereed) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (rid, sender, recipient, title.strip(), body.strip(), 'asked', cwd, None, session, None, now(), now(),
                 depth, channel, int(bool(refereed))))
            self._message(rid, sender, 'request', body or title, session, files)
        return self.request(rid)

    def request(self, rid):
        row = self.db.execute('select * from requests where id=?', (rid,)).fetchone()
        if not row:
            raise KeyError(f'No request {rid}')
        return dict(row)

    def requests(self, recipient=None, open_only=False):
        sql, args = 'select * from requests where 1=1', []
        if recipient:
            sql += ' and recipient=?'
            args.append(recipient)
        if open_only:
            sql += " and status in ('held','asked','queued','working')"
        return [dict(r) for r in self.db.execute(sql + ' order by created desc', args)]

    def set_status(self, rid, status, by, note='', session=None, files=(), kind=None):
        if status not in STATUSES:
            raise ValueError(status)
        req = self.request(rid)
        with self.tx():
            self.db.execute('update requests set status=?, updated=? where id=?', (status, now(), rid))
            msg = self._message(rid, by, kind or status, note, session, files)
        return req | {'status': status}, msg

    def nudge(self, rid, body):
        """A note from the lead for a request that is already running: the worker hands it to the agent mid-run."""
        nid = short_id()
        with self.tx():
            self.db.execute('insert into nudges(id, rid, body, status, created) values(?,?,?,?,?)', (nid, rid, body, 'pending', now()))
        return nid

    def take_nudges(self, rid):
        """Pending notes for a request, marked delivered. Returns [(id, body)]."""
        with self.tx():
            rows = self.db.execute("select id, body from nudges where rid=? and status='pending' order by created", (rid,)).fetchall()
            self.db.executemany("update nudges set status='delivered' where id=?", [(r[0],) for r in rows])
        return [(r[0], r[1]) for r in rows]

    def nudge_status(self, nid, status):
        with self.tx():
            self.db.execute('update nudges set status=? where id=?', (status, nid))

    def flag(self, issue):
        """Record something the supervisor did, once. True the first time."""
        with self.tx():
            cur = self.db.execute('insert or ignore into watch(issue, at) values(?,?)', (issue, now()))
        return cur.rowcount == 1

    def flags_since(self, prefix, since):
        return self.db.execute('select count(*) from watch where issue like ? and at > ?', (prefix + '%', since)).fetchone()[0]

    def link(self, rid, **fields):
        allowed = {'worker_pid', 'worker_session', 'sender_session'}
        with self.tx():
            for key, value in fields.items():
                if key in allowed:
                    self.db.execute(f'update requests set {key}=?, updated=? where id=?', (value, now(), rid))

    # --- messages -------------------------------------------------------------
    def say(self, sender, body, rid=None, session=None, files=(), kind='message', project=None, channel=None):
        if rid:
            self.request(rid)
        with self.tx():
            return self._message(rid, sender, kind, body, session, files, project, channel)

    def _message(self, rid, sender, kind, body, session, files, project=None, channel=None):
        mid = short_id()
        self.db.execute('insert into messages(id,request_id,sender,kind,body,session,created,project,channel) values(?,?,?,?,?,?,?,?,?)',
            (mid, rid, sender, kind, body or '', session, now(), project, channel))
        for f in files:
            p = Path(f).resolve()
            if not p.is_file():
                raise FileNotFoundError(f'Attachment not found: {f}')
            if p.stat().st_size > MAX_ATTACHMENT:
                raise ValueError(f'Attachment over 50 MB: {f}')
            self.db.execute('insert into attachments values(?,?,?,?,?,?)', (short_id(), mid, str(p), p.name,
                mimetypes.guess_type(p.name)[0] or 'application/octet-stream', p.stat().st_size))
        return mid

    def messages(self, after=0, rid=None, limit=500):
        sql, args = 'select * from messages where seq>?', [after]
        if rid:
            sql += ' and request_id=?'
            args.append(rid)
        rows = [dict(r) for r in self.db.execute(sql + ' order by seq desc limit ?', args + [limit])][::-1]
        files = {}
        if rows:
            marks = ','.join('?' * len(rows))
            for a in self.db.execute(f'select * from attachments where message_id in ({marks})', [r['id'] for r in rows]):
                files.setdefault(a['message_id'], []).append({k: a[k] for k in ('id', 'name', 'mime', 'size')})
        for r in rows:
            r['files'] = files.get(r['id'], [])
        return rows

    # --- one ongoing chat per project and agent ---------------------------------
    # (the provider column holds the member id: "claude", "codex", "codex-designer", ...)
    def agent_session(self, project, member):
        row = self.db.execute('select session, turns from agent_sessions where project=? and provider=?', (project, member)).fetchone()
        return (row[0], row[1]) if row else (None, 0)

    def remember_session(self, project, member, session, turns=0):
        with self.tx():
            self.db.execute('insert or replace into agent_sessions(project,provider,session,updated,turns) values(?,?,?,?,?)',
                            (project, member, session, now(), turns))

    def forget_session(self, project, provider):
        with self.tx():
            self.db.execute('delete from agent_sessions where project=? and provider=?', (project, provider))

    def agent_sessions(self):
        return [dict(r) for r in self.db.execute('select * from agent_sessions')]

    # --- projects created or set up in Team Chat -------------------------------
    def save_project(self, key, name, root, settings):
        with self.tx():
            self.db.execute('insert into projects values(?,?,?,?,?) on conflict(key) do update set '
                            'name=excluded.name, root=excluded.root, settings=excluded.settings',
                            (key, name, root, json.dumps(settings, ensure_ascii=False), now()))

    def project(self, key):
        row = self.db.execute('select * from projects where key=?', (key,)).fetchone()
        return dict(row) | {'settings': json.loads(row['settings'])} if row else None

    def saved_projects(self):
        return [dict(r) | {'settings': json.loads(r['settings'])} for r in self.db.execute('select * from projects')]

    # --- starting a project's chat fresh ------------------------------------------
    def cleared(self):
        return {r['key']: r['cleared_at'] for r in self.db.execute('select * from project_marks') if r['cleared_at']}

    def start_fresh(self, key):
        """Hide what came before (still recoverable) and give every member a new chat next time."""
        with self.tx():
            self.db.execute('insert or replace into project_marks values(?,?)', (key, now()))
            self.db.execute('delete from agent_sessions where project=?', (key,))

    def delete_history(self, key, request_ids):
        """Permanently remove a project's Team Chat messages and requests. Files on disk are not touched."""
        with self.tx():
            ids = list(request_ids)
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ','.join('?' * len(chunk))
                self.db.execute(f'delete from attachments where message_id in (select id from messages where request_id in ({marks}))', chunk)
                self.db.execute(f'delete from messages where request_id in ({marks})', chunk)
                self.db.execute(f'delete from requests where id in ({marks})', chunk)
            self.db.execute('delete from attachments where message_id in (select id from messages where project=? and request_id is null)', (key,))
            self.db.execute('delete from messages where project=? and request_id is null', (key,))
            self.db.execute('delete from agent_sessions where project=?', (key,))
            self.db.execute('delete from project_marks where key=?', (key,))

    def attached_paths(self):
        return {r[0] for r in self.db.execute('select path from attachments')}

    def attachment(self, aid):
        row = self.db.execute('select * from attachments where id=?', (aid,)).fetchone()
        return dict(row) if row else None


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2)
