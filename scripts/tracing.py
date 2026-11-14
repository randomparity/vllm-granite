#!/usr/bin/env python3
"""Rootless host observer for explicitly requested diagnostic workload captures."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time
import uuid

LIMIT = 256 * 1024 ** 2
ANNOTATION = 'org.granite.capture'


def require(ok, message):
    if not ok:
        raise RuntimeError('trace: ' + message)


def write(folder, name, value):
    temporary = folder / (name + '.tmp')
    with temporary.open('w') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(value, output)
    temporary.replace(folder / name)


def identity(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def read(folder, name):
    return json.loads((folder / name).read_text())


def validate(path, root, pidns=False):
    """Reject incomplete lifecycle evidence without interpreting syscall requirements."""
    seen, exited, children, pending = set(), set(), set(), {}
    records, executed, digest, size = 0, False, hashlib.sha256(), 0
    with path.open('rb') as source:
        while raw := source.readline(65537):
            require(len(raw) <= 65536 and raw.endswith(b'\n'), 'truncated/oversized trace line')
            digest.update(raw)
            size += len(raw)
            match = re.fullmatch(rb'(\d+)\s+\d+\.\d+\s+(.+)\n', raw)
            require(match is not None, 'unknown trace format; coverage unproved')
            pid, body = int(match[1]), match[2].decode('ascii')
            require('<unavailable>' not in body, 'unavailable syscall evidence')
            require(pid not in exited, 'record after terminal task exit')
            seen.add(pid)
            terminal = r'\+\+\+ (?:exited with \d+|killed by SIG[A-Z0-9]+'
            if re.fullmatch(terminal + r'(?: \(core dumped\))?) \+\+\+', body):
                exited.add(pid)
                pending.pop(pid, None)
                continue
            if body.startswith('--- SIG') and body.endswith(' ---'):
                continue
            resumed = re.match(r'<\.\.\. (\w+) resumed>', body)
            if resumed:
                previous = pending.pop(pid, None)
                require(previous == resumed[1] or pid == root and not executed,
                        'unmatched resumed syscall')
                name = resumed[1]
            else:
                call = re.match(r'(\w+)\(', body)
                require(call is not None and pid not in pending, 'unrecognized/incomplete syscall')
                name = call[1]
                records += 1
            if body.endswith('<unfinished ...>'):
                pending[pid] = name
                continue
            returned = re.search(r' = (-?0x[0-9a-f]+|-?\d+)(?:\s|$)', body)
            require(returned is not None or ' = ?' in body, 'missing syscall completion')
            value = int(returned[1], 0) if returned else None
            if name in ('clone', 'clone3', 'fork', 'vfork') and value is not None and value > 0:
                translated = re.search(r"/\* (\d+) in strace's PID NS \*/",
                                       body[returned.end():])
                require(translated is not None or not pidns, 'child PID translation missing')
                children.add(int(translated[1]) if translated else value)
            if name in ('execve', 'execveat') and pid == root and value == 0:
                executed = True
    require(0 < size < LIMIT, 'empty capture or byte budget exhausted')
    require(executed and seen == children | {root} and seen == exited and not pending,
            'application exec/task lineage/final exits incomplete')
    return {'status': 'complete', 'tasks': len(seen), 'syscall_records': records,
            'bytes': size, 'sha256': digest.hexdigest()}


def observe(folder, pid):
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))
    with (folder / 'observer.stderr').open('w') as error:
        observer = subprocess.Popen(['strace', '-f', '--always-show-pid', '-ttt',
            '--decode-pids=pidns', '-e', 'raw=!clone,clone3,fork,vfork',
            '-o', str(folder / 'raw.strace'), '-p', str(pid)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=error)
        write(folder, 'observer.json', {'pid': observer.pid, 'start': identity(observer.pid)})
        code = observer.wait()
    write(folder, 'exit.json', {'code': code})


def hook(folder):
    raw = sys.stdin.buffer.read(65537)
    require(len(raw) <= 65536, 'oversized OCI state')
    state, config = json.loads(raw), read(folder, 'config.json')
    pid = state['pid']
    require(type(pid) is int and pid > 1 and state['status'] == 'created'
            and re.fullmatch('[0-9a-f]{64}', state['id'])
            and state['annotations'][ANNOTATION] == config['token'], 'OCI identity mismatch')
    require(Path(f'/proc/{pid}').stat().st_uid == os.getuid(), 'foreign process owner')
    with (folder / 'supervisor.stderr').open('w') as error:
        supervisor = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
            '--observer', str(folder), str(pid)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=error, start_new_session=True)
    write(folder, 'supervisor.json', {'pid': supervisor.pid, 'start': identity(supervisor.pid)})
    end = time.monotonic() + 4
    while time.monotonic() < end:
        require(supervisor.poll() is None, 'observer exited before prearming')
        if (folder / 'observer.json').exists():
            observer = read(folder, 'observer.json')
            status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status')
                          .read_text().splitlines() if ':' in line)
            if int(status['TracerPid']) == observer['pid']:
                write(folder, 'armed.json', {'root': pid, 'container': state['id'],
                                           'time_ns': time.time_ns(),
                                           'pidns': os.readlink('/proc/self/ns/pid') !=
                                           os.readlink(f'/proc/{pid}/ns/pid')})
                return
        time.sleep(.01)
    raise RuntimeError('trace: prearming deadline exceeded')


class Capture:
    def __init__(self, folder):
        self.folder, self.container, self.summary = folder, None, None
        folder.mkdir(mode=0o700)
        require(folder == folder.resolve() and folder.stat().st_uid == os.getuid()
                and folder.stat().st_mode & 0o077 == 0, 'private owned capture directory required')
        version = subprocess.check_output(['strace', '--version'], text=True, timeout=5)
        self.version = version.splitlines()[0]
        require(re.fullmatch(r'strace -- version \d+\.\d+(?:\.\d+)?', self.version),
                'unsupported tracer version output')
        self.token = uuid.uuid4().hex
        write(folder, 'config.json', {'token': self.token})
        hooks = folder / 'hooks'
        hooks.mkdir(mode=0o700)
        script = str(Path(__file__).resolve())
        definition = {'version': '1.0.0', 'hook': {'path': sys.executable,
            'args': [sys.executable, script, '--hook', str(folder)], 'timeout': 6},
            'when': {'annotations': {'^org\\.granite\\.capture$': '^' + self.token + '$'}},
            'stages': ['prestart']}
        write(hooks, '00-capture.json', definition)

    def arguments(self, start=False):
        values = ['--hooks-dir=' + str(self.folder / 'hooks')]
        if not start:
            values.append('--annotation=' + ANNOTATION + '=' + self.token)
        return values

    def check(self):
        require((self.folder / 'armed.json').exists(), 'prestart acknowledgment missing')
        armed = read(self.folder, 'armed.json')
        require(armed['container'] == self.container, 'created container identity mismatch')
        if (self.folder / 'exit.json').exists():
            require(read(self.folder, 'exit.json')['code'] == 0, 'observer failed; coverage lost')
        else:
            observer = read(self.folder, 'observer.json')
            require(identity(observer['pid']) == observer['start'], 'observer identity lost')
        for name in ('raw.strace', 'observer.stderr', 'supervisor.stderr'):
            path = self.folder / name
            require(not path.exists() or path.stat().st_size < LIMIT,
                    'capture byte budget exhausted')

    def finish(self):
        try:
            end = time.monotonic() + 5
            while not (self.folder / 'exit.json').exists() and time.monotonic() < end:
                time.sleep(.01)
            self.check()
            require((self.folder / 'exit.json').exists(),
                    'observer did not close after teardown')
            error = (self.folder / 'observer.stderr').read_text()
            require(all(re.fullmatch(r'(?:[^\n]*strace): Process \d+ attached'
                                     r'(?: with \d+ threads)?', line)
                        for line in error.splitlines()),
                    'observer diagnostics invalidate coverage; inspect private stderr')
            require(not (self.folder / 'supervisor.stderr').stat().st_size,
                    'supervisor failed; inspect private stderr')
            armed = read(self.folder, 'armed.json')
            result = validate(self.folder / 'raw.strace', armed['root'], armed['pidns'])
            result['tracer'] = self.version
            write(self.folder, 'summary.json', result)
            self.summary = result
            return result
        finally:
            for name in ('observer.json', 'supervisor.json'):
                if (self.folder / name).exists():
                    process = read(self.folder, name)
                    try:
                        if identity(process['pid']) == process['start']:
                            os.kill(process['pid'], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    except FileNotFoundError:
                        pass


if __name__ == '__main__':
    os.umask(0o077)
    try:
        require(len(sys.argv) in (3, 4), 'invalid observer invocation')
        folder = Path(sys.argv[2])
        require(folder == folder.resolve() and folder.is_dir()
                and folder.stat().st_uid == os.getuid() and folder.stat().st_mode & 0o077 == 0,
                'private owned capture directory required')
        if sys.argv[1] == '--hook' and len(sys.argv) == 3:
            hook(folder)
        elif sys.argv[1] == '--observer' and len(sys.argv) == 4:
            observe(folder, int(sys.argv[3]))
        else:
            raise RuntimeError('trace: invalid observer invocation')
    except Exception:
        print('trace: observer failed; inspect private capture artifacts', file=sys.stderr)
        sys.exit(1)
