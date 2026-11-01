"""Create and configure team projects: folder, roles, models and skills shared between the agents.

Skills are shared per project, never globally: a Claude skill picked for Codex is copied into
<project>/.agents/skills (Codex reads it there) and a Codex skill picked for Claude into
<project>/.claude/skills. Roles are written to TEAM.md, which AGENTS.md and CLAUDE.md point to, so
every chat in the folder knows the team - including chats you start yourself in either app.
"""
import io
import json
import re
import shutil
import time
from pathlib import Path

from . import members as team, paths, projects

HOME = Path.home()
SKILL_DIRS = {
    'claude': [HOME / '.claude' / 'skills'],
    'codex': [HOME / '.agents' / 'skills', HOME / '.codex' / 'skills'],
}
PROJECT_SKILLS = {'claude': Path('.claude') / 'skills', 'codex': Path('.agents') / 'skills'}
CLAUDE_MODELS = [
    {'id': '', 'name': 'Default (your Claude setting)'},
    {'id': 'opus', 'name': 'Opus — most capable'},
    {'id': 'sonnet', 'name': 'Sonnet — fast and strong'},
    {'id': 'haiku', 'name': 'Haiku — quickest, light tasks'},
]
ROLE_PRESETS = [
    'Lead builder — writes and changes the code',
    'Designer — images, icons, illustrations and UI art',
    'Reviewer — reads changes, runs checks and tests, reports problems',
    'Writer — docs, copy, READMEs and release notes',
    'Researcher — looks things up and compares options',
    'Helper — whatever the team needs',
]
DEFAULT_ROLES = {
    'claude': {'roles': [ROLE_PRESETS[0], ROLE_PRESETS[2]], 'model': ''},
    'codex': {'roles': [ROLE_PRESETS[1], 'Checker — runs builds, tests and shell checks'], 'model': ''},
    'cursor': {'roles': [ROLE_PRESETS[0], 'Refactorer — tidies and restructures code'], 'model': ''},
    'antigravity': {'roles': [ROLE_PRESETS[4], ROLE_PRESETS[2]], 'model': ''},
}
for _r in DEFAULT_ROLES.values():
    _r['role'] = '; '.join(_r['roles'])
MAX_SKILL_BYTES = 25 * 1024 * 1024
NAME_OK = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]{1,80}$')
_models_cache = {'at': 0, 'value': []}


# --- discovery -----------------------------------------------------------------
def _frontmatter(text):
    """Tiny YAML front-matter reader: `key: value` plus folded/literal (`>`, `|`) blocks."""
    meta, current = {}, None
    if text.startswith('---'):
        for line in text.split('---', 2)[1].splitlines():
            if current and (line.startswith((' ', '\t')) or not line.strip()):
                meta[current] = (meta[current] + ' ' + line.strip()).strip()
                continue
            current = None
            if ':' in line and not line.startswith((' ', '\t')):
                k, v = line.split(':', 1)
                v = v.strip()
                if v in ('>', '|', '>-', '|-'):
                    current, v = k.strip(), ''
                meta[k.strip()] = v.strip('"\'')
    return meta


def list_skills():
    """Installed skills per agent: [{name, description}] (first copy wins if a name repeats)."""
    out = {}
    for agent, dirs in SKILL_DIRS.items():
        seen = {}
        for d in dirs:
            if not d.is_dir():
                continue
            for skill in sorted(d.iterdir()):
                md = skill / 'SKILL.md'
                if skill.name in seen or not md.is_file():
                    continue
                try:
                    meta = _frontmatter(md.read_text(encoding='utf-8', errors='replace')[:4000])
                except OSError:
                    continue
                seen[skill.name] = {'name': skill.name, 'description': meta.get('description', '')[:240],
                                    'path': str(skill)}
        out[agent] = list(seen.values())
    return out


def codex_models():
    if time.time() - _models_cache['at'] < 600 and _models_cache['value']:
        return _models_cache['value']
    models = []
    try:
        from .worker import CodexChat
        chat = CodexChat(io.StringIO())
        try:
            models = [{'id': m.get('id') or m.get('model'), 'name': m.get('displayName') or m.get('id')}
                      for m in chat.call('model/list', {'limit': 40}, timeout=30).get('data', [])]
        finally:
            chat.close()
    except Exception:
        cache = paths.CODEX_HOME / 'models_cache.json'
        if cache.exists():
            data = json.loads(cache.read_text(encoding='utf-8'))
            rows = data.get('models', data) if isinstance(data, dict) else data
            models = [{'id': m.get('slug'), 'name': m.get('display_name') or m.get('slug')} for m in rows
                      if isinstance(m, dict) and m.get('slug') and 'review' not in m.get('slug', '')]
    models = [{'id': '', 'name': 'Default (your Codex setting)'}] + [m for m in models if m['id']]
    _models_cache.update(at=time.time(), value=models)
    return models


def cli_models(app):
    """Cursor lists hundreds of variants (each model x effort x fast); keep the picker short."""
    from . import agents
    found = agents.models(app)
    if app == 'cursor':
        found = [m for m in found if not m['id'].endswith('-fast')][:40]
    return found


