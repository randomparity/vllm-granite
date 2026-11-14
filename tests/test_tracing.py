import contextlib
import io
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import tracing as t
from scripts import granite as g
from scripts import baseline as b


TRACE = ('1000 1.000001 execve(0x1, 0x2, 0x3) = 0\n'
         '1000 1.000002 clone3({flags=CLONE_THREAD}, 88) = 2 '
         "/* 2000 in strace's PID NS */\n"
         '2000 1.000003 exit(0) = ?\n'
         '2000 1.000004 +++ exited with 0 +++\n'
         '1000 1.000005 exit_group(0) = ?\n'
         '1000 1.000006 +++ exited with 0 +++\n')


class ParserCases(unittest.TestCase):
    def validate(self, text, pidns=True):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'raw'
            path.write_text(text)
            return t.validate(path, 1000, pidns)

    def test_namespace_lineage_and_summary_allowlist(self):
        value = self.validate(TRACE)
        self.assertEqual(value['tasks'], 2)
        self.assertEqual(value['syscall_records'], 4)
        self.assertEqual(set(value), {'status', 'tasks', 'syscall_records', 'bytes', 'sha256'})
        self.assertEqual(len(value['sha256']), 64)

    def test_incomplete_coverage_is_rejected(self):
        variants = [TRACE.replace('execve', 'openat'), TRACE[:-1], '',
                    '\n'.join(line for line in TRACE.split('\n') if not line.startswith('2000 ')),
                    TRACE.replace('2000 1.000004 +++ exited with 0 +++\n', ''),
                    TRACE.replace(" /* 2000 in strace's PID NS */", ''),
                    TRACE.replace('2000 1.000003', '3000 1.000003'),
                    TRACE.replace('1000 1.000005 exit_group(0) = ?', 'garbage'),
                    TRACE + '1000 1.000007 getpid() = 1\n',
                    TRACE.replace(' = 0\n', ' = ? <unavailable>\n', 1),
                    TRACE.replace('exit_group(0) = ?', 'getpid() = ? <unavailable>'),
                    TRACE.replace('1000 1.000005 exit_group(0) = ?',
                                  '1000 1.000005 write(' + 'x' * 65536)]
        for text in variants:
            with self.subTest(text=text[:60]), self.assertRaises(RuntimeError):
                self.validate(text)
        with patch.object(t, 'LIMIT', len(TRACE.encode())), self.assertRaises(RuntimeError):
            self.validate(TRACE)

    def test_resumed_clone_and_bootstrap(self):
        text = TRACE.replace('clone3({flags=CLONE_THREAD}, 88) = 2',
                             'clone3({flags=CLONE_THREAD}, 88 <unfinished ...>\n'
                             '1000 1.000002 <... clone3 resumed>) = 2')
        text = '1000 1.000000 <... read resumed>) = 0\n' + text
        self.assertEqual(self.validate(text)['tasks'], 2)
        with self.assertRaises(RuntimeError):
            self.validate(text.replace('<... clone3 resumed>', '<... clone resumed>'))

    def test_same_namespace_and_failed_clone(self):
        text = TRACE.replace("2 /* 2000 in strace's PID NS */", '2000')
        text = text.replace('1000 1.000005',
                            '1000 1.000004 clone3(0x1, 0x2) = -1 ENOSYS '
                            '(Function not implemented)\n'
                            '1000 1.000005')
        self.assertEqual(self.validate(text, False)['tasks'], 2)


