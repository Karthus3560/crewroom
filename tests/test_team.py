"""Run with: python -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ['TEAMCHAT_DATA'] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from teamchat import __version__, cli, paths, server, status, system, transcripts, worker  # noqa: E402
from teamchat.db import Mailbox  # noqa: E402


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.mb = Mailbox(Path(TMP) / f'{self.id()}.db')

    def tearDown(self):
        self.mb.close()

    def test_request_lifecycle_with_attachment(self):
        req = self.mb.ask('claude', 'codex', 'Make icons', 'two **PNGs**')
        self.assertEqual(req['status'], 'asked')
        self.assertEqual([r['id'] for r in self.mb.requests('codex', open_only=True)], [req['id']])
        self.mb.set_status(req['id'], 'done', 'codex', 'Here', files=[__file__])
        self.assertEqual(self.mb.request(req['id'])['status'], 'done')
        self.assertEqual(self.mb.requests('codex', open_only=True), [])
        done = self.mb.messages(rid=req['id'])[-1]
        self.assertEqual(done['files'][0]['name'], 'test_team.py')
        self.assertEqual(self.mb.attachment(done['files'][0]['id'])['path'], str(Path(__file__).resolve()))

    def test_rejects_bad_members_and_missing_files(self):
        with self.assertRaises(ValueError):
            self.mb.ask('claude', 'claude', 'self')
        with self.assertRaises(ValueError):
            self.mb.ask('claude', 'gemini', 'who')
        with self.assertRaises(FileNotFoundError):
            self.mb.ask('claude', 'codex', 'x', files=['missing.png'])
        self.assertEqual(self.mb.requests(), [])  # failed attachment rolled the request back

    def test_attached_paths(self):
        req = self.mb.ask('claude', 'codex', 'x', files=[__file__])
        self.assertIn(str(Path(__file__).resolve()), self.mb.attached_paths())

    def test_messages_after_cursor(self):
        self.mb.say('human', 'one')
        first = self.mb.messages()[-1]['seq']
        self.mb.say('codex', 'two')
        self.assertEqual([m['body'] for m in self.mb.messages(after=first)], ['two'])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def test_ask_inbox_done_show(self):
        code, out = self.run_cli('--as', 'claude', 'ask', 'codex', 'Write tests', '--cwd', TMP)
        self.assertEqual(code, 0)
        rid = out.split('request ')[1].split()[0]
        self.assertIn(rid, self.run_cli('--as', 'codex', 'inbox')[1])
        self.run_cli('--as', 'codex', 'done', rid, 'All **green**')
        self.assertIn('Inbox empty', self.run_cli('--as', 'codex', 'inbox')[1])
        self.assertIn('All **green**', self.run_cli('show', rid)[1])

    def test_identity_detection(self):
        env = dict(os.environ)
        try:
            for k in [k for k in os.environ if k.startswith(('CLAUDE', 'CODEX_', 'TEAMCHAT_AS'))]:
                os.environ.pop(k)
            self.assertEqual(cli.whoami(), 'human')
            os.environ['CODEX_SANDBOX'] = 'seatbelt'
            self.assertEqual(cli.whoami(), 'codex')
            os.environ['CLAUDECODE'] = '1'
            self.assertEqual(cli.whoami(), 'claude')
            self.assertEqual(cli.whoami('human'), 'human')
        finally:
            os.environ.clear()
            os.environ.update(env)


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        home = Path(tempfile.mkdtemp())
        self.claude = home / 'projects'
        self.codex = home / 'codex'
        (self.claude / 'proj').mkdir(parents=True)
        (self.codex / 'sessions' / '2026' / '10' / '30').mkdir(parents=True)
        self.saved = (paths.CLAUDE_PROJECTS, paths.CODEX_HOME, paths.CODEX_SESSIONS)
        paths.CLAUDE_PROJECTS, paths.CODEX_HOME, paths.CODEX_SESSIONS = self.claude, self.codex, self.codex / 'sessions'

    def tearDown(self):
        paths.CLAUDE_PROJECTS, paths.CODEX_HOME, paths.CODEX_SESSIONS = self.saved

    def write(self, path, rows):
        path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')

    def test_claude_chat_is_cleaned(self):
        sid = '11111111-2222-3333-4444-555555555555'
        self.write(self.claude / 'proj' / f'{sid}.jsonl', [
            {'type': 'user', 'cwd': 'C:/x', 'message': {'content': '<system-reminder>hidden</system-reminder>'}},
            {'type': 'user', 'cwd': 'C:/x', 'message': {'content': 'Build a **calculator**'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': 'secret'},
                {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'a.py'}},
                {'type': 'text', 'text': 'Done!'}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AAAA'}}]}]}},
            {'type': 'assistant', 'isSidechain': True, 'message': {'content': [{'type': 'text', 'text': 'subagent'}]}},
            {'type': 'custom-title', 'customTitle': 'Calc chat'},
        ])
        self.assertEqual(transcripts.claude_sessions()[0]['title'], 'Calc chat')
        msgs = transcripts.messages('claude', sid)
        self.assertEqual([m['role'] for m in msgs], ['human', 'claude', 'tool'])
        self.assertEqual(msgs[1]['parts'], [{'type': 'tool', 'label': 'Read: a.py'}, {'type': 'text', 'text': 'Done!'}])
        self.assertTrue(msgs[2]['parts'][0]['src'].startswith('data:image/png;base64,'))
        self.assertNotIn('secret', json.dumps(msgs))

    def test_codex_chat_and_title(self):
        sid = '01a18c74-0000-7000-8000-000000000001'
        self.write(self.codex / 'sessions' / '2026' / '10' / '30' / f'rollout-2026-10-30T13-00-00-{sid}.jsonl', [
            {'type': 'session_meta', 'payload': {'cwd': 'C:/y'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': 'rules'}]}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '<environment_context>x'}]}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Make 6 icons'}]}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'input': 'ls'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Here they are'}]}},
        ])
        self.write(self.codex / 'session_index.jsonl', [{'id': sid, 'thread_name': 'Icon job'}])
        self.assertEqual(transcripts.codex_sessions()[0]['title'], 'Icon job')
        msgs = transcripts.messages('codex', sid)
        self.assertEqual([m['role'] for m in msgs], ['human', 'codex'])
        self.assertEqual(msgs[1]['parts'][0], {'type': 'tool', 'label': 'exec: ls'})

    def test_rejects_path_like_ids(self):
        for bad in ('../x', 'a/b', '', 'x' * 80):
            with self.assertRaises(KeyError):
                transcripts.messages('claude', bad)


class WorkerTests(unittest.TestCase):
    def test_changed_files_prefers_media(self):
        root = Path(tempfile.mkdtemp())
        (root / 'old.txt').write_text('a')
        before = worker.snapshot(root)
        time.sleep(0.05)
        (root / 'notes.md').write_text('b')
        (root / 'pic.png').write_bytes(b'png')
        (root / 'node_modules').mkdir()
        (root / 'node_modules' / 'skip.js').write_text('c')
        found = [Path(p).name for p in worker.changed_files(before, root)]
        self.assertEqual(found, ['pic.png', 'notes.md'])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, path, body=None, headers=None):
        h = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{self.port}'} if body is not None else {}
        h.update(headers or {})
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}',
            data=json.dumps(body).encode() if body is not None else None, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_page_and_state(self):
        code, page = self.call('/')
        self.assertEqual(code, 200)
        self.assertIn(b'Crewroom', page)
        code, data = self.call('/api/state')
        self.assertIn('claude', json.loads(data)['members'])

    def test_static_traversal_blocked(self):
        self.assertEqual(self.call('/../teamchat/db.py')[0], 404)
        self.assertEqual(self.call('/%2e%2e/teamchat/db.py')[0], 404)

    def test_host_and_origin_guards(self):
        self.assertEqual(self.call('/api/state', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.call('/api/say', {'body': 'hi'}, {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.call('/api/say', {'body': 'hi'})[0], 200)

    def test_human_ask_validation(self):
        self.assertEqual(self.call('/api/ask', {'to': 'human', 'title': 'x'})[0], 400)
        self.assertEqual(self.call('/api/ask', {'to': 'codex', 'title': 'x', 'cwd': 'Z:/nope/nope'})[0], 400)
        code, data = self.call('/api/ask', {'to': 'codex', 'title': 'Queue only'})
        self.assertEqual((code, json.loads(data)['status']), (200, 'asked'))

    def test_setup_check_and_onboarding(self):
        code, data = self.call('/api/setup-check')
        check = json.loads(data)
        self.assertEqual(code, 200)
        self.assertEqual(set(check['skills']), {'claude', 'codex'})
        self.assertFalse(check['onboarded'])
        self.assertEqual(self.call('/api/onboarded', {})[0], 200)
        self.assertTrue(json.loads(self.call('/api/setup-check')[1])['onboarded'])

    def test_tray_status_counts_work(self):
        tip, lines, working = server.tray_status()
        self.assertIn('is running', tip)
        self.assertLessEqual(len(tip), 127)
        self.assertEqual(lines[0], f'Crewroom {__version__} is running')

    def test_uninstall_refused_without_an_install_record(self):
        code, data = self.call('/api/uninstall', {})
        self.assertEqual(code, 409)
        self.assertIn('not the installed one', json.loads(data)['error'])

    def test_unknown_attachment_is_404(self):
        self.assertEqual(self.call('/api/file/nope')[0], 404)


class SetupTests(unittest.TestCase):
    def test_create_project_roles_and_shared_skills(self):
        from teamchat import setup, projects
        home = Path(tempfile.mkdtemp())
        claude_skill = home / 'claude-skills' / 'draw'
        claude_skill.mkdir(parents=True)
        (claude_skill / 'SKILL.md').write_text('---\nname: draw\ndescription: >\n  Make images\n  with Codex.\n---\n',
                                               encoding='utf-8')
        saved = dict(setup.SKILL_DIRS)
        setup.SKILL_DIRS.update(claude=[home / 'claude-skills'], codex=[home / 'codex-skills'])
        try:
            self.assertEqual(setup.list_skills()['claude'][0]['description'], 'Make images with Codex.')
            mb = Mailbox(Path(TMP) / 'setup.db')
            team = [{'app': 'claude', 'name': 'Claude', 'roles': ['Lead builder']},
                    {'app': 'codex', 'name': 'Designer', 'roles': ['Designer', 'Icons'], 'model': 'gpt-x'},
                    {'app': 'codex', 'name': 'Tester', 'roles': ['Runs checks']}]
            made = setup.create({'name': 'Demo', 'parent': str(home), 'share': {'codex': ['draw']}, 'members': team}, mb)
            root = Path(made['root'])
            self.assertTrue((root / '.agents' / 'skills' / 'draw' / 'SKILL.md').exists())
            self.assertIn('`codex-designer`', (root / 'TEAM.md').read_text(encoding='utf-8'))
            self.assertIn('TEAM.md', (root / 'AGENTS.md').read_text(encoding='utf-8'))
            self.assertEqual(projects.root_of(root / 'assets')[0], made['key'])
            ids = [m['id'] for m in mb.project(made['key'])['settings']['members']]
            self.assertEqual(ids, ['claude', 'codex-designer', 'codex-tester'])
            self.assertEqual(mb.project(made['key'])['settings']['members'][1]['model'], 'gpt-x')
            self.assertIn('codex-tester', mb.member_ids())
            mb.ask('claude', 'codex-tester', 'Run the checks', cwd=str(root))  # project members can be asked
            with self.assertRaises(ValueError):
                setup.update({'key': made['key'], 'members': team + [{'app': 'codex', 'name': 'tester', 'roles': ['x']}]}, mb)
            with self.assertRaises(ValueError):
                setup.update({'key': made['key'], 'members': [{'app': 'codex', 'name': 'NoRoles', 'roles': []}]}, mb)
            with self.assertRaises(ValueError):
                setup.create({'name': 'bad/name', 'parent': str(home)}, mb)
            with self.assertRaises(ValueError):
                setup.create({'name': 'Demo', 'parent': str(home)}, mb)  # already exists
            mb.close()
        finally:
            setup.SKILL_DIRS.clear()
            setup.SKILL_DIRS.update(saved)
            projects.set_saved_roots([])


class FreshStartTests(unittest.TestCase):
    def test_start_fresh_and_delete_history(self):
        mb = Mailbox(Path(TMP) / 'fresh.db')
        req = mb.ask('claude', 'codex', 'Old work')
        mb.set_status(req['id'], 'done', 'codex', 'ok', files=[__file__])
        mb.say('human', 'old chat', project='p1', channel='general')
        mb.remember_session('p1', 'codex', 'thread-1', 3)
        mb.start_fresh('p1')
        self.assertIn('p1', mb.cleared())
        self.assertEqual(mb.agent_session('p1', 'codex'), (None, 0))  # next request opens a new chat
        self.assertEqual(len(mb.messages()), 3)                          # hidden, not deleted
        mb.delete_history('p1', [req['id']])
        self.assertEqual(mb.messages(), [])
        self.assertEqual(mb.requests(), [])
        self.assertEqual(mb.attached_paths(), set())
        self.assertNotIn('p1', mb.cleared())
        self.assertTrue(Path(__file__).exists())                        # files on disk are untouched
        mb.close()


class DispatchTests(unittest.TestCase):
    def setUp(self):
        from teamchat import dispatch
        self.d = dispatch
        self.mb = Mailbox(Path(TMP) / f'{self.id()}.db')
        self.settings = {'members': [
            {'id': 'codex-director', 'name': 'Director', 'app': 'codex', 'roles': ['Director']},
            {'id': 'claude-producer', 'name': 'Producer', 'app': 'claude', 'roles': ['Coordinator']},
            {'id': 'codex-composer', 'name': 'Composer', 'app': 'codex', 'roles': ['Music']}],
            'coordinator': 'claude-producer'}
        self.started = []

    def tearDown(self):
        self.mb.close()

    def run_handle(self, who, text, depth=0):
        self.mb.save_project('p', 'P', TMP, self.settings)
        req = self.mb.ask('human', who, 'x', cwd=TMP) | {'depth': depth}
        member = next(m for m in self.settings['members'] if m['id'] == who)
        return self.d.handle(self.mb, req, member, self.settings, text, self.started.append, project='p')

    def test_split_removes_block(self):
        clean, orders, err = self.d.split('Done.\n```dispatch\n[{"to":"a","title":"t"}]\n```')
        self.assertEqual((clean, len(orders), err), ('Done.', 1, None))

    def test_orders_from_members_go_to_coordinator(self):
        shown, notes = self.run_handle('codex-director', 'Plan ready.\n```dispatch\n[{"to":"codex-composer","title":"Re-time score","body":"b"}]\n```')
        self.assertEqual(shown, 'Plan ready.')
        req = self.mb.request(self.started[0])
        self.assertEqual((req['recipient'], req['depth']), ('claude-producer', 0))  # routing hops are free
        self.assertIn('Re-time score', req['body'])

    def test_coordinator_dispatches_directly_and_skips_bad_orders(self):
        _, notes = self.run_handle('claude-producer', 'ok\n```dispatch\n[{"to":"codex-composer","title":"Score"},{"to":"nobody","title":"x"},{"to":"claude-producer","title":"me"}]\n```')
        self.assertEqual([self.mb.request(i)['recipient'] for i in self.started], ['codex-composer'])
        self.assertEqual(sum('Skipped' in n for n in notes), 2)

    def test_post_block_reaches_channel(self):
        shown, _ = self.run_handle('claude-producer', 'Noted.' + chr(10) + '```post #general' + chr(10) + 'Got it, adding Arabic.' + chr(10) + '```')
        self.assertEqual(shown, 'Noted.')
        posted = [m for m in self.mb.messages() if m['channel'] == 'general']
        self.assertEqual((posted[-1]['sender'], posted[-1]['body']), ('claude-producer', 'Got it, adding Arabic.'))

    def test_long_chain_is_held_not_dropped(self):
        _, notes = self.run_handle('claude-producer', '```dispatch\n[{"to":"codex-composer","title":"t"}]\n```', depth=8)
        self.assertEqual(self.started, [])
        held = [r for r in self.mb.requests() if r['status'] == 'held']
        self.assertEqual([r['recipient'] for r in held], ['codex-composer'])
        self.assertTrue(any('waiting for your OK' in n for n in notes))

    def test_referee_steps_in_once(self):
        self.settings['referee'] = 'codex-director'
        self.run_handle('claude-producer', '```dispatch\n[{"to":"codex-composer","title":"t"}]\n```', depth=8)
        ref = self.mb.request(self.started[0])
        self.assertEqual((ref['recipient'], ref['refereed']), ('codex-director', 1))
        # the referee's own orders get a few more steps
        self.started.clear()
        self.run_handle('codex-director', '```dispatch\n[{"to":"codex-composer","title":"merged"}]\n```', depth=8)
        self.assertEqual(self.mb.request(self.started[0])['depth'], self.d.MAX_DEPTH - self.d.REFEREE_EXTRA + 1)


class AddMemberTests(unittest.TestCase):
    def test_coordinator_adds_member_when_asked(self):
        from teamchat import dispatch
        home = Path(tempfile.mkdtemp())
        mb = Mailbox(Path(TMP) / 'add.db')
        settings = {'members': [{'id': 'claude-producer', 'name': 'Producer', 'app': 'claude', 'roles': ['Coordinator']}],
                    'coordinator': 'claude-producer'}
        mb.save_project('p', 'P', str(home), settings)
        req = mb.ask('human', 'claude-producer', 'add a 3d designer', cwd=str(home))
        block = '```add-member' + chr(10) + '[{"app":"codex","name":"3D Designer","roles":["3D graphics"]}]' + chr(10) + '```'
        shown, notes = dispatch.handle(mb, req, settings['members'][0], settings, 'Done. ' + block, lambda i: None, project='p')
        ids = [m['id'] for m in mb.project('p')['settings']['members']]
        self.assertEqual(ids, ['claude-producer', 'codex-3d-designer'])
        self.assertIn('3D Designer', (home / 'TEAM.md').read_text(encoding='utf-8'))
        self.assertEqual(shown, 'Done.')
        # a plain member on another member's order may not add anyone
        member = {'id': 'codex-3d-designer', 'name': '3D Designer', 'app': 'codex'}
        req2 = mb.ask('claude-producer', 'codex-3d-designer', 'x', cwd=str(home))
        _, notes2 = dispatch.handle(mb, req2, member, mb.project('p')['settings'], block.replace('3D Designer', 'Extra'), lambda i: None, project='p')
        self.assertEqual(len(mb.project('p')['settings']['members']), 2)
        self.assertTrue(any('Ignored' in n for n in notes2))
        mb.close()


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        from teamchat import supervisor
        self.s = supervisor
        self.home = Path(tempfile.mkdtemp())
        self.mb = Mailbox(Path(tempfile.mkdtemp()) / 'sup.db')
        self.settings = {'members': [{'id': 'codex', 'name': 'Codex', 'app': 'codex', 'roles': []},
                                     {'id': 'claude-boss', 'name': 'Boss', 'app': 'claude', 'roles': []}],
                         'supervisor': 'claude-boss'}
        self.mb.save_project('p', 'P', str(self.home), self.settings)
        self.started = []

    def tearDown(self):
        self.mb.close()

    def run_check(self):
        from unittest import mock
        with mock.patch.object(self.s.projects, 'root_of', return_value=('p', 'P', str(self.home))):
            return self.s.check(self.mb, start=self.started.append)

    def test_dead_worker_restarts_once_then_fails(self):
        r = self.mb.ask('human', 'codex', 'make art', cwd=str(self.home))
        self.mb.link(r['id'], worker_pid=999999)
        self.mb.set_status(r['id'], 'working', 'codex')
        self.assertEqual(self.run_check(), [('restarted', r['id'])])
        self.mb.set_status(r['id'], 'working', 'codex')
        self.assertEqual(self.run_check()[0], ('failed', r['id']))

    def test_failure_retried_once_then_escalated(self):
        r = self.mb.ask('human', 'codex', 'make art', cwd=str(self.home))
        self.mb.set_status(r['id'], 'failed', 'codex', 'boom')
        self.assertEqual(self.run_check(), [('retried', r['id'])])
        retry = self.started[-1]
        self.mb.set_status(retry, 'failed', 'codex', 'boom again')
        did = self.run_check()
        self.assertIn(('escalated', retry), did)
        sup = self.mb.request(self.started[-1])
        self.assertEqual((sup['recipient'], sup['sender']), ('claude-boss', 'codex'))
        self.assertIn('boom', ''.join(m['body'] for m in self.mb.messages(rid=retry)))
        self.assertEqual(self.run_check(), [])  # nothing is done twice

    def test_old_failures_are_left_alone(self):
        r = self.mb.ask('human', 'codex', 'old', cwd=str(self.home))
        self.mb.set_status(r['id'], 'failed', 'codex', 'boom')
        self.mb.db.execute("update requests set updated='2020-01-01T00:00:00+00:00'")
        self.mb.db.commit()
        self.assertEqual(self.run_check(), [])


class ShellFlagTests(unittest.TestCase):
    def test_flag_kept_for_claude_only_and_tools_follow_it(self):
        from teamchat import members, worker
        out = members.clean([{'app': 'claude', 'name': 'Montage', 'roles': ['x'], 'shell': True},
                             {'app': 'codex', 'name': 'Codex', 'roles': ['y'], 'shell': True},
                             {'app': 'claude', 'name': 'Critic', 'roles': ['z']}], None)
        self.assertEqual([m['shell'] for m in out], [True, False, False])
        on, off = worker.claude_tools(out[0]), worker.claude_tools(out[2])
        self.assertIn('Bash', on[1])
        self.assertIn('Bash(git push:*)', on[3])
        self.assertIn('PowerShell(Remove-Item:*)', on[3])
        self.assertEqual(off, ['--allowedTools', worker.READ_WRITE])
        self.assertIn('runs commands', members.roles_text({'members': out}))


class MentionTests(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from teamchat import server, worker
        self.server, self.worker = server, worker
        self.home = Path(tempfile.mkdtemp())
        self.mb = Mailbox(Path(tempfile.mkdtemp()) / 'm.db')
        self.settings = {'members': [{'id': 'claude-montage', 'name': 'Montage', 'app': 'claude', 'roles': ['x']},
                                     {'id': 'claude-3d-designer', 'name': '3D Designer', 'app': 'claude', 'roles': ['y']},
                                     {'id': 'claude', 'name': 'Claude', 'app': 'claude', 'roles': ['z'], 'manual': True}]}
        self.mb.save_project('p', 'P', str(self.home), self.settings)
        self.started = []
        self.patches = [mock.patch.object(worker, 'start', self.started.append),
                        mock.patch.object(server.projects, 'root_of', return_value=('p', 'P', str(self.home)))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.mb.close()

    def test_parse_names_and_ids(self):
        from teamchat import members
        found = members.mentions('hey @3d designer and @claude-montage, mail me@x.com', self.settings)
        self.assertEqual(found, ['claude-3d-designer', 'claude-montage'])
        self.assertEqual(members.mentions('@Claude', self.settings), ['claude'])
        self.assertEqual(members.mentions('@Claudette', self.settings), [])

    def test_busy_member_gets_note_free_one_gets_request(self):
        busy = self.mb.ask('human', 'claude-montage', 'cut shot 3', cwd=str(self.home))
        self.mb.set_status(busy['id'], 'working', 'claude-montage')
        out = self.server.answer_lead(self.mb, 'p', 'general', '@Montage make it 6 s. @3D Designer add rails')['mentions']
        self.assertEqual([(o['id'], o['how']) for o in out], [('claude-montage', 'live'), ('claude-3d-designer', 'new')])
        self.assertEqual([b for _, b in self.mb.take_nudges(busy['id'])], ['@Montage make it 6 s. @3D Designer add rails'])
        self.assertEqual(self.started, [out[1]['request']])
        manual = self.server.answer_lead(self.mb, 'p', 'general', '@Claude check this')['mentions']
        self.assertEqual(manual[0]['how'], 'inbox')
        self.assertEqual(len(self.started), 1)  # manual members are not started

    def test_late_note_becomes_follow_up(self):
        req = self.mb.ask('human', 'claude-montage', 'cut shot 3', cwd=str(self.home))
        self.mb.nudge(req['id'], 'also fix the seam')
        new = self.worker._carry_notes(self.mb, self.mb.request(req['id']), {'id': 'claude-montage'}, self.settings)
        self.assertIn('also fix the seam', new['body'])
        self.assertEqual(self.started, [new['id']])
        self.assertEqual(self.mb.take_nudges(req['id']), [])

    def say(self, who, text, channel='discussion'):
        self.mb.say(who, text, project='p', channel=channel)

    def test_team_tag_outside_discussion_asks_everyone_who_can_answer(self):
        from teamchat import members
        self.assertTrue(members.mentions_team('what do you think @team?'))
        self.assertFalse(members.mentions_team('mail team@x.com or @teamwork'))
        self.say('human', 'logo is blue now', 'general')
        out = self.server.answer_lead(self.mb, 'p', 'general', '@everyone ready to ship?')['mentions']
        self.assertEqual([o['id'] for o in out], ['claude-montage', 'claude-3d-designer'])  # the manual one sits out
        body = self.mb.request(out[0]['request'])['body']
        self.assertIn('whole team', body)
        self.assertIn('logo is blue now', body)  # sees what the channel was talking about

    def test_team_room_setting(self):
        from teamchat import discuss
        self.assertEqual(discuss.team_room({}), 'nobody')
        self.assertEqual(discuss.team_room({'coordinator': 'x'}), 'producer')
        self.assertEqual(discuss.team_room({'coordinator': 'x', 'teamRoom': 'nobody'}), 'nobody')
        self.mb.save_project('p', 'P', str(self.home), self.settings | {'coordinator': 'claude-montage'})
        self.assertEqual(self.server.answer_lead(self.mb, 'p', 'general', 'hello')['routedTo'], 'claude-montage')
        self.mb.save_project('p', 'P', str(self.home), self.settings | {'coordinator': 'claude-montage', 'teamRoom': 'nobody'})
        self.assertIsNone(self.server.answer_lead(self.mb, 'p', 'general', 'hello')['routedTo'])
        self.assertEqual(self.started, [self.mb.requests('claude-montage')[0]['id']])

    def test_round_table_takes_turns_then_decides(self):
        from teamchat import discuss
        self.mb.save_project('p', 'P', str(self.home), self.settings | {'rounds': 1})
        self.say('human', '@team should we cut the intro?')
        got = self.server.answer_lead(self.mb, 'p', 'discussion', '@team should we cut the intro?')
        did = got['discussion']
        first = self.mb.request(self.started[-1])
        self.assertEqual((first['recipient'], first['discussion'], first['channel']), ('claude-montage', did, 'discussion'))
        self.assertIn('go first', first['body'])
        self.mb.set_status(first['id'], 'done', 'claude-montage', 'Cut it.')
        self.say('claude-montage', 'Cut it, it drags.')
        self.say('human', 'keep the logo though')  # the lead chimes in mid-way
        self.assertTrue(self.server.answer_lead(self.mb, 'p', 'discussion', 'keep the logo though')['joined'])
        discuss.advance(self.mb, did, self.started.append)
        second = self.mb.request(self.started[-1])
        self.assertEqual(second['recipient'], 'claude-3d-designer')
        self.assertIn('Cut it, it drags.', second['body'])
        self.assertIn('**The lead:** keep the logo though', second['body'])
        self.assertNotIn('Round-table started', second['body'])
        self.mb.set_status(second['id'], 'done', 'claude-3d-designer', 'ok')
        discuss.advance(self.mb, did, self.started.append)
        decision = self.mb.request(self.started[-1])
        self.assertEqual(decision['recipient'], 'claude-montage')  # no Producer: the first member hosts
        self.assertIn('**Decision**', decision['body'])
        self.mb.set_status(decision['id'], 'done', 'claude-montage', 'ok')
        self.assertIsNone(discuss.advance(self.mb, did, self.started.append))
        self.assertEqual(self.mb.discussion(did)['status'], 'done')
        self.assertIsNone(discuss.running(self.mb, 'p'))

    def test_stopping_a_round_table_cancels_its_turn(self):
        from teamchat import discuss
        did = self.server.answer_lead(self.mb, 'p', 'discussion', '@team ideas?')['discussion']
        turn = self.started[-1]
        self.assertTrue(discuss.stop(self.mb, did))
        self.assertEqual(self.mb.request(turn)['status'], 'cancelled')
        self.assertIsNone(discuss.advance(self.mb, did, self.started.append))
        self.assertFalse(discuss.stop(self.mb, did))

    def test_every_new_team_gets_a_producer(self):
        from teamchat import setup
        two = [{'id': 'codex', 'app': 'codex'}, {'id': 'claude-writer', 'app': 'claude'}]
        self.assertEqual(setup.default_producer(two), 'claude-writer')
        self.assertEqual(setup.default_producer([{'id': 'codex', 'app': 'codex'}]), '')  # a team of one needs none
        self.assertEqual(setup.default_producer(two[:1] + [{'id': 'claude', 'app': 'claude', 'manual': True}]), '')

class AgentTests(unittest.TestCase):
    def setUp(self):
        from teamchat import agents
        self.agents = agents
        self._command = agents.command
        agents.command = lambda app: ['TOOL']

    def tearDown(self):
        self.agents.command = self._command

    def test_ids_map_to_apps(self):
        a = self.agents
        self.assertEqual([a.app_of(x) for x in ('cursor', 'cursor-reviewer', 'antigravity-designer', 'codex-art', 'claude', 'human', 'cursorx')],
                         ['cursor', 'cursor', 'antigravity', 'codex', 'claude', 'human', 'human'])

    def test_cursor_command(self):
        args = self.agents.argv('cursor', {'model': 'gpt-5.2'}, 'C:/p', 'C:/p', 'chat-1', 'do it')
        self.assertEqual(args[:4], ['TOOL', '-p', '--output-format', 'stream-json'])
        self.assertNotIn('--force', args)  # no commands unless the lead allowed them
        self.assertEqual(args[-1], 'do it')
        self.assertEqual(args[args.index('--resume') + 1], 'chat-1')
        self.assertIn('--force', self.agents.argv('cursor', {'shell': True}, 'C:/p', 'C:/p', None, 'x'))

    def test_antigravity_command_keeps_prompt_last_and_limits_permissions(self):
        args = self.agents.argv('antigravity', {}, 'C:/p', 'C:/p', 'conv-1', 'do it')
        self.assertEqual(args[-2:], ['-p', 'do it'])
        perms = json.loads(args[args.index('--settings') + 1])['permissions']
        self.assertIn('write_file(*)', perms['allow'])
        self.assertIn('command(*)', perms['deny'])
        self.assertEqual(args[args.index('--conversation') + 1], 'conv-1')
        shell = self.agents.argv('antigravity', {'shell': True}, 'C:/p', 'C:/p', None, 'x')
        self.assertIn('--sandbox', shell)
        self.assertIn('command(git push*)', json.loads(shell[shell.index('--settings') + 1])['permissions']['deny'])

    def test_reading_progress(self):
        r = self.agents.read
        self.assertEqual(r('cursor', {'type': 'system', 'subtype': 'init', 'session_id': 's1'}), {'session': 's1'})
        self.assertEqual(r('cursor', {'type': 'result', 'subtype': 'success', 'result': 'ok', 'is_error': False}), {'final': 'ok', 'error': False})
        self.assertEqual(r('antigravity', {'event': 'init', 'conversation_id': 'c1'}), {'session': 'c1'})
        done = r('antigravity', {'event': 'result', 'result': {'status': 'SUCCESS', 'response': 'hi', 'conversation_id': 'c1'}})
        self.assertEqual((done['final'], done['error']), ('hi', False))
        self.assertTrue(r('antigravity', {'event': 'result', 'result': {'status': 'ERROR'}})['error'])

    def test_long_prompts_go_through_a_file(self):
        text = 'x' * (self.agents.LONG_PROMPT + 10)
        short = self.agents.brief(text, 'abc12345')
        self.assertLess(len(short), 2000)
        self.assertEqual((paths.DATA / 'briefs' / 'abc12345.md').read_text(encoding='utf-8'), text)

    def test_notes_to_a_busy_cursor_member_wait_for_the_next_request(self):
        mb = Mailbox(Path(TMP) / 'agent-notes.db')
        req = mb.ask('human', 'cursor', 'Refactor')
        mb.set_status(req['id'], 'working', 'cursor')
        self.assertEqual(server.note_running(mb, mb.request(req['id']), 'also rename x'), 'after')
        mb.close()


class GroupingTests(unittest.TestCase):
    def test_subfolders_join_the_project_of_earlier_work(self):
        from teamchat import projects
        base = Path(tempfile.mkdtemp()) / 'Art' / 'avatars'
        (base / 'v2' / 'chatgpt').mkdir(parents=True)
        projects.set_work_folders([str(base)])
        scratch, projects.SCRATCH = projects.SCRATCH, []  # the test folder lives in Temp, normally "Scratch & temporary"
        try:
            self.assertEqual(projects.root_of(str(base / 'v2' / 'chatgpt'))[1:], ('avatars', str(base)))
            self.assertEqual(projects.root_of(str(base))[1], 'avatars')
            (base.parent / 'TEAM.md').write_text('# Art team', encoding='utf-8')  # a marked project above wins
            self.assertEqual(projects.root_of(str(base / 'v2' / 'chatgpt'))[1], 'Art')
            repo = base.parent / 'tool' / 'src'
            (repo.parent / '.git').mkdir(parents=True)
            repo.mkdir()
            self.assertEqual(projects.root_of(str(repo))[1], 'tool')  # the nearest marker, not the one further up
        finally:
            projects.set_work_folders([])
            projects.SCRATCH = scratch


class SystemTests(unittest.TestCase):
    def test_lock_is_exclusive_and_released(self):
        path = Path(TMP) / 'lock-test'
        with open(path, 'a+') as a, open(path, 'a+') as b:
            self.assertTrue(system.try_lock(a))
            self.assertFalse(system.try_lock(b))
            system.unlock(a)
            self.assertTrue(system.try_lock(b))
            system.unlock(b)

    def test_alive(self):
        self.assertTrue(system.alive(os.getpid()))
        proc = __import__('subprocess').Popen([sys.executable, '-c', 'pass'])
        proc.wait()
        self.assertFalse(system.alive(proc.pid))
        self.assertFalse(system.alive(None))

    def test_version_of_folders(self):
        self.assertEqual(status.version_of(paths.ROOT), __version__)
        self.assertIsNone(status.version_of(Path(TMP) / 'no-such-crewroom'))


class PingAndStopTests(unittest.TestCase):
    def test_ping_names_this_copy_and_shutdown_stops_it(self):
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        port = httpd.server_address[1]
        done = threading.Event()
        threading.Thread(target=lambda: (httpd.serve_forever(), done.set()), daemon=True).start()
        info = status.ping(port)
        self.assertEqual((info['version'], info['root'], info['pid']), (__version__, str(paths.ROOT), os.getpid()))
        self.assertTrue(status.stop(port, wait=5))
        self.assertTrue(done.wait(5))
        httpd.server_close()
        self.assertIsNone(status.ping(port))


class InstallerTests(unittest.TestCase):
    def run_installer(self, home, *args):
        env = dict(os.environ, TEAMCHAT_DATA=str(Path(home) / 'data'), TEAMCHAT_PORT='47898', PYTHONIOENCODING='utf-8')
        return __import__('subprocess').run([sys.executable, str(paths.ROOT / 'install.py'), '--yes', '--no-open', '--home', str(home),
                                             '--desktop', str(Path(home) / 'Desktop'), *args],
                                            capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)

    def test_app_install_is_quiet_and_guards_against_a_second_copy(self):
        home = Path(tempfile.mkdtemp())
        r = self.run_installer(home, '--from-app')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        record = json.loads((home / 'data' / 'install.json').read_text(encoding='utf-8'))
        self.assertEqual(record['installer'], 'app')
        self.assertIn(str(paths.ROOT / 'team.py'), (home / '.claude' / 'skills' / 'team-chat' / 'SKILL.md').read_text(encoding='utf-8'))
        record['root'] = str(home / 'elsewhere')  # pretend the app lives somewhere else
        (home / 'data' / 'install.json').write_text(json.dumps(record), encoding='utf-8')
        r = self.run_installer(home)
        self.assertEqual(r.returncode, 1)
        self.assertIn('installed as a program', r.stdout)
        record['root'] = str(paths.ROOT)
        (home / 'data' / 'install.json').write_text(json.dumps(record), encoding='utf-8')
        r = self.run_installer(home, '--uninstall', '--from-app')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((home / '.claude' / 'skills' / 'team-chat').exists())

    def test_install_replaces_old_copy_then_uninstall_restores(self):
        home = Path(tempfile.mkdtemp())
        mine = home / '.agents' / 'skills' / 'team-chat'
        mine.mkdir(parents=True)
        (mine / 'SKILL.md').write_text('a skill that is not Crewroom', encoding='utf-8')
        old = home / '.claude' / 'skills' / 'team-chat'
        old.mkdir(parents=True)
        (old / 'SKILL.md').write_text('# Crewroom\npython "C:\\Old\\Crewroom\\team.py" ask', encoding='utf-8')
        r = self.run_installer(home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('already installed', r.stdout)
        self.assertIn(str(paths.ROOT / 'team.py'), (old / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertTrue((mine / 'SKILL.md.bak').exists())
        record = json.loads((home / 'data' / 'install.json').read_text(encoding='utf-8'))
        self.assertEqual((record['root'], record['version']), (str(paths.ROOT), __version__))
        self.assertTrue(record['launchers'] and all(Path(l).exists() for l in record['launchers']))
        r = self.run_installer(home, '--uninstall')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((mine / 'SKILL.md').read_text(encoding='utf-8'), 'a skill that is not Crewroom')
        self.assertFalse(old.exists())
        self.assertFalse(any(Path(l).exists() for l in record['launchers']))
        self.assertFalse((home / 'data' / 'install.json').exists())


if __name__ == '__main__':
    unittest.main()
