"""Hand-offs between members without the `team` command.

Background agents can't run `team` (their sandboxes block the mailbox), so a member hands work on by ending
its reply with a block like:

```dispatch
[{"to": "codex-composer", "title": "Re-time the score", "body": "Move the 0:38 cue to 0:36 ..."}]
```

Crewroom reads the block after the turn and files the requests. If the project has a coordinator (the
"Producer"), orders from everyone else go to the coordinator first, who sharpens them and picks the member
whose roles fit; only the coordinator's own dispatches reach the members directly.
"""
import json
import re
from pathlib import Path

from . import members as team

BLOCK = re.compile(r"```dispatch[ \t]*\r?\n(.*?)\r?\n?```", re.S)
POST = re.compile(r"```post[ \t]+#?(general|discussion)[ \t]*\r?\n(.*?)\r?\n?```", re.S)
ADD = re.compile(r"```add-member[ \t]*\r?\n(.*?)\r?\n?```", re.S)
MAX_ITEMS = 6
MAX_NEW_MEMBERS = 2

ADDING = '''
## Adding team members (only when the lead asked for it)
If the lead asked for a new teammate, add it with one block, then dispatch its first task if there is one:
```add-member
[{{"app": "claude" or "codex", "name": "<short name, e.g. 3D Designer>", "roles": ["<role — what it does>"], "model": ""}}]
```
Pick the app whose strengths fit (Codex: images, shell, builds; Claude: code, writing, review). New member ids are
"<app>-<name in lowercase-with-dashes>". At most {max} per reply. Never add members the lead did not ask for.
'''
MAX_DEPTH = 8  # member-to-member steps in one chain (hops through the coordinator are free); stops runaway loops

INSTRUCTIONS = '''
## Handing work to teammates
To give a teammate work, end your reply with one fenced block (no other text inside it):
```dispatch
[{{"to": "<member id>", "title": "<short task>", "body": "<goal, exact files and names, constraints, how to check>"}}]
```
Members you can hand to: {ids}. At most {max} orders. Only dispatch real, needed work.
To post in a project channel, add a block that starts with ```post #general (or ```post #discussion) and holds the message.
Never run the `team` command yourself: it is blocked in background work; these blocks do the same job.
'''

REFEREE_EXTRA = 3  # hand-offs a chain gets after the referee has sorted it

REFEREE = '''
## You are this project's referee
A hand-off chain ran long, so its pending orders came to you instead of the members. Stop loops and waste:
- Drop orders that repeat earlier work, bounce work back and forth, or aren't needed for the lead's goal.
- Merge overlapping orders into one clear brief per member; do small fixes yourself.
- Dispatch only what is still needed (the chain gets a few more hand-offs after you), and say briefly what you dropped and why.
'''

SUPERVISOR = '''
## You are this project's supervisor
Crewroom sends you work that went wrong: a failed order, a retry that failed too, or a run that went silent.
Read the log, find the cause, then fix it yourself if small, or dispatch one corrected order (straight to the member,
not through the coordinator), or post in #general what the lead must decide. Keep #general updates to one or two lines.
'''

COORDINATOR = '''
## You are this project's coordinator (Producer)
- Messages from the lead and orders from other members come to you. Reply to the lead briefly and plainly.
- Turn each order into a clear brief: goal, exact files and names, constraints, how to check it.
- Send it to the member whose roles fit best (see the team list); split mixed orders; drop duplicates.
- Do the small things yourself (answers, notes, file edits); dispatch work that needs another member's skills.
'''


def split(text):
    """Return (text without dispatch blocks, list of orders, error or None)."""
    orders, error = [], None
    for m in BLOCK.finditer(text or ''):
        try:
            data = json.loads(m.group(1))
            data = data if isinstance(data, list) else [data]
            orders += [d for d in data if isinstance(d, dict)]
        except ValueError as e:
            error = f'Could not read a dispatch block: {e}'
    clean = BLOCK.sub('', text or '').strip()
    return clean, orders, error


def prompt_section(settings, member):
    ids = [f"`{m['id']}` ({m['name']}: {'; '.join(m.get('roles') or [])[:90]})"
           for m in team.team(settings) if m['id'] != member['id']]
    if not ids:
        return ''
    text = INSTRUCTIONS.format(ids=', '.join(ids), max=MAX_ITEMS)
    if settings.get('coordinator') == member['id']:
        text += COORDINATOR
    if settings.get('referee') == member['id']:
        text += REFEREE
    if settings.get('supervisor') == member['id']:
        text += SUPERVISOR
        return text
    if can_add(settings, member, None):
        text += ADDING.format(max=MAX_NEW_MEMBERS)
    elif settings.get('coordinator'):
        text += f"Your orders first go to the coordinator (`{settings['coordinator']}`), who refines and routes them.\n"
    return text


def can_add(settings, member, req):
    """The coordinator may add members; so may anyone working directly on the lead's own message."""
    return settings.get('coordinator') == member['id'] or bool(req and req.get('sender') == 'human')


