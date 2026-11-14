import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from scripts import granite as g

class MetadataCases(unittest.TestCase):
    def metadata(self):
        return {'sha': g.REV, 'siblings': [{'rfilename': name, 'size': 1,
                 'blobId': hashlib.sha1(b'blob 1\0x').hexdigest()} for name in sorted(g.FILES)]}
    def test_allowlist(self):
        meta = self.metadata()
        self.assertEqual(len(g.selected(meta)), 13)
        for mutate in (lambda m: m.update(sha='wrong'), lambda m: m['siblings'].pop(),
                       lambda m: m['siblings'].append(m['siblings'][0]),
                       lambda m: m['siblings'][0].update(size=-1),
                       lambda m: m['siblings'][0].update(blobId='bad'),
                       lambda m: m['siblings'][0].update(rfilename='../config.json')):
            bad = copy.deepcopy(meta)
            mutate(bad)
            with self.assertRaises(RuntimeError):
                g.selected(bad)
        meta['siblings'].append({'rfilename': 'granite_thinking_parser.py'})
        self.assertEqual(len(g.selected(meta)), 13)
    def test_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'blob'
            path.write_bytes(b'x')
            for lfs in (False, True):
                item = self.metadata()['siblings'][0]
                if lfs:
                    item['lfs'] = {'sha256': hashlib.sha256(b'x').hexdigest(), 'size': 1}
                g.verify(path, item)
                for wrong in (b'y', b'xx'):
                    path.write_bytes(wrong)
                    with self.assertRaises(RuntimeError):
                        g.verify(path, item)
                path.write_bytes(b'x')
    def test_download(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'blob'
            item = self.metadata()['siblings'][0]
            for wrong in (b'xx', b'y', b''):
                with self.assertRaises(RuntimeError):
                    g.download(io.BytesIO(wrong), path, item, lambda: None)
                self.assertFalse(path.exists())
            g.download(io.BytesIO(b'x'), path, item, lambda: None)
            self.assertEqual(path.read_bytes(), b'x')
    def test_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'link'
            path.symlink_to('/etc/passwd')
            with self.assertRaises(RuntimeError):
                g.verify(path, self.metadata()['siblings'][0])
    def test_redirect(self):
        with self.assertRaises(RuntimeError):
            g.HTTPSRedirect().redirect_request(None, None, 302, '', {}, 'http://example.invalid')

class RuntimeCases(unittest.TestCase):
    def test_readiness_redirect(self):
        for status in (200, 302, 307):
            with patch.object(g.socket, 'create_connection') as connect, \
                 patch.object(g.time, 'monotonic', return_value=10):
                connection = connect.return_value.__enter__.return_value
                connection.recv.return_value = f'HTTP/1.1 {status} Status\r\n\r\n'.encode()
                self.assertEqual(g.readiness(False, 11), status == 200)
                connect.assert_called_once_with(('127.0.0.1', 8000), timeout=1)
                self.assertTrue(connection.sendall.call_args.args[0].startswith(b'GET /health '))
    def test_readiness_headers(self):
        for response in (b'', b'invalid\r\n\r\n', b'x' * 4096):
            with patch.object(g.socket, 'create_connection') as connect, \
                 patch.object(g.time, 'monotonic', return_value=10):
                connection = connect.return_value.__enter__.return_value
                connection.recv.return_value = response
                self.assertFalse(g.readiness(True, 11))
                self.assertLessEqual(connection.recv.call_count, 17)
    def test_readiness_trickle(self):
        clock = [0.0]
        class Trickle(io.RawIOBase):
            payload = bytearray(b'HTTP/1.1 200 OK\r\nX-Test: ' + b'x' * 1300 + b'\r\n\r\n')
            def readable(self):
                return True
            def readinto(self, target):
                data = self.recv(len(target))
                target[:len(data)] = data
                return len(data)
            def recv(self, size):
                clock[0] += 0.5
                return bytes([self.payload.pop(0)]) if self.payload else b''
            def makefile(self, *args):
                return io.BufferedReader(self)
            def sendall(self, data):
                pass
            def settimeout(self, timeout):
                pass
            def setsockopt(self, *args):
                pass
        with patch.object(g.socket, 'create_connection', return_value=Trickle()), \
             patch.object(g.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                g.readiness(False, 600)
        self.assertLessEqual(clock[0], 1)
    def test_diagnostic_http(self):
        import http.server
        def serve(HandlerClass=http.server.BaseHTTPRequestHandler, **kwargs):
            self.assertTrue(callable(getattr(HandlerClass, 'do_GET', None)))
        with patch.object(http.server, 'test', side_effect=serve), \
             patch.object(g.os, 'chdir'), patch.object(g.signal, 'signal'):
            exec(g.DIAGNOSTIC_SERVER)
    def test_cache_mount(self):
        entry = {'target': '/state/cache', 'source': '/dev/loop7', 'fstype': 'ext4',
                 'fsroot': '/', 'options': 'rw,nosuid,nodev,relatime,seclabel'}
        directory = SimpleNamespace(st_mode=0o40700, st_uid=g.os.getuid(), st_dev=1799)
        device = SimpleNamespace(st_mode=0o60600, st_rdev=1799)
        with patch.object(g, 'run', side_effect=lambda *a, **k: g.json.dumps({'filesystems': [entry]})), \
             patch.object(Path, 'is_symlink', return_value=False), \
             patch.object(Path, 'resolve', side_effect=lambda: Path('/state/cache')), \
             patch.object(Path, 'stat', side_effect=lambda: directory), \
             patch.object(g.os, 'statvfs', return_value=SimpleNamespace(f_blocks=2000000, f_frsize=4096)), \
             patch.object(Path, 'read_text', return_value='16777216'):
            with patch.object(g.os, 'stat', return_value=device):
                self.assertEqual(g.cache_bytes(Path('/state/cache')), 8 * g.GIB)
                for key, bad in (('source', '/dev/sda'), ('fstype', 'tmpfs'), ('fsroot', '/subdir'),
                                 ('target', '/state'), ('options', 'rw,nodev'),
                                 ('options', 'rw,nodev,nosuid,context=unconfined')):
                    previous = entry[key]
                    entry[key] = bad
                    with self.assertRaises(RuntimeError):
                        g.cache_bytes(Path('/state/cache'))
                    entry[key] = previous
                with patch.object(Path, 'read_text', return_value='33554432'):
                    with self.assertRaises(RuntimeError):
                        g.cache_bytes(Path('/state/cache'))
    def test_unlinked_cache_accounting(self):
        budget = g.Budget.__new__(g.Budget)
        budget.state, budget.store, budget.base, budget.last = Path('/state'), Path('/store'), {'bytes': 0}, 0
        budget.runtime = True
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_blocks=0)), \
             patch.object(Path, 'iterdir', return_value=[]), patch.object(g, 'allocated', return_value=0), \
             patch.object(g, 'cache_bytes', return_value=8 * g.GIB) as bounded:
            budget.check(True)
            bounded.assert_called_once_with(Path('/state/cache'), None)
    def test_budget(self):
        budget = g.Budget.__new__(g.Budget)
        budget.state, budget.store, budget.base, budget.last = Path('/state'), Path('/store'), {'bytes': 0}, 0
        budget.runtime = False
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_blocks=0)), \
             patch.object(Path, 'iterdir', return_value=[]), \
             patch.object(g, 'allocated', side_effect=[33 * g.GIB, 0, 0, 0]):
            with self.assertRaises(RuntimeError):
                budget.check(True)
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_blocks=0)), \
             patch.object(Path, 'iterdir', return_value=[]), patch.object(g, 'allocated', return_value=0):
            budget.check(True)
    def test_nested_poll_deadline(self):
        budget = g.Budget.__new__(g.Budget)
        budget.state, budget.store, budget.base, budget.last = Path('/state'), Path('/store'), {'bytes': 0}, 0
        budget.runtime = False
        clock, timeouts = [10], []
        def scan(*args, **kwargs):
            self.assertLessEqual(kwargs['timeout'], 1)
            timeouts.append(kwargs['timeout'])
            clock[0] += 2
            return '0 path'
        with patch.object(g.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(g.subprocess, 'check_output', side_effect=scan):
            with self.assertRaisesRegex(RuntimeError, 'readiness deadline'):
                budget.check(True, deadline=11)
        self.assertEqual(timeouts, [1])
    def test_capacity(self):
        for cpu, ram in ((7, 48), (8, 47), (0, 0)):
            with self.assertRaises(RuntimeError):
                g.capacity(cpu, ram * g.GIB)
        g.capacity(8, 48 * g.GIB)
        g.capacity(48, 200 * g.GIB)
    def test_allocation_faults(self):
        for operation in ('network', 'container'):
            for fault in (KeyboardInterrupt(), SystemExit(143), g.subprocess.TimeoutExpired('create', 1)):
                with tempfile.TemporaryDirectory() as directory:
                    state, owned = Path(directory), {'foreign'}
                    (state / 'logs').mkdir()
                    def command(*args, **kwargs):
                        if args[1:3] == ('network', 'create') or args[1] == 'create':
                            kind = 'network' if args[1] == 'network' else 'container'
                            owned.add(args[-1] if kind == 'network' else args[args.index('--name') + 1])
                            if kind == operation:
                                raise fault
                        if args[1] == 'ps' or args[1:3] == ('network', 'ls'):
                            return '\n'.join(owned)
                        if 'rm' in args:
                            owned.discard(args[-1])
                        return '0'
                    with patch.object(g, 'run', side_effect=command), \
                         patch.object(g, 'reachable', return_value=False):
                        with self.assertRaises(type(fault)):
                            g.launch(state, 'GPU-test', None, True)
                    self.assertEqual(owned, {'foreign'})
    def test_preexisting(self):
        with patch.object(g.uuid, 'uuid4', return_value=SimpleNamespace(hex='fixed')), \
             patch.object(g, 'run', return_value='granite-fixed') as command:
            with self.assertRaisesRegex(RuntimeError, 'name exists'):
                g.launch(Path('/state'), 'GPU-test', None, True)
            self.assertEqual(command.call_count, 1)
    def test_cleanup_failure(self):
        commands = []
        def command(*args, **kwargs):
            commands.append(args)
            if args[1] == 'ps' or args[1:3] == ('network', 'ls'):
                return 'owned\nowned-network'
            raise RuntimeError('container refusal')
        with patch.object(g, 'run', side_effect=command):
            with self.assertRaisesRegex(RuntimeError, 'container refusal'):
                g.cleanup('owned', 'owned-network')
        self.assertTrue(any(args[1:3] == ('network', 'rm') for args in commands))
        self.assertTrue(any(args[1] == 'rm' for args in commands))
    def test_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'error.log'
            error = g.subprocess.CalledProcessError(125, 'podman', output='x' * 70000 + 'refused', stderr='')
            with patch.object(g, 'ERROR_LOG', log), \
                 patch.object(g.subprocess, 'check_output', side_effect=error):
                with self.assertRaisesRegex(RuntimeError, str(log)) as caught:
                    g.run('podman', 'create')
            self.assertEqual(len(log.read_text()), 65536)
            self.assertTrue(log.read_text().endswith('refused'))
            self.assertNotIn('refused', str(caught.exception))
    def test_readiness_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'logs').mkdir()
            clock = iter([100])
            with patch.object(g, 'run', return_value=''), patch.object(g, 'cleanup'), \
                 patch.object(g, 'reachable', return_value=False), \
                 patch.object(g, 'observe', return_value={}) as observed, \
                 patch.object(g.time, 'monotonic', side_effect=lambda: next(clock, 131)):
                with self.assertRaisesRegex(RuntimeError, 'readiness deadline'):
                    g.launch(state, 'GPU-test', None, True)
                self.assertEqual(observed.call_args.args[-1], 130)
    def test_drm_devices(self):
        devices = [{'path': '/dev/nvidia2', 'major': 195, 'minor': 2, 'type': 'c'},
                   {'path': '/dev/dri/card2', 'major': 226, 'minor': 2, 'type': 'c'}]
        nodes = {d['path']: g.os.makedev(d['major'], d['minor']) for d in devices}
        with patch.object(g, 'run', return_value='00000000:01:00.0'), \
             patch.object(Path, 'read_text', return_value='GPU UUID: GPU-test\nDevice Minor: 2'), \
             patch.object(g.os, 'stat', side_effect=lambda path: SimpleNamespace(st_rdev=nodes[path])), \
             patch.object(Path, 'resolve', return_value=Path('/sys/devices/0000:01:00.0')):
            g.device_proof(devices, nodes, 'GPU-test')
            with self.assertRaisesRegex(RuntimeError, 'incomplete OCI'):
                g.device_proof(devices, {'/dev/nvidia2': nodes['/dev/nvidia2']}, 'GPU-test')
            with patch.object(Path, 'resolve', return_value=Path('/sys/devices/0000:02:00.0')):
                with self.assertRaisesRegex(RuntimeError, 'another PCI GPU'):
                    g.device_proof(devices, nodes, 'GPU-test')
    def test_desktop_baseline(self):
        baseline = {'gpu': 'GPU-test', 'pid': 17, 'starttime': '500', 'exe': '/approved', 'max_mib': 38}
        stat = '17 (terminal) ' + ' '.join(['S'] + ['0'] * 18 + ['500'])
        with patch.object(g, 'run', return_value='17, 38'), \
             patch.object(Path, 'read_text', return_value=stat), \
             patch.object(g.os, 'readlink', return_value='/approved'):
            g.gpu_processes('GPU-test', baseline)
            with self.assertRaises(RuntimeError):
                g.gpu_processes('GPU-test')
            for boundary, value in (('run', '17, 39'), ('run', '17, 38\n18, 1'),
                                    ('stat', stat.replace('500', '501')), ('exe', '/different')):
                target, field = (g, 'run') if boundary == 'run' else (
                    (Path, 'read_text') if boundary == 'stat' else (g.os, 'readlink'))
                with patch.object(target, field, return_value=value), self.assertRaises(RuntimeError):
                    g.gpu_processes('GPU-test', baseline)
            with patch.object(g, 'run', return_value='18, 1'), \
                 patch.object(Path, 'read_text', return_value='0::/owned/worker'):
                g.gpu_processes('GPU-test', baseline, '/owned')
    def test_baseline_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline.json'
            entry = {'gpu': 'GPU-test', 'pid': 17, 'starttime': '500', 'exe': '/approved', 'max_mib': 38}
            path.write_text(g.json.dumps(entry))
            path.chmod(0o600)
            self.assertEqual(g.desktop_baseline(path, 'GPU-test'), entry)
            with self.assertRaises(RuntimeError):
                g.desktop_baseline(path, 'GPU-other')
            entry['max_mib'] = 39
            path.write_text(g.json.dumps(entry))
            with self.assertRaises(RuntimeError):
                g.desktop_baseline(path, 'GPU-test')
    def test_launch(self):
        args = g.argv(Path('/private'), 'GPU-test', 'container', 'network')
        for flag in ('--pull=never', '--read-only', '--ipc=private', '--cap-drop=all',
                     '--security-opt=no-new-privileges', '--memory=32g', '--memory-swap=32g',
                     '--pids-limit=1024', '--shm-size=4g', 'HF_HUB_OFFLINE=1',
                     'TRANSFORMERS_OFFLINE=1', 'VLLM_PLUGINS=', '/private/model:/model:ro,Z'):
            self.assertIn(flag, args)
        self.assertIn('--cpus=8', args)
        self.assertIn('OMP_NUM_THREADS=8', args)
        self.assertFalse(any(arg.startswith('--cpuset-cpus') for arg in args))
        self.assertEqual(args.count('--device'), 1)
        self.assertIn('nvidia.com/gpu=GPU-test', args)
        self.assertIn('127.0.0.1:8000:8000', args)
        self.assertFalse(any('unconfined' in x or 'privileged' in x or 'label=disable' in x
                             for x in args))

