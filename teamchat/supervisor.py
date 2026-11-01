"""The supervisor: every minute, look for work that went wrong and fix it.

Mechanical problems are fixed here without spending tokens (a worker that died, an order that never started,
one retry of a failed order). What needs judgment goes to the project's supervisor member, an agent that
diagnoses it and re-briefs, re-routes or asks the lead.
"""
import threading
import time
from datetime import datetime, timedelta, timezone

from . import members as team, paths, projects, system, worker
from .db import Mailbox

INTERVAL = 60
LOST_AFTER = 120                     # an order whose worker died before starting it
SILENT_AFTER = worker.TIMEOUT + 600  # a run past the worker's own time limit is stuck
MANUAL_AFTER = 600                   # tell the lead an order waits on a member that works in its own app
RECENT = 1800                        # only failures this fresh are retried (never old history)
MAX_ESCALATIONS = 6                  # per project per hour, so a bad day can't burn tokens

BRIEF = '''Something went wrong with a request in this project. You are the supervisor: find the cause and get the work done.

**Request {id}:** {title}
**For:** {recipient} · **asked by:** {sender}
**Problem:** {problem}

**The original order:**

{body}

**Last lines of its log:**

```text
{tail}
```

Then do one of these:
- Fix it yourself if it is small (a wrong path, a missing folder, a typo in a file).
- Dispatch a corrected, clearer order to the same member or a better-fitting one. Say what changed.
- If it needs the lead (a login, quota, a risky step, a real decision), post it in #general and stop.
Do not repeat the same order unchanged: it already failed.'''


alive = system.alive


def age(ts):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()


def tail(rid, size=1500):
    log = paths.LOGS / f'{rid}.log'
    return log.read_text(encoding='utf-8', errors='replace')[-size:].strip() if log.exists() else '(no log)'


def check(mb, start=worker.start):
    """One pass. Returns a list of what was done (for tests and the log)."""
    saved = mb.saved_projects()
    projects.set_saved_roots(saved)
    by_key = {p['key']: p for p in saved}
    names = team.display(saved)
    reqs = mb.requests()
    did = []
    for r in reqs:
        rid, who, status = r['id'], r['recipient'], r['status']
        key = projects.root_of(r['cwd'])[0] if r['cwd'] else None
        settings = (by_key.get(key) or {}).get('settings') or {}
        name = names.get(who, {}).get('name', who)
        if status in ('working', 'queued') and r['worker_pid'] and not alive(r['worker_pid']):
            if mb.flag(f'restart:{rid}'):
                mb.set_status(rid, 'asked', who, f'Supervisor: {name}\'s worker stopped without finishing, so I restarted it.', kind='note')
                start(rid)
                did.append(('restarted', rid))
            else:
                mb.set_status(rid, 'failed', who, f'**Could not finish:** the worker stopped twice without finishing.\n\n```text\n{tail(rid)}\n```')
                did.append(('failed', rid))
        elif status == 'asked' and r['worker_pid'] and not alive(r['worker_pid']) and age(r['updated']) > LOST_AFTER \
                and not team.is_manual(settings, who):
            if mb.flag(f'restart:{rid}'):
                mb.say(who, 'Supervisor: this order never started, so I started it.', rid=rid, kind='note')
                start(rid)
                did.append(('started', rid))
        elif status == 'asked' and team.is_manual(settings, who) and age(r['updated']) > MANUAL_AFTER:
            if mb.flag(f'manual:{rid}'):
                mb.say(who, f'Supervisor: this waits for **{name}**, who works in its own app. Open that app and ask it to '
                       f'check its Crewroom inbox, or untick "Works in my own app" in **Edit team** so it runs in the background.',
                       rid=rid, kind='note')
                did.append(('manual', rid))
        elif status == 'working' and age(r['updated']) > SILENT_AFTER:
            if mb.flag(f'silent:{rid}'):
                did += escalate(mb, r, key, settings, names, f'{name} has been working for over {SILENT_AFTER // 60} minutes with no result.', start)
        elif status == 'failed' and age(r['updated']) < RECENT:
            later = any(o['recipient'] == who and o['title'] == r['title'] and o['created'] > r['created'] for o in reqs)
            if later:
                continue  # someone already tried again
            if mb.flag(f'retry:{rid}'):
                new = mb.ask(r['sender'], who, r['title'], r['body'], cwd=r['cwd'], session=r['sender_session'],
                             depth=r['depth'] or 0, channel=r['channel'], refereed=r['refereed'])
                mb.flag(f'retry:{new["id"]}')  # one automatic retry per order, not a chain of them
                mb.say(who, f'Supervisor: trying once more as request `{new["id"]}`.', rid=rid, kind='note')
                start(new['id'])
                did.append(('retried', rid))
            elif mb.flag(f'escalate:{key}:{rid}'):
                did += escalate(mb, r, key, settings, names, f'It failed, and so did one automatic retry.', start)
    return did


def escalate(mb, r, key, settings, names, problem, start):
    sup = settings.get('supervisor')
    members = {m['id'] for m in team.team(settings)}
    if sup not in members or sup == r['recipient']:
        mb.say(r['recipient'], f'Supervisor: {problem} This needs you (no supervisor member is set for this project).', rid=r['id'], kind='note')
        return [('told-lead', r['id'])]
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec='seconds')
    if mb.flags_since(f'escalate:{key}:', since) > MAX_ESCALATIONS:
        mb.say(r['recipient'], f'Supervisor: {problem} Too many problems this hour, so I am leaving this one for you.', rid=r['id'], kind='note')
        return [('told-lead', r['id'])]
    nm = lambda i: names.get(i, {}).get('name', i)
    new = mb.ask(r['recipient'], sup, f'Supervisor: fix "{r["title"][:80]}"',
                 BRIEF.format(id=r['id'], title=r['title'], recipient=nm(r['recipient']), sender=nm(r['sender']), problem=problem,
                              body=r['body'] or '(no details)', tail=tail(r['id'])),
                 cwd=r['cwd'], depth=r['depth'] or 0, refereed=1)
    mb.flag(f'retry:{new["id"]}')
    mb.flag(f'escalate:{key}:{new["id"]}')  # the supervisor's own work is never escalated to itself
    mb.say(sup, f'Looking into **{r["title"]}** ({nm(r["recipient"])}): {problem}', project=key, channel='general')
    start(new['id'])
    return [('escalated', r['id'])]


def run_forever():
    while True:
        time.sleep(INTERVAL)
        mb = None
        try:
            mb = Mailbox()
            for what, rid in check(mb):
                print(f'supervisor: {what} {rid}', flush=True)
        except Exception as error:  # the watchdog must never take the window down
            print(f'supervisor error: {error}', flush=True)
        finally:
            if mb:
                mb.close()


def start_thread():
    threading.Thread(target=run_forever, name='supervisor', daemon=True).start()
