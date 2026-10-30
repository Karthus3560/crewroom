"""`team` command used by Claude, Codex and you to talk through the shared mailbox."""
import argparse
import os
import sys

from . import projects, transcripts, worker
from .db import Mailbox
from .members import app_of, display

_names = {}


def nm(mid):
    return _names.get(mid, {}).get('name', mid)


def whoami(explicit=None):
    if explicit:
        return explicit
    if os.environ.get('TEAMCHAT_AS'):
        return os.environ['TEAMCHAT_AS']
    if os.environ.get('CLAUDECODE') or os.environ.get('CLAUDE_CODE_SESSION_ID'):
        return 'claude'
    if any(k.startswith('CODEX_') and k != 'CODEX_HOME' for k in os.environ):
        return 'codex'
    return 'human'


def my_session(me):
    if app_of(me) == 'claude':
        return os.environ.get('CLAUDE_CODE_SESSION_ID')
    if app_of(me) == 'codex':
        return transcripts.current_codex_session(os.getcwd())
    return None


def show(mb, rid):
    req = mb.request(rid)
    print(f"[{req['id']}] {nm(req['sender'])} -> {nm(req['recipient'])} · {req['status']}")
    print(f"Title: {req['title']}")
    if req['cwd']:
        print(f"Folder: {req['cwd']}")
    for m in mb.messages(rid=rid):
        print(f"\n--- {nm(m['sender'])} · {m['kind']} · {m['created']}")
        print(m['body'])
        for f in m['files']:
            print(f"  file: {mb.attachment(f['id'])['path']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog='team', description='Talk to your AI teammates through Team Chat.')
    ap.add_argument('--as', dest='me', help='who is speaking: claude, codex or your member id (auto-detected)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('ask', help='ask a teammate to do something')
    s.add_argument('to', help='member id: claude, codex, or a project member like codex-designer (see `team roles`)')
    s.add_argument('title')
    s.add_argument('--body', default='', help='details, Markdown welcome')
    s.add_argument('--cwd', default=None, help='folder the work belongs in (default: current folder)')
    s.add_argument('--file', action='append', default=[], help='attach a file (repeatable)')
    s.add_argument('--run', action='store_true', help='start the teammate now in the background')

    s = sub.add_parser('inbox', help='open requests addressed to me')
    s.add_argument('--all', action='store_true', help='include finished requests')

    for name, text in (('take', 'mark a request as being worked on'), ('done', 'finish a request'),
                       ('fail', 'report a request could not be finished'), ('reply', 'reply on a request')):
        s = sub.add_parser(name, help=text)
        s.add_argument('id')
        s.add_argument('message', nargs='?', default='')
        s.add_argument('--file', action='append', default=[])

    s = sub.add_parser('say', help='post to a team channel')
    s.add_argument('message')
    s.add_argument('--channel', choices=['general', 'discussion'], default='general')
    s.add_argument('--cwd', default=None, help='project folder (default: current folder)')
    s.add_argument('--file', action='append', default=[])

    s = sub.add_parser('wait', help='block until a request is done (run in the background)')
    s.add_argument('id')
    s.add_argument('--timeout', type=int, default=3600)

    s = sub.add_parser('show', help='show a request and its messages')
    s.add_argument('id')

    sub.add_parser('list', help='all recent requests')
    s = sub.add_parser('roles', help="who does what in this folder's project")
    s.add_argument('--cwd', default=None)
    sub.add_parser('whoami', help='print detected identity and session')
    s = sub.add_parser('_work')
    s.add_argument('id')

    a = ap.parse_args(argv)
    if a.cmd == '_work':
        return worker.work(a.id)
    me = whoami(a.me)
    mb = Mailbox()
    _names.update(display(mb.saved_projects()))
    try:
        if a.cmd == 'whoami':
            print(f'{me} session={my_session(me)}')
        elif a.cmd == 'ask':
            cwd = os.path.abspath(a.cwd or os.getcwd())
            req = mb.ask(me, a.to, a.title, a.body, cwd=cwd, session=my_session(me), files=a.file)
            print(f"Asked {nm(a.to)}: request {req['id']}")
            saved = mb.project(projects.root_of(cwd)[0])
            from .members import is_manual
            if a.run and is_manual(saved and saved['settings'], a.to):
                print(f"{nm(a.to)} works in its own app, so the request waits in its inbox (team inbox).")
            elif a.run and app_of(a.to) != 'human':
                worker.start(req['id'])
                print(f"{nm(a.to)} is working on it in the background.")
                print(f"To be told when it is done: team wait {req['id']}  (run it as a background command)")
            elif app_of(a.to) != 'human':
                print(f"It waits in {nm(a.to)}'s inbox (team inbox) until picked up.")
        elif a.cmd == 'inbox':
            rows = mb.requests(recipient=me, open_only=not a.all)
            if not rows:
                print('Inbox empty.')
            for r in rows:
                print(f"[{r['id']}] {r['status']:<8} from {nm(r['sender'])}: {r['title']}  ({r['cwd'] or ''})")
        elif a.cmd in ('take', 'done', 'fail', 'reply'):
            status = {'take': 'working', 'done': 'done', 'fail': 'failed'}.get(a.cmd)
            if status:
                mb.set_status(a.id, status, me, a.message, session=my_session(me), files=a.file)
            else:
                mb.say(me, a.message, rid=a.id, session=my_session(me), files=a.file, kind='reply')
            print(f'Posted to request {a.id}.')
        elif a.cmd == 'say':
            projects.set_saved_roots(mb.saved_projects())
            key = projects.root_of(os.path.abspath(a.cwd or os.getcwd()))[0]
            mb.say(me, a.message, session=my_session(me), files=a.file, project=key, channel=a.channel)
            print(f'Posted to #{a.channel}.')
        elif a.cmd == 'wait':
            mb.close()
            req = worker.wait(a.id, a.timeout)
            mb = Mailbox()
            show(mb, a.id)
            return 0 if req['status'] == 'done' else 1 if req['status'] in ('failed', 'cancelled') else 2
        elif a.cmd == 'show':
            show(mb, a.id)
        elif a.cmd == 'roles':
            from .setup import roles_text
            projects.set_saved_roots(mb.saved_projects())
            key, name, root = projects.root_of(os.path.abspath(a.cwd or os.getcwd()))
            p = mb.project(key)
            if not p:
                print(f'"{name}" has no team set. Members: claude (builds and reviews), codex (images, shell checks).')
            else:
                print(f'Team for {name} ({root}):')
                print(roles_text(p['settings']))
                shared = p['settings'].get('shared', {})
                if shared.get('codex') or shared.get('claude'):
                    print(f"Shared skills -> Codex: {', '.join(shared.get('codex', [])) or '-'}; -> Claude: {', '.join(shared.get('claude', [])) or '-'}")
        elif a.cmd == 'list':
            for r in mb.requests()[:30]:
                print(f"[{r['id']}] {r['status']:<8} {nm(r['sender'])} -> {nm(r['recipient'])}: {r['title']}")
        return 0
    except (KeyError, ValueError, FileNotFoundError) as error:
        print(f'team: {error}', file=sys.stderr)
        return 2
    finally:
        mb.close()


if __name__ == '__main__':
    sys.exit(main())