# --- creating / updating ---------------------------------------------------------
def create(body, mb):
    name = str(body.get('name', '')).strip()
    existing = str(body.get('existing', '')).strip().strip('"')
    if existing:
        root = Path(existing)
        if not root.is_dir():
            raise ValueError(f'Folder not found: {existing}')
        name = name or root.name
    else:
        parent = Path(str(body.get('parent', '')).strip().strip('"') or HOME / 'Desktop')
        if not NAME_OK.match(name) or name.strip('. ') != name:
            raise ValueError('Give the project a folder-friendly name (no \\ / : * ? " < > |)')
        if not parent.is_dir():
            raise ValueError(f'Parent folder not found: {parent}')
        root = parent / name
        if root.exists():
            raise ValueError(f'"{root}" already exists. Choose "Use an existing folder" to set it up instead.')
        root.mkdir()
    root = root.resolve()
    key = projects.key(root)
    settings = configure(root, name, body, new_folder=not existing)
    mb.save_project(key, name, str(root), settings)
    projects.set_saved_roots(mb.saved_projects())
    return {'key': key, 'name': name, 'root': str(root), 'settings': settings}


def update(body, mb):
    p = mb.project(str(body.get('key', '')))
    if not p:
        raise ValueError('Unknown project')
    settings = configure(Path(p['root']), p['name'], body, new_folder=False)
    mb.save_project(p['key'], p['name'], p['root'], settings)
    return {'key': p['key'], 'name': p['name'], 'root': p['root'], 'settings': settings}


def configure(root, name, body, new_folder):
    given = body.get('members') or [{'app': a, 'name': team.APPS[a]['name'], 'roles': DEFAULT_ROLES[a]['roles'],
                                     'model': ''} for a in ('claude', 'codex')]
    settings = {'members': team.clean(given, None),
                'humanRole': str(body.get('humanRole') or team.DEFAULT_HUMAN_ROLE)[:300],
                'freshEvery': max(0, min(50, int(body.get('freshEvery', team.DEFAULT_FRESH_EVERY) or 0)))}
    coordinator = str(body.get('coordinator') or '')
    settings['coordinator'] = coordinator if coordinator in {m['id'] for m in settings['members']} else ''
    referee = str(body.get('referee') or '')
    settings['referee'] = referee if referee in {m['id'] for m in settings['members']} else ''
    supervisor = str(body.get('supervisor') or '')
    settings['supervisor'] = supervisor if supervisor in {m['id'] for m in settings['members']} else ''
    settings['shared'] = share_skills(root, body.get('share') or {})
    write_team_files(root, name, settings, settings['shared'], link=new_folder or body.get('linkFiles', True))
    return settings


def share_skills(root, share):
    """Copy the chosen skills into the project's skill folder for the *other* agent."""
    installed = list_skills()
    result = {'codex': [], 'claude': []}
    for target, source in (('codex', 'claude'), ('claude', 'codex')):
        wanted = set(share.get(target) or [])
        dest_root = root / PROJECT_SKILLS[target]
        for skill in installed[source]:
            if skill['name'] not in wanted:
                continue
            src, dest = Path(skill['path']), dest_root / skill['name']
            if dest.exists():
                result[target].append(skill['name'])
                continue
            if sum(f.stat().st_size for f in src.rglob('*') if f.is_file()) > MAX_SKILL_BYTES:
                continue
            dest_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns('node_modules', '.git', '__pycache__'))
            result[target].append(skill['name'])
    return result


roles_text = team.roles_text


def write_team_files(root, name, settings, shared, link=True):
    team = f'''# {name} — team

This project is worked on by a small team through **Crewroom** (desktop app).

{roles_text(settings)}

To hand work to a teammate, use the **team-chat** skill: `team ask <member id> "Title" --run`
(member ids are shown in backticks above). Ask the teammate whose roles fit; check results before telling
the user it is done. Talk in the team channels with `team say --channel general|discussion "..."`.
'''
    if shared['codex'] or shared['claude']:
        team += '\n## Skills shared in this project\n'
        if shared['codex']:
            team += f"\nClaude skills available to Codex (in `.agents/skills`): {', '.join(shared['codex'])}\n"
        if shared['claude']:
            team += f"\nCodex skills available to Claude (in `.claude/skills`): {', '.join(shared['claude'])}\n"
    (root / 'TEAM.md').write_text(team, encoding='utf-8')
    pointer = 'This folder is a Crewroom project. Read TEAM.md for who does what and how to hand work to a teammate.\n'
    for fname in ('AGENTS.md', 'CLAUDE.md'):
        f = root / fname
        if not f.exists():
            f.write_text(f'# {name}\n\n{pointer}', encoding='utf-8')
        elif link and 'TEAM.md' not in f.read_text(encoding='utf-8', errors='replace'):
            with open(f, 'a', encoding='utf-8') as out:
                out.write(f'\n\n## Team\n\n{pointer}')
