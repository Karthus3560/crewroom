"""Read Claude Code and Codex chat files from disk and turn them into clean chat messages.

Both apps save every conversation as JSON lines on this computer:
  Claude: ~/.claude/projects/<folder>/<session>.jsonl
  Codex:  ~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<thread>.jsonl
Nothing here writes to those files.
"""
import json
import os
import re
import time
from pathlib import Path

from . import paths

MAX_IMAGE = 1_500_000          # base64 characters kept per inline image
MAX_MESSAGES = 400
UUID = re.compile(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$')
NOISE = ('<system-reminder>', '<environment_context>', '<command-', '<local-command', '<user_instructions>',
         '<permissions instructions>', '<task-notification>', '<turn_aborted>', 'Caveat:')


def _lines(path, max_bytes=None):
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        if max_bytes and size > max_bytes:
            f.seek(size - max_bytes)
            f.readline()
        for raw in f:
            try:
                yield json.loads(raw)
            except ValueError:
                continue


def _head(path, max_bytes=4 * 1024 * 1024):
    """Lines from the start of a file, stopping once max_bytes have been read (callers break early)."""
    read = 0
    with open(path, 'rb') as f:
        for raw in f:
            read += len(raw)
            if read > max_bytes:
                return
            try:
                yield json.loads(raw)
            except ValueError:
                continue


def _tool_label(name, data):
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return f'{name}: {data[:120]}'
    if not isinstance(data, dict):
        return name
    for key in ('file_path', 'path', 'command', 'cmd', 'pattern', 'url', 'query', 'description', 'prompt'):
        if data.get(key):
            return f'{name}: {str(data[key])[:120]}'
    return name


def _title(text):
    """First line a person would recognise: skip tag lines such as <image ...> or <environment_context>."""
    for line in text.strip().splitlines():
        line = line.strip().lstrip('#').strip()
        if line and not line.startswith(('<', '[Image', '```')):
            return line[:80]
    return None


def _is_noise(text):
    return not text.strip() or text.lstrip().startswith(NOISE)


def _image(source):
    if isinstance(source, dict) and source.get('type') == 'base64' and len(source.get('data', '')) <= MAX_IMAGE:
        return f"data:{source.get('media_type', 'image/png')};base64,{source['data']}"
    return None


# --- Claude -----------------------------------------------------------------
def claude_sessions(limit=40):
    files = sorted(paths.CLAUDE_PROJECTS.glob('*/*.jsonl'), key=os.path.getmtime, reverse=True)[:limit]
    out = []
    for f in files:
        title, cwd = None, None
        for d in _lines(f, 131072):
            if d.get('type') == 'custom-title':
                title = d.get('customTitle') or title
            elif d.get('type') == 'summary' and not title:
                title = d.get('summary')
            cwd = d.get('cwd') or cwd
        if not title:
            for d in _head(f):
                cwd = cwd or d.get('cwd')
                msg = d.get('message')
                if d.get('type') == 'user' and isinstance(msg, dict) and isinstance(msg.get('content'), str) \
                        and not _is_noise(msg['content']):
                    title = _title(msg['content'])
                    if title:
                        break
        out.append(dict(provider='claude', id=f.stem, title=title or 'Untitled chat', cwd=cwd,
                        updated=os.path.getmtime(f)))
    return out


def claude_messages(session_id):
    found = list(paths.CLAUDE_PROJECTS.glob(f'*/{session_id}.jsonl'))
    if not found:
        raise KeyError(session_id)
    out = []
    for d in _lines(found[0], 24 * 1024 * 1024):
        if d.get('type') not in ('user', 'assistant') or d.get('isSidechain'):
            continue
        msg = d.get('message') or {}
        role = 'claude' if d['type'] == 'assistant' else 'human'
        content = msg.get('content')
        parts = []
        if isinstance(content, str):
            if not _is_noise(content):
                parts.append({'type': 'text', 'text': content})
        elif isinstance(content, list):
            for b in content:
                t = b.get('type')
                if t == 'text' and not _is_noise(b.get('text', '')):
                    parts.append({'type': 'text', 'text': b['text']})
                elif t == 'image' and _image(b.get('source')):
                    parts.append({'type': 'image', 'src': _image(b['source'])})
                elif t == 'tool_use':
                    parts.append({'type': 'tool', 'label': _tool_label(b.get('name', 'tool'), b.get('input'))})
                elif t == 'tool_result' and isinstance(b.get('content'), list):
                    for inner in b['content']:
                        if inner.get('type') == 'image' and _image(inner.get('source')):
                            parts.append({'type': 'image', 'src': _image(inner['source'])})
        if parts:
            if all(p['type'] != 'text' for p in parts) and role == 'human':
                role = 'tool'
            _append(out, role, d.get('timestamp'), parts)
    return out[-MAX_MESSAGES:]


# --- Codex ------------------------------------------------------------------
def _codex_files():
    return sorted(paths.CODEX_SESSIONS.glob('*/*/*/rollout-*.jsonl'), key=os.path.getmtime, reverse=True)


def _codex_names():
    names = {}
    index = paths.CODEX_HOME / 'session_index.jsonl'
    if index.exists():
        for d in _lines(index, 4 * 1024 * 1024):
            if d.get('id') and d.get('thread_name'):
                names[d['id']] = d['thread_name']
    return names


def codex_sessions(limit=40):
    names = _codex_names()
    out = []
    for f in _codex_files()[:limit]:
        m = UUID.search(f.name)
        sid = m.group(1) if m else f.stem
        cwd, title = None, names.get(sid)
        for d in _head(f):
            p = d.get('payload') or {}
            if d.get('type') == 'session_meta':
                cwd = p.get('cwd')
                if title:
                    break
            elif not title and d.get('type') == 'event_msg' and p.get('type') == 'user_message' \
                    and not _is_noise(p.get('message', '')):
                title = _title(p['message'])
                if title:
                    break
            elif not title and d.get('type') == 'response_item' and p.get('role') == 'user':
                text = '\n'.join(c.get('text', '') for c in p.get('content') or [] if c.get('type') == 'input_text'
                                 and not _is_noise(c.get('text', '')))
                title = _title(text) if text else None
                if title:
                    break
        out.append(dict(provider='codex', id=sid, title=title or 'Chat with images', cwd=cwd,
                        updated=os.path.getmtime(f)))
    return out


def codex_messages(session_id):
    found = [f for f in _codex_files() if f.name.endswith(f'{session_id}.jsonl')]
    if not found:
        raise KeyError(session_id)
    out = []
    for d in _lines(found[0], 24 * 1024 * 1024):
        if d.get('type') != 'response_item':
            continue
        p = d.get('payload') or {}
        t = p.get('type')
        if t == 'message' and p.get('role') in ('user', 'assistant'):
            parts = []
            for c in p.get('content') or []:
                if c.get('type') in ('input_text', 'output_text') and not _is_noise(c.get('text', '')):
                    parts.append({'type': 'text', 'text': c['text']})
                elif c.get('type') == 'input_image' and isinstance(c.get('image_url'), str) \
                        and c['image_url'].startswith('data:') and len(c['image_url']) <= MAX_IMAGE:
                    parts.append({'type': 'image', 'src': c['image_url']})
            if parts:
                _append(out, 'codex' if p['role'] == 'assistant' else 'human', d.get('timestamp'), parts)
        elif t in ('function_call', 'custom_tool_call', 'local_shell_call', 'web_search_call', 'image_generation_call'):
            name = p.get('name') or t.replace('_call', '').replace('_', ' ')
            _append(out, 'codex', d.get('timestamp'), [{'type': 'tool', 'label': _tool_label(name, p.get('arguments') or p.get('input') or p.get('action'))}])
    return out[-MAX_MESSAGES:]


def _append(out, role, ts, parts):
    """Merge back-to-back pieces from the same speaker into one bubble."""
    if out and out[-1]['role'] == role:
        out[-1]['parts'].extend(parts)
    else:
        out.append({'role': role, 'time': ts, 'parts': parts})


def sessions(limit=30):
    both = claude_sessions(limit) + codex_sessions(limit)
    return sorted(both, key=lambda s: s['updated'], reverse=True)


def messages(provider, session_id):
    if not re.fullmatch(r'[0-9A-Za-z-]{8,64}', session_id or ''):
        raise KeyError(session_id)
    return claude_messages(session_id) if provider == 'claude' else codex_messages(session_id)


def current_codex_session(cwd, max_age=900):
    """Best guess at the Codex chat running a command: the newest recent chat for this folder."""
    if os.environ.get('CODEX_THREAD_ID'):
        return os.environ['CODEX_THREAD_ID']
    target = os.path.normcase(os.path.abspath(cwd))
    for f in _codex_files()[:40]:
        if time.time() - os.path.getmtime(f) > max_age:
            break
        for d in _head(f):
            if d.get('type') == 'session_meta':
                if os.path.normcase(os.path.abspath(d['payload'].get('cwd', ''))) == target:
                    m = UUID.search(f.name)
                    return m.group(1) if m else None
                break
    return None
