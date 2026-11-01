"""A request's work log, made readable: what the member said and did while working on it.

Every worker writes its agent's raw event stream to logs/<request id>.log. Each agent speaks its own format
(Claude Code and Cursor: stream-json; Codex: app-server notifications; Antigravity: step updates), so this turns
any of them into one simple list of steps for the window's Work log.
"""
import json
import re

from . import paths

MAX_STEPS = 300
MAX_TEXT = 1200


def _short(value, n=160):
    text = ' '.join(str(value).split())
    return text if len(text) <= n else text[:n - 1] + '…'


def _args(args):
    """The interesting part of a tool's arguments: a path, a pattern, a command or a URL."""
    if not isinstance(args, dict):
        return _short(args)
    for key in ('file_path', 'path', 'Path', 'targetFile', 'TargetFile', 'command', 'CommandLine', 'cmd', 'pattern',
                'glob', 'query', 'url', 'Url', 'targetDirectory', 'description'):
        if args.get(key):
            return _short(args[key])
    return _short(json.dumps(args, ensure_ascii=False))


def _command(cmd):
    """Codex runs commands through PowerShell -Command "..." on Windows; show just the command."""
    cmd = cmd if isinstance(cmd, str) else ' '.join(map(str, cmd or []))
    m = re.search(r'-Command\s+(["\']?)(.*)\1\s*$', cmd, re.S)
    return _short(m.group(2) if m else cmd, 200)


def read(rid):
    """[{'kind': 'say'|'tool'|'image'|'error', 'text': ..., 'detail': ...}] for request `rid` (empty if no log)."""
    log = paths.LOGS / f'{rid}.log'
    if not re.fullmatch(r'[0-9a-f]{8}', rid or '') or not log.exists():
        return []
    steps, agy_text = [], {}

    def add(kind, text, detail=''):
        if text and len(steps) < MAX_STEPS:
            steps.append({'kind': kind, 'text': text if kind == 'say' else _short(text, 200),
                          'detail': _short(detail, 220) if detail else ''})

    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        method, params = e.get('method', ''), e.get('params') or {}
        # --- Codex app server -------------------------------------------------------------
        if method == 'item/completed':
            item = params.get('item') or {}
            t = item.get('type')
            if t == 'agentMessage':
                add('say', (item.get('text') or '')[:MAX_TEXT])
            elif t == 'commandExecution':
                add('tool', 'Ran a command', _command(item.get('command')))
            elif t == 'fileChange':
                changed = [c.get('path', '') for c in item.get('changes') or []]
                add('tool', 'Edited files', ', '.join(changed))
            elif t == 'imageGeneration':
                add('image', 'Generated an image', item.get('revisedPrompt') or '')
            elif t == 'webSearch':
                add('tool', 'Searched the web', item.get('query') or '')
            elif t == 'mcpToolCall':
                add('tool', f"Used {item.get('server', '')} {item.get('tool', '')}".strip(), _args(item.get('arguments')))
            continue
        if method == 'turn/completed' and (params.get('turn') or {}).get('status') not in (None, 'completed'):
            add('error', f"Turn {params['turn'].get('status')}", str(params['turn'].get('error') or ''))
            continue
        # --- Claude Code and Cursor (stream-json) --------------------------------------------
        if e.get('type') == 'assistant':
            for part in (e.get('message') or {}).get('content') or []:
                if part.get('type') == 'text' and part.get('text', '').strip():
                    add('say', part['text'][:MAX_TEXT])
                elif part.get('type') == 'tool_use':
                    add('tool', part.get('name', 'Tool'), _args(part.get('input')))
            continue
        if e.get('type') == 'tool_call' and e.get('subtype') == 'started':
            call = e.get('tool_call') or {}
            for name, body in call.items():  # e.g. {"readToolCall": {"args": {...}}}; other keys are ids and text
                if not name.endswith('ToolCall') or not isinstance(body, dict):
                    continue
                add('tool', re.sub(r'ToolCall$', '', name).replace('_', ' ').capitalize() or 'Tool', _args((body or {}).get('args')))
            continue
        if e.get('type') == 'result' and e.get('is_error'):
            add('error', 'Finished with an error', str(e.get('result') or ''))
            continue
        # --- Antigravity CLI ---------------------------------------------------------------
        if e.get('event') == 'step_update':
            s = e.get('step_update') or {}
            i = s.get('step_index')
            if s.get('step_type') == 'agent_response':
                agy_text[i] = agy_text.get(i, '') + (s.get('text_delta') or '')
                if s.get('state') == 'DONE' and agy_text.get(i, '').strip():
                    add('say', agy_text.pop(i).strip()[:MAX_TEXT])
            elif s.get('step_type') == 'tool' and s.get('state') in ('DONE', 'ERROR'):
                info = s.get('tool_info') or {}
                name = (s.get('tool_name') or 'tool').replace('_', ' ').capitalize()
                add('error' if s.get('state') == 'ERROR' else 'tool', name + (' (refused)' if s.get('state') == 'ERROR' else ''),
                    _args(info.get('parameters')))
            continue
        if e.get('event') == 'result' and (e.get('result') or {}).get('status') not in (None, 'SUCCESS'):
            add('error', f"Finished: {e['result'].get('status')}", '')
    return steps