def add_members(mb, req, member, settings, text, project):
    """Apply add-member blocks. Returns (text without them, notes, updated settings)."""
    blocks = list(ADD.finditer(text or ''))
    if not blocks:
        return text, [], settings
    text = ADD.sub('', text).strip()
    if not can_add(settings, member, req):
        return text, ['Ignored a request to add members: only the coordinator, or a member working on the lead\'s message, can do that.'], settings
    wanted = []
    for b in blocks:
        try:
            data = json.loads(b.group(1))
            wanted += [d for d in (data if isinstance(data, list) else [data]) if isinstance(d, dict)]
        except ValueError as e:
            return text, [f'Could not read an add-member block: {e}'], settings
    p = mb.project(project)
    if not p:
        return text, ['Members can only be added to a project set up in Crewroom (Edit team).'], settings
    from . import setup
    current = team.team(p['settings'])
    try:
        merged = team.clean(current + wanted[:MAX_NEW_MEMBERS], None)
    except ValueError as e:
        return text, [f'Could not add members: {e}'], settings
    added = [m for m in merged if m['id'] not in {c['id'] for c in current}]
    new_settings = p['settings'] | {'members': merged}
    mb.save_project(p['key'], p['name'], p['root'], new_settings)
    setup.write_team_files(Path(p['root']), p['name'], new_settings, new_settings.get('shared') or {'codex': [], 'claude': []}, link=False)
    for m in added:
        mb.say(member['id'], f"Added **{m['name']}** (`{m['id']}`, {team.APPS[m['app']]['name']}) to the team: "
               f"{'; '.join(m['roles'])}. Change or remove it in **Edit team**.", project=project, channel='general')
    return text, [f"Added {', '.join(m['name'] for m in added)} to the team."] if added else [], new_settings


def posts(text):
    """Return (text without post blocks, [(channel, message)])."""
    found = [(m.group(1), m.group(2).strip()) for m in POST.finditer(text or '')]
    return POST.sub('', text or '').strip(), [f for f in found if f[1]]


def handle(mb, req, member, settings, final, start, project=None):
    """File the orders and channel posts found in `final`. Returns (text to show, list of notes)."""
    final, add_notes, settings = add_members(mb, req, member, settings, final, project)
    final, said = posts(final)
    for channel, message in said[:3]:
        mb.say(member['id'], message[:20000], project=project, channel=channel)
    clean, orders, error = split(final)
    notes = add_notes + ([error] if error else [])
    if not orders:
        return clean or final, notes
    ids = {m['id'] for m in team.team(settings)}
    coordinator = settings.get('coordinator') if settings.get('coordinator') in ids else None
    # The supervisor's fixes go straight to the member; everyone else's orders go through the coordinator.
    via_coordinator = bool(coordinator and member['id'] not in (coordinator, settings.get('supervisor')))
    # Sending orders to the coordinator for routing doesn't lengthen the chain; real hand-offs do.
    referee = settings.get('referee') if settings.get('referee') in ids else None
    refereed = bool(req.get('refereed')) or member['id'] == referee
    depth = (req.get('depth') or 0) + (0 if via_coordinator else 1)
    if member['id'] == referee and req.get('depth', 0) >= MAX_DEPTH:
        depth = MAX_DEPTH - REFEREE_EXTRA + 1  # the referee's sorted orders get a few more steps
    hold = depth > MAX_DEPTH
    valid = []
    for o in orders[:MAX_ITEMS]:
        to, title = str(o.get('to', '')).strip(), str(o.get('title', '')).strip()[:200]
        if to not in ids or to == member['id'] or not title:
            notes.append(f'Skipped an order for `{to or "?"}`: unknown member, self, or no title.')
            continue
        valid.append({'to': to, 'title': title, 'body': str(o.get('body', ''))[:20000]})
    if not valid:
        return clean, notes
    if hold and referee and not refereed and member['id'] != referee:
        listing = '\n'.join(f"{i + 1}. **{o['title']}** → wanted: `{o['to']}`\n\n{o['body']}" for i, o in enumerate(valid))
        new = mb.ask(member['id'], referee, f"Referee: long hand-off chain from {member['name']}",
                     f"This chain already has {MAX_DEPTH} hand-offs. {member['name']} wants to send these orders. Decide what is "
                     f"really needed, merge or drop the rest, then dispatch.\n\n{listing}", cwd=req['cwd'], depth=MAX_DEPTH, refereed=1)
        start(new['id'])
        names = team.display(mb.saved_projects())
        return clean, notes + [f"Long hand-off chain: {len(valid)} order(s) went to the referee, {names.get(referee, {}).get('name', referee)}, to sort out."]
    if hold:  # never drop work: park it for the lead to send or dismiss
        for o in valid:
            new = mb.ask(member['id'], o['to'], o['title'], o['body'], cwd=req['cwd'], depth=depth, refereed=1)
            mb.set_status(new['id'], 'held', member['id'],
                          f'Held for your OK: this chain already has {MAX_DEPTH} hand-offs. Press **Send** to start it or **Dismiss**.',
                          kind='note')
        return clean, notes + [f"{len(valid)} order(s) are waiting for your OK (long hand-off chain). Find them under Requests → Open."]
    if via_coordinator:
        listing = '\n'.join(f"{i + 1}. **{o['title']}** → suggested: `{o['to']}`\n\n{o['body']}" for i, o in enumerate(valid))
        new = mb.ask(member['id'], coordinator, f"Orders from {member['name']}: refine and route",
                     f"{member['name']} wants this work done. Sharpen each order and dispatch it to the best-fitting member "
                     f"(their suggestion is only a hint).\n\n{listing}", cwd=req['cwd'], depth=depth, refereed=refereed)
        start(new['id'])
        return clean, notes + [f"Sent {len(valid)} order(s) to the coordinator to refine and route."]
    for o in valid:
        new = mb.ask(member['id'], o['to'], o['title'], o['body'], cwd=req['cwd'], depth=depth, refereed=refereed)
        if team.is_manual(settings, o['to']):
            notes.append(f"**{o['title']}** waits in {o['to']}'s inbox (works in its own app).")
        else:
            start(new['id'])
    names = team.display(mb.saved_projects())
    return clean, notes + ['Handed off: ' + ', '.join(f"**{o['title']}** → {names.get(o['to'], {}).get('name', o['to'])}" for o in valid)]
