"""Team members. A project's team can hold any mix of agents: Claude, Codex, Cursor and Antigravity members
(e.g. three Codex designers and one Claude builder). Each member has a name, an app (see agents.py), roles
and a model, and keeps its own ongoing chat in the project.

Member ids are stable and always start with their app: "claude", "codex", "codex-designer", "cursor-reviewer", ...
"""
import re

from .agents import AGENTS, app_of  # noqa: F401  (app_of is part of this module's interface)

APPS = {a.id: {'name': a.name, 'color': a.color} for a in AGENTS.values()}
HUMAN = {'name': 'You', 'role': 'Lead', 'color': '#c2410c', 'app': 'human'}
DEFAULT_HUMAN_ROLE = 'Lead — sets goals and approves the results'
DEFAULT_FRESH_EVERY = 6
# Colour shades (hue turns, degrees) a member's avatar can take; 0 is the app's own colour.
HUES = [0, 45, 90, 150, 200, 250, 300]


def auto_hue(mid, taken=()):
    """The avatar's true colours for the first member of each app in a project (the avatars are characters: a
    tinted orange cat looks wrong); later members of the same app get the first free shade (stable per id)."""
    if mid in APPS or 0 not in taken:
        return 0
    start = sum(map(ord, mid)) % (len(HUES) - 1) + 1
    for i in range(len(HUES) - 1):
        h = HUES[(start - 1 + i) % (len(HUES) - 1) + 1]
        if h not in taken:
            return h
    return HUES[start]


def member_id(app, name):
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:30]
    return app if not slug or slug == app else f'{app}-{slug}'


def team(settings):
    """The member list of a project, upgrading the older {roles: {claude, codex}} format."""
    if settings.get('members'):
        return settings['members']
    out = []
    for app in ('claude', 'codex'):
        r = (settings.get('roles') or {}).get(app) or {}
        jobs = r.get('roles') or [x.strip() for x in str(r.get('role', '')).split(';') if x.strip()]
        out.append({'id': app, 'name': APPS[app]['name'], 'app': app, 'roles': jobs, 'model': r.get('model', '')})
    return out


def human_role(settings):
    return settings.get('humanRole') or ((settings.get('roles') or {}).get('human') or {}).get('role') or DEFAULT_HUMAN_ROLE


def display(saved_projects):
    """Everyone who can appear in the chat: you, the two base agents and every project member."""
    out = {'human': dict(HUMAN), 'claude': {'name': 'Claude', 'role': 'Builder · code, writing, review', 'color': APPS['claude']['color'], 'app': 'claude'},
           'codex': {'name': 'Codex', 'role': 'Builder · code, images, shell checks', 'color': APPS['codex']['color'], 'app': 'codex'}}
    for a in AGENTS.values():  # Cursor, Antigravity, ...: askable by their plain id too
        out.setdefault(a.id, {'name': a.name, 'role': a.blurb, 'color': a.color, 'app': a.id})
    for p in saved_projects:
        for m in team(p['settings']):
            out.setdefault(m['id'], {'name': m['name'], 'role': '; '.join(m.get('roles') or [])[:120],
                                     'color': APPS[m['app']]['color'], 'app': m['app'],
                                     'hue': m.get('hue', auto_hue(m['id']))})
            if m['id'] in APPS and m.get('hue'):
                out[m['id']]['hue'] = m['hue']
    return out


def find(settings, mid):
    """A member's full settings in a project; base members fall back to defaults."""
    for m in team(settings or {}):
        if m['id'] == mid:
            return m
    app = app_of(mid)
    if app == 'human':
        return None
    return {'id': mid, 'name': APPS[app]['name'] if mid == app else mid, 'app': app, 'roles': [], 'model': ''}


def clean(given, human):
    """Validate members sent by the window."""
    out, seen = [], set()
    for m in given or []:
        app = m.get('app')
        name = str(m.get('name') or '').strip()[:40]
        if app not in APPS or not name:
            continue
        mid = member_id(app, name)
        if mid in seen:
            raise ValueError(f'Two members are called "{name}"; give each a different name')
        seen.add(mid)
        jobs = [str(r).strip()[:200] for r in m.get('roles') or [] if str(r).strip()][:12]
        if not jobs:
            raise ValueError(f'Give {name} at least one role')
        try:
            hue = int(m['hue']) % 360 if m.get('hue') not in (None, '') else None
        except (TypeError, ValueError):
            hue = None
        if hue is None:
            hue = auto_hue(mid, {o['hue'] for o in out if o['app'] == app})
        out.append({'id': mid, 'name': name, 'app': app, 'roles': jobs, 'model': str(m.get('model') or '')[:60], 'hue': hue,
                    'manual': bool(m.get('manual')), 'shell': bool(m.get('shell')) and AGENTS[app].shell})
    if not out:
        raise ValueError('The team needs at least one member')
    if len(out) > 12:
        raise ValueError('Up to 12 members per project')
    return out


def mentions(text, settings):
    """Member ids @mentioned in text, by name ("@3D Designer") or id ("@claude-montage"), in order of appearance."""
    import re
    found = {}
    for m in team(settings or {}):
        for label in {m['name'], m['id']}:
            hit = re.search(r'(?<![\w@])@' + re.escape(label) + r'(?![\w-])', text or '', re.I)
            if hit:
                found[m['id']] = min(found.get(m['id'], hit.start()), hit.start())
    return sorted(found, key=found.get)


def is_manual(settings, mid):
    """A member that works in its own app (e.g. your open Claude Code chat): requests wait in its inbox."""
    return any(m['id'] == mid and m.get('manual') for m in team(settings or {}))


def roles_text(settings):
    lines = [f"- **You (the user)**: {human_role(settings)}"]
    for m in team(settings):
        model = f", model {m['model']}" if m.get('model') else ''
        jobs = m.get('roles') or []
        flags = (', works in its own app' if m.get('manual') else '') + (', runs commands' if m.get('shell') else '')
        head = f"- **{m['name']}** (`{m['id']}` · {APPS[m['app']]['name']}{model}{flags}): "
        lines.append(head + ('; '.join(jobs) if len(jobs) < 2 else '\n  - ' + '\n  - '.join(jobs)))
    return '\n'.join(lines)