class ServingContractCases(unittest.TestCase):
    def test_pinned_server_uses_private_logging_and_bounded_drain(self):
        captured = []
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'logs').mkdir()
            def command(*args, **kwargs):
                if args[1] == 'create':
                    captured.extend(args)
                    raise RuntimeError('captured serving command')
                return ''
            with patch.object(g, 'exists', return_value=False), patch.object(g, 'run', command), \
                 patch.object(g, 'cleanup'), patch.object(g, 'reachable', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'captured serving command'):
                    g.launch(state, 'GPU-test', None, False)
        self.assertIn('--no-enable-log-requests', captured)
        self.assertNotIn('--disable-log-requests', captured)
        self.assertNotIn('--enable-log-requests', captured)
        drain = int(captured[captured.index('--shutdown-timeout') + 1])
        self.assertEqual(drain, 20)
        self.assertLess(drain, int(next(x for x in captured
                                       if x.startswith('--stop-timeout=')).split('=')[1]))

    def test_exited_server_is_reported_before_removed_cgroup_is_read(self):
        state = {'Running': False, 'OOMKilled': False, 'ExitCode': 2}
        observation = {'GraniteProof': {'cgroup': '/removed'}}
        with patch.object(g, 'run', return_value=g.json.dumps([{'State': state}])), \
             patch.object(g, 'gpu_state', return_value=[0, 0, 0]), \
             patch.object(Path, 'read_text', side_effect=FileNotFoundError('removed cgroup')):
            budget = SimpleNamespace(check=lambda **kwargs: None)
            with self.assertRaisesRegex(RuntimeError, 'server exited.*2'):
                g.active('owned', observation, 'GPU-test', budget, None, g.time.monotonic()+2)
        self.assertEqual(observation['GraniteExitState']['ExitCode'], 2)

class StartupEvidenceCases(unittest.TestCase):
    def test_exit_before_readiness_persists_updated_observation_and_cleans(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'logs').mkdir()
            exited = {'Running': False, 'OOMKilled': False, 'ExitCode': 2}
            def command(*args, **kwargs):
                if args[1] == 'inspect':
                    return g.json.dumps([{'State': exited}])
                return ''
            def observed(name, *args):
                return {'Name': name, 'GraniteProof': {'cgroup': '/removed'}}
            budget = SimpleNamespace(check=lambda **kwargs: None)
            with patch.object(g, 'exists', return_value=False), patch.object(g, 'run', command), \
                 patch.object(g, 'observe', side_effect=observed), \
                 patch.object(g, 'cleanup') as cleanup, \
                 patch.object(g, 'reachable', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'server exited.*2'):
                    g.launch(state, 'GPU-test', budget, False)
            retained = g.json.loads((state / 'logs' / 'inspect.json').read_text())
            self.assertEqual(retained['GraniteExitState']['ExitCode'], 2)
            cleanup.assert_called_once()
