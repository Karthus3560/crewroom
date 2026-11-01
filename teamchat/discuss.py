"""Round-table discussions: the team talks a topic through in a channel, in turns, and ends with a decision.

The lead starts one by writing to the whole team in #discussion (with @team, or when the project's team room is set to
"Everyone"). Each member answers in turn, seeing what the others said before it, for a few rounds. Then the host (the
Producer, or else the first member) writes the Decision and dispatches any agreed work. Every turn is an ordinary
request, so it shows up in Requests, has a work log, and can be cancelled; a member that fails is skipped.
"""
import uuid
from datetime import datetime, timezone

from . import members as team
from .db import now

DEFAULT_ROUNDS = 2
MAX_ROUNDS = 3

TURN = '''[Round-table in #{channel} · round {round} of {rounds}]

The lead asked the team:

{topic}

{said}
It's your turn, {name}. Answer in 2 to 5 sentences, from your role ({roles}): agree, disagree, or add something the others
missed, and speak to teammates by name. This is a conversation: don't start work, edit files or dispatch orders now. If you
would do something, say what and why. Reply with just your answer: Crewroom posts it in #{channel} for everyone, so don't
post it yourself with `team say` and don't add a summary of what you did.'''

DECISION = '''[Round-table in #{channel} · decision]

The lead asked the team:

{topic}

{said}
You are hosting this round-table. Write the team's **Decision** for the lead in a few short bullet points: what the team
agreed, what it disagreed on, and any question only the lead can answer. If the lead asked for work and the team agreed on
it, dispatch clear orders to the members whose roles fit (a dispatch block); if not, don't. Reply with just the decision:
Crewroom posts it in #{channel}, so don't post it yourself with `team say`.'''


def quote(text):
    return '> ' + (text or '').strip().replace('\n', '\n> ')


def transcript(mb, d, names):
    """What was said since the round-table began; the lead can chime in mid-way and everyone sees it."""
    said = [m for m in mb.channel_messages(d['project'], d['channel'], since=d['started'], limit=40) if m.get('kind') != 'note']
    if said and said[0]['sender'] == 'human' and said[0]['body'].strip()[:4000] == d['topic']:
        said = said[1:]  # the topic itself is quoted above
    lines = [f"**{'The lead' if m['sender'] == 'human' else names.get(m['sender'], {}).get('name', m['sender'])}:** "
             f"{' '.join(m['body'].split())[:700]}" for m in said]
    return ('What the team has said so far:\n\n' + '\n\n'.join(lines) + '\n') if lines else 'Nobody has answered yet: you go first.\n'


def channel_context(mb, project, channel, answering='', limit=10):
    """The last few lines of a channel, so whoever answers knows what was being talked about. The message being
    answered is quoted on its own, so it's left out here."""
    said = [m for m in mb.channel_messages(project, channel, limit=limit + 1) if m.get('kind') != 'note']
    if said and said[-1]['sender'] == 'human' and said[-1]['body'].strip() == answering.strip():
        said = said[:-1]
    said = said[-limit:]
    if not said:
        return ''
    names = team.display(mb.saved_projects())
    lines = [f"- {'The lead' if m['sender'] == 'human' else names.get(m['sender'], {}).get('name', m['sender'])}: "
             f"{' '.join(m['body'].split())[:300]}" for m in said]
    return f'\n\nEarlier in #{channel} (for context):\n' + '\n'.join(lines)


def running(mb, project, channel=None):
    """The project's live round-table. One whose turn died without handing over (no open turn for 2 minutes) ends."""
    for d in mb.discussions():
        if d['project'] != project or channel not in (None, d['channel']):
            continue
        if any(r.get('discussion') == d['id'] for r in mb.requests(open_only=True)):
            return d
        if (datetime.now(timezone.utc) - datetime.fromisoformat(d['updated'])).total_seconds() < 120:
            return d
        d['status'] = 'stopped'
        mb.save_discussion(d)
    return None


def start(mb, p, channel, text, start_fn):
    """Begin a round-table in project p; returns its id. Members that work in their own app sit it out."""
    project, settings = p['key'], p['settings']
    members = [m for m in team.team(settings) if not m.get('manual')]
    if not members:
        raise ValueError('Nobody on this team can join a round-table (they all work in their own app)')
    ids = [m['id'] for m in members]
    host = settings.get('coordinator') if settings.get('coordinator') in ids else ids[0]
    rounds = max(1, min(MAX_ROUNDS, int(settings.get('rounds') or DEFAULT_ROUNDS)))
    d = {'id': uuid.uuid4().hex[:8], 'project': project, 'channel': channel, 'topic': text.strip()[:4000], 'members': ids,
         'rounds': rounds, 'turn': 0, 'host': host, 'status': 'running', 'started': now()}
    mb.save_discussion(d)
    names = team.display(mb.saved_projects())
    mb.say(host, f"Round-table started: {', '.join(names.get(i, {}).get('name', i) for i in ids)} answer in turns, "
                 f"{rounds} round{'s' if rounds > 1 else ''}, then {names.get(host, {}).get('name', host)} writes the decision. "
                 f"You can stop it any time.", project=project, channel=channel, kind='note')
    advance(mb, d['id'], start_fn)
    return d['id']


def order(d):
    return [mid for _ in range(d['rounds']) for mid in d['members']] + [d['host']]


def advance(mb, did, start_fn):
    """Start the next turn, or finish. Called when a discussion starts and whenever one of its turns ends."""
    d = mb.discussion(did)
    if not d or d['status'] != 'running':
        return None
    seq = order(d)
    if d['turn'] >= len(seq):
        d['status'] = 'done'
        mb.save_discussion(d)
        return None
    mid = seq[d['turn']]
    p = mb.project(d['project'])
    if not p:
        d['status'] = 'stopped'
        mb.save_discussion(d)
        return None
    names = team.display(mb.saved_projects())
    member = team.find(p['settings'], mid) or {'name': mid, 'roles': []}
    said = transcript(mb, d, names)
    deciding = d['turn'] == len(seq) - 1
    round_no = d['turn'] // len(d['members']) + 1
    body = (DECISION if deciding else TURN).format(channel=d['channel'], round=round_no, rounds=d['rounds'], topic=quote(d['topic']),
                                                   said=said, name=member['name'], roles='; '.join(member.get('roles') or []) or 'teammate')
    title = ('Round-table decision: ' if deciding else f'Round-table, round {round_no}: ') + ' '.join(d['topic'].split())[:70]
    d['turn'] += 1
    mb.save_discussion(d)
    req = mb.ask('human', mid, title, body, cwd=p['root'], channel=d['channel'], discussion=did, refereed=1)
    start_fn(req['id'])
    return req['id']


def stop(mb, did, by='human'):
    """End a round-table now; the turn in progress is cancelled."""
    d = mb.discussion(did)
    if not d or d['status'] != 'running':
        return False
    d['status'] = 'stopped'
    mb.save_discussion(d)
    for r in mb.requests():
        if r.get('discussion') == did and r['status'] in ('asked', 'queued', 'working'):
            mb.set_status(r['id'], 'cancelled', by, 'Cancelled: the round-table was stopped.')
    mb.say(by, 'Round-table stopped.', project=d['project'], channel=d['channel'], kind='note')
    return True


def team_room(settings):
    """Who answers a lead's message in a channel: 'producer', 'everyone' or 'nobody' (a free note)."""
    room = (settings or {}).get('teamRoom')
    if room in ('producer', 'everyone', 'nobody'):
        return room
    return 'producer' if (settings or {}).get('coordinator') else 'nobody'