class ObserverCases(unittest.TestCase):
    def test_private_files_do_not_depend_on_callers_umask(self):
        with tempfile.TemporaryDirectory() as name:
            previous = os.umask(0o022)
            try:
                capture = t.Capture(Path(name) / 'capture')
            finally:
                os.umask(previous)
            for path in capture.folder.rglob('*'):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_health_errors_and_private_identity(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / 'capture'
            capture = t.Capture(folder)
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            definition = t.read(folder / 'hooks', '00-capture.json')
            self.assertEqual(definition['stages'], ['prestart'])
            self.assertEqual(definition['hook']['timeout'], 6)
            key, value = next(iter(definition['when']['annotations'].items()))
            self.assertIsNotNone(re.fullmatch(key, t.ANNOTATION))
            self.assertIsNotNone(re.fullmatch(value, capture.token))
            self.assertIn(capture.token, capture.arguments()[1])
            with self.assertRaises(RuntimeError):
                capture.check()
            capture.container = 'a' * 64
            t.write(folder, 'armed.json', {'container': capture.container, 'root': 1000,
                                         'pidns': True})
            t.write(folder, 'exit.json', {'code': 1})
            with self.assertRaises(RuntimeError):
                capture.check()
            t.write(folder, 'exit.json', {'code': 0})
            (folder / 'raw.strace').write_text(TRACE)
            (folder / 'observer.stderr').write_text('strace: Process 1000 detached\n')
            (folder / 'supervisor.stderr').write_text('')
            with self.assertRaises(RuntimeError):
                capture.finish()
            (folder / 'observer.stderr').write_text('strace: Process 1000 attached\n')
            self.assertEqual(capture.finish()['tasks'], 2)
            t.write(folder, 'armed.json', {'container': 'b' * 64})
            with self.assertRaises(RuntimeError):
                capture.check()

    def test_hook_refuses_foreign_state_before_spawning(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / 'capture'
            capture = t.Capture(folder)
            state = {'pid': os.getpid(), 'id': 'a' * 64, 'status': 'created',
                     'annotations': {t.ANNOTATION: 'wrong'}}
            with patch.object(sys, 'stdin',
                              io.TextIOWrapper(io.BytesIO(json.dumps(state).encode()))):
                with patch.object(t.subprocess, 'Popen') as spawn:
                    with self.assertRaises(RuntimeError):
                        t.hook(folder)
                    spawn.assert_not_called()
            self.assertIsNone(capture.summary)

    def test_real_host_prearm_exec_short_lived_thread_and_child(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / 'capture'
            capture = t.Capture(folder)
            capture.container = 'a' * 64
            read_fd, write_fd = os.pipe()
            source = ('import os,threading,time; '
                      't=threading.Thread(target=lambda:time.sleep(.01)); t.start(); t.join(); '
                      'p=os.fork(); (os._exit(0) if p==0 else os.waitpid(p,0)); t.join()')
            bootstrap = ('import os,sys; print("ready",flush=True); '
                         f'os.read({read_fd},1); os.close({read_fd}); '
                         'os.execv(sys.executable,[sys.executable,"-c",sys.argv[1]])')
            child = subprocess.Popen([sys.executable, '-c', bootstrap, source],
                                     pass_fds=(read_fd,), stdout=subprocess.PIPE)
            os.close(read_fd)
            try:
                self.assertTrue(select.select([child.stdout], [], [], 5)[0])
                self.assertEqual(child.stdout.readline(), b'ready\n')
                state = {'pid': child.pid, 'id': capture.container, 'status': 'created',
                         'annotations': {t.ANNOTATION: capture.token}}
                hook = subprocess.run([sys.executable, str(Path(t.__file__).resolve()),
                                       '--hook', str(folder)], input=json.dumps(state),
                                      text=True, capture_output=True, timeout=7)
                self.assertEqual(hook.returncode, 0, hook.stderr)
                self.assertTrue((folder / 'armed.json').exists())
                os.write(write_fd, b'x')
                self.assertEqual(child.wait(timeout=10), 0)
                self.assertEqual(capture.finish()['tasks'], 3)
                self.assertTrue(capture.summary['syscall_records'] > 50)
            finally:
                os.close(write_fd)
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.stdout.close()


class LaunchCases(unittest.TestCase):
    def launch(self, fault=False):
        with tempfile.TemporaryDirectory() as name:
            state = Path(name)
            (state / 'logs').mkdir()
            events = []

            class Capture:
                container = None
                def arguments(self):
                    return ['--hooks-dir=/private/hooks', '--annotation=org.granite.capture=test']
                def check(self):
                    events.append('check')
                    if fault:
                        raise RuntimeError('primary capture failure')
                def finish(self):
                    events.append('finish')
                    if fault:
                        raise RuntimeError('incomplete trace at teardown')

            capture = Capture()
            def run(*args, **kwargs):
                if args[:2] == ('podman', 'create'):
                    self.assertIn('--hooks-dir=/private/hooks', args)
                    events.append('create')
                    return 'a' * 64
                if args[:2] == ('podman', 'start'):
                    events.append('start')
                return ''
            with contextlib.ExitStack() as stack:
                for field, value in {'exists': lambda *a: False, 'run': run,
                        'observe': lambda *a: {'ok': True}, 'active': lambda *a: None,
                        'readiness': lambda *a: True, 'network_check': lambda *a: None,
                        'reachable': lambda *a: False,
                        'cleanup': lambda *a: events.append('cleanup')}.items():
                    stack.enter_context(patch.object(g, field, side_effect=value))
                if fault:
                    with self.assertRaisesRegex(RuntimeError, 'primary capture failure'):
                        g.launch(state, 'private', None, True, capture=capture)
                else:
                    g.launch(state, 'private', None, True, capture=capture)
            self.assertEqual(capture.container, 'a' * 64)
            self.assertEqual(events[:2], ['create', 'start'])
            self.assertIn('check', events)
            self.assertEqual(events[-2:], ['cleanup', 'finish'])

    def test_optional_capture_wraps_creation_and_final_cleanup(self):
        self.launch()

    def test_capture_failure_preserves_cause_and_cleans(self):
        self.launch(True)


class BaselineCases(unittest.TestCase):
    def test_trace_summary_is_allowlisted_again(self):
        value = b.public_result({'requests': [], 'traces': [{
            'status': 'complete', 'cache': 'cold', 'tasks': 2, 'bytes': 100,
            'sha256': 'a' * 64, 'tracer': 'strace -- version 7.2',
            'raw': 'private argument', 'pid': 123, 'folder': '/private'}]}, {})
        self.assertEqual(value['traces'][0]['cache'], 'cold')
        self.assertNotIn('private', json.dumps(value))
        self.assertNotIn('pid', value['traces'][0])

    def test_explicit_trace_flag_and_live_sample_failure(self):
        command = subprocess.run([sys.executable, str(Path(b.__file__).resolve()), '--help'],
                                 capture_output=True, text=True, timeout=5)
        self.assertEqual(command.returncode, 0)
        self.assertIn('--trace', command.stdout)
        trial = b.Trial(Path('/private'), 'private', None, None, {}, {}, 10)
        with patch.object(b.tracing, 'Capture') as capture:
            trial.capture = capture.return_value
            trial.capture.check.side_effect = RuntimeError('trace lost')
            with patch.object(g, 'active') as active, self.assertRaisesRegex(RuntimeError, 'lost'):
                trial.sample(force=True)
            active.assert_not_called()

    def test_traced_session_passes_capture_and_retains_cache_id(self):
        with tempfile.TemporaryDirectory() as name:
            result = {'cleanups': []}
            trial = b.Trial(Path(name), 'private', None, None, {}, result, 100)
            trial.capture_root = Path(name)
            with patch.object(b.tracing, 'Capture') as capture, \
                 patch.object(g, 'preflight'), \
                 patch.object(g, 'gpu_state', return_value=[0, 0, 0]), \
                 patch.object(g, 'launch') as launch, \
                 patch.object(trial, 'verify_teardown', return_value={'status': 'passed'}):
                capture.return_value.summary = {'status': 'complete', 'tasks': 3}
                with patch.object(b.time, 'monotonic', return_value=1):
                    trial.session('cold')
            self.assertIs(launch.call_args.kwargs['capture'], capture.return_value)
            self.assertEqual(result['traces'][0]['cache'], 'cold')

    def test_trace_failure_does_not_start_automatic_recovery(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as name:
            state = Path(name)
            (state / 'logs').mkdir()
            (state / 'cache').mkdir()
            profile = state / 'profile.json'
            profile.write_text('{}')
            sessions = []

            class Trial:
                def __init__(self, *args):
                    self.result = args[-2]
                def session(self, cache, **kwargs):
                    sessions.append(cache)
                    self.result['cleanups'].append({'status': 'passed'})
                    raise RuntimeError('cgroup OOM')

            info = {'host': {'security': {'seccompProfilePath': str(profile)},
                             'ociRuntime': {'package': 'runtime'}}, 'version': {'Version': '5.8.7'}}
            budget = SimpleNamespace(store=state, check=lambda *a, **kw: None)
            args = SimpleNamespace(state=state, gpu='private', desktop_baseline=None,
                                   reset_cache=False, trace=True)
            with patch.object(g, 'reachable', return_value=False), \
                 patch.object(g, 'desktop_baseline'), \
                 patch.object(g, 'preflight', return_value=info), \
                 patch.object(g, 'Budget', return_value=budget), \
                 patch.object(g, 'run', return_value='version'), patch.object(g, 'launch'), \
                 patch.object(b.shutil, 'disk_usage',
                              return_value=SimpleNamespace(free=100*g.GIB)), \
                 patch.object(b, 'validate_fixtures'), patch.object(b, 'Trial', Trial):
                with self.assertRaisesRegex(RuntimeError, 'cgroup OOM'):
                    b.run_trial(args)
            self.assertEqual(sessions, ['cold'])
