#!/usr/bin/env python3
"""Online acquisition; offline rootless diagnostics and foreground serving."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import uuid

ERROR_LOG = None
GIB = 1024 ** 3
IMAGE = 'docker.io/vllm/vllm-openai@sha256:6ee133356d49ed24cee03dd0cda3d3980279a11c107ce3e752c89e76540f41c9'
REV = 'a7042144125ce5ae64f89610e8289647fc000b9a'
MODEL = 'ibm-granite/granite-4.2-8b'
FILES = set('chat_template.jinja config.json generation_config.json merges.txt '
            'model.safetensors.index.json special_tokens_map.json tokenizer.json '
            'tokenizer_config.json vocab.json'.split())
FILES.update(f'model-{n:05d}-of-00004.safetensors' for n in range(1, 5))
class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(newurl.startswith('https://'), 'acquire: non-HTTPS redirect refused')
        return super().redirect_request(req, fp, code, msg, headers, newurl)

HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}), HTTPSRedirect())

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def remaining(deadline):
    seconds = deadline - time.monotonic()
    require(seconds > 0, 'runtime: readiness deadline exceeded')
    return seconds

def run(*args, deadline=None):
    timeout = min(60, remaining(deadline)) if deadline else 60
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=timeout).strip()
    except (subprocess.SubprocessError, OSError) as error:
        detail = getattr(error, 'stderr', None) or getattr(error, 'output', None) or str(error)
        if isinstance(detail, bytes):
            detail = detail.decode(errors='replace')
        require(ERROR_LOG is not None, 'command: private error log was not initialized')
        operation = ' '.join(args[:2])
        previous = ERROR_LOG.read_bytes() if ERROR_LOG.exists() else b''
        ERROR_LOG.write_bytes((previous + f'\n{operation}: {detail}'.encode())[-65536:])
        raise RuntimeError(f'{operation} failed; inspect {ERROR_LOG}') from error

def allocated(path, store=False, deadline=None):
    prefix = ['podman', 'unshare'] if store else []
    return int(run(*prefix, 'du', '-sx', '-B1', str(path), deadline=deadline).split()[0])

def capacity(cpu, ram):
    require(cpu >= 8 and ram >= 48 * GIB, 'preflight: need 8 CPUs and 48 GiB available RAM')

def selected(meta):
    require(meta['sha'] == REV, 'acquire: wrong model revision')
    items = [x for x in meta['siblings'] if x['rfilename'] in FILES]
    require(len(items) == len(FILES) and {x['rfilename'] for x in items} == FILES,
            'acquire: missing or duplicate required model file')
    for item in items:
        require(type(item['size']) is int and 0 < item['size'] <= 20 * GIB,
                'acquire: invalid file size')
        digest = item.get('lfs', {}).get('sha256', item['blobId'])
        require(re.fullmatch('[0-9a-f]{64}' if 'lfs' in item else '[0-9a-f]{40}', digest),
                'acquire: malformed content hash')
        require('lfs' not in item or item['lfs']['size'] == item['size'],
                'acquire: inconsistent LFS size')
    require(sum(x['size'] for x in items) <= 20 * GIB, 'acquire: model exceeds 20 GiB')
    return items

def verify(path, item, deadline=None):
    require(path.is_file() and not path.is_symlink(), 'verify: missing or unsafe model file')
    size = item['size']
    require(path.stat().st_size == size, 'verify: file size mismatch')
    digest = hashlib.sha256() if 'lfs' in item else hashlib.sha1()
    if 'lfs' not in item:
        digest.update(f'blob {size}\0'.encode())
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            if deadline is not None:
                remaining(deadline)
            digest.update(block)
    expected = item['lfs']['sha256'] if 'lfs' in item else item['blobId']
    require(digest.hexdigest() == expected, 'verify: content hash mismatch')

def download(source, path, item, budget):
    partial = path.with_suffix(path.suffix + '.part')
    require(not partial.is_symlink(), 'acquire: unsafe partial path')
    with partial.open('wb') as target:
        count = 0
        for block in iter(lambda: source.read(1024 * 1024), b''):
            count += len(block)
            require(count <= item['size'], 'acquire: response exceeds declared size')
            target.write(block)
            budget()
    verify(partial, item)
    partial.replace(path)

def cache_bytes(path, deadline=None):
    entry = json.loads(run('findmnt', '--json', '--mountpoint', str(path), '-o',
                           'TARGET,SOURCE,FSTYPE,FSROOT,OPTIONS', deadline=deadline))['filesystems']
    require(len(entry) == 1, 'cache: require one dedicated mount; follow provisioning')
    entry = entry[0]
    source, options = entry['source'], set(entry['options'].split(','))
    require(not path.is_symlink() and entry['target'] == str(path.resolve())
            and entry['fstype'] == 'ext4' and entry['fsroot'] == '/'
            and re.fullmatch(r'/dev/loop[0-9]+', source)
            and {'rw', 'nosuid', 'nodev'} <= options and 'noexec' not in options
            and not any('context=' in option for option in options),
            'cache: require private ext4 loop filesystem root with nosuid,nodev and native labels')
    directory, device = path.stat(), os.stat(source)
    sectors = int((Path('/sys/class/block') / Path(source).name / 'size').read_text())
    filesystem = os.statvfs(path)
    require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.getuid()
            and stat.S_IMODE(directory.st_mode) == 0o700 and stat.S_ISBLK(device.st_mode)
            and directory.st_dev == device.st_rdev and sectors * 512 == 8 * GIB
            and 0 < filesystem.f_blocks * filesystem.f_frsize <= 8 * GIB,
            'cache: mount ownership/device/capacity mismatch; follow provisioning')
    return 8 * GIB

class Budget:
    def __init__(self, state, info, runtime=False):
        self.runtime = runtime
        self.state = state
        self.store = Path(info['store']['graphRoot'])
        self.last = 0
        record = state / 'store-baseline.json'
        if not record.exists():
            for path in (state, self.store):
                require(shutil.disk_usage(path).free >= 80 * GIB,
                        'acquire: reserve 80 GiB free on each affected filesystem')
            record.write_text(json.dumps({'store': str(self.store),
                                          'bytes': allocated(self.store, True)}))
        self.base = json.loads(record.read_text())
        require(self.base['store'] == str(self.store), 'state: Podman store changed; inspect state')
    def check(self, force=False, deadline=None):
        if not force and time.monotonic() - self.last < 5:
            return
        self.last = time.monotonic()
        buckets = [max(0, allocated(self.store, True, deadline) - self.base['bytes'])
                   + allocated(self.state / 'pull-tmp', deadline=deadline),
                   allocated(self.state / 'model', deadline=deadline),
                   cache_bytes(self.state / 'cache', deadline) if self.runtime
                   else max(8 * GIB, allocated(self.state / 'cache', deadline=deadline)), 0]
        buckets[3] = self.state.stat().st_blocks * 512 + sum(allocated(path, deadline=deadline)
            for path in self.state.iterdir() if path.name not in {'model', 'cache', 'pull-tmp'})
        for size, limit in zip(buckets, (32, 20, 8, 4)):
            require(size <= limit * GIB, f'disk: {limit} GiB bucket exceeded; inspect private state')
        require(sum(buckets) <= 64 * GIB, 'disk: 64 GiB total exceeded; inspect private state')

def image(deadline=None):
    value = json.loads(run('podman', 'image', 'inspect', IMAGE, deadline=deadline))[0]
    require(value['Architecture'] == 'amd64' and value['Os'] == 'linux'
            and IMAGE in value['RepoDigests'], 'verify: image digest/platform mismatch')

def acquire(state, budget):
    for path in (state, budget.store):
        require(shutil.disk_usage(path).free >= 80 * GIB, 'acquire: insufficient free disk')
    env = dict(os.environ, TMPDIR=str(state / 'pull-tmp'))
    with (state / 'logs' / 'pull.log').open('w') as log:
        child = subprocess.Popen(['podman', 'pull', '--platform=linux/amd64', IMAGE],
                                 stdout=log, stderr=log, env=env)
        try:
            while child.poll() is None:
                budget.check()
                time.sleep(1)
            require(child.returncode == 0, 'acquire: image pull failed; inspect private pull.log')
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
    image()
    url = f'https://huggingface.co/api/models/{MODEL}/revision/{REV}?blobs=true'
    with HTTP.open(url, timeout=30) as response:
        raw = response.read(1024 * 1024 + 1)
    require(len(raw) <= 1024 * 1024, 'acquire: oversized model metadata')
    meta = json.loads(raw)
    items = selected(meta)
    for item in items:
        path = state / 'model' / item['rfilename']
        if path.exists():
            verify(path, item)
            continue
        with HTTP.open(f'https://huggingface.co/{MODEL}/resolve/{REV}/{path.name}',
                       timeout=30) as response:
            require(response.url.startswith('https://'), 'acquire: non-HTTPS redirect refused')
            download(response, path, item, budget.check)
    (state / 'metadata.json').write_text(json.dumps(meta))
    budget.check(True)
    print('Acquisition verified; model and image identities match frozen pins.')

def gpu_state(gpu, deadline=None):
    require(re.fullmatch(r'GPU-[0-9a-fA-F-]{36}', gpu), 'preflight: require exact GPU UUID')
    fields = 'uuid,name,memory.total,memory.free,memory.used'
    rows = [x.split(', ') for x in run('nvidia-smi', f'--query-gpu={fields}',
                                     '--format=csv,noheader,nounits', deadline=deadline).splitlines()]
    matches = [row for row in rows if row[0] == gpu]
    require(len(matches) == 1 and matches[0][1] == 'NVIDIA RTX A6000',
            'preflight: selected GPU must be the A6000')
    return [float(x) * 1024 ** 2 for x in matches[0][2:]]

def desktop_baseline(path, gpu):
    if path is None:
        return None
    require(path.is_file() and not path.is_symlink() and path.stat().st_uid == os.getuid()
            and path.stat().st_mode & 0o077 == 0 and path.stat().st_size <= 4096,
            'baseline: require small private owned JSON file supplied by operator')
    entry = json.loads(path.read_text())
    require(set(entry) == {'gpu', 'pid', 'starttime', 'exe', 'max_mib'}
            and entry['gpu'] == gpu and type(entry['pid']) is int and entry['pid'] > 0
            and isinstance(entry['starttime'], str) and entry['starttime'].isdigit()
            and isinstance(entry['exe'], str) and entry['exe'].startswith('/')
            and entry['max_mib'] == 38, 'baseline: invalid approved identity or 38 MiB bound')
    return entry

def gpu_processes(gpu, baseline=None, group=None, deadline=None):
    rows = run('nvidia-smi', '-i', gpu, '--query-compute-apps=pid,used_gpu_memory',
               '--format=csv,noheader,nounits', deadline=deadline).splitlines()
    for row in rows:
        pid, usage = row.split(', ')
        process = Path('/proc') / str(int(pid))
        if group:
            membership = (process / 'cgroup').read_text().strip().split('::', 1)[1]
            if membership == group or membership.startswith(group + '/'):
                continue
        require(baseline is not None and int(pid) == baseline['pid'],
                'GPU: competing process; operator must inspect')
        starttime = (process / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        require(starttime == baseline['starttime'] and os.readlink(process / 'exe') == baseline['exe']
                and 0 <= float(usage) <= baseline['max_mib'],
                'GPU: approved desktop identity changed or exceeds 38 MiB; stop and inspect')

def preflight(state, gpu, baseline=None, deadline=None):
    info = json.loads(run('podman', 'info', '--format=json', deadline=deadline))
    host = info['host']
    security = host['security']
    require(os.getuid() != 0 and security['rootless'] and not host['serviceIsRemote'],
            'preflight: local rootless Podman required')
    require(host['arch'] == 'amd64' and host['os'] == 'linux', 'preflight: linux/amd64 required')
    require(host['cgroupVersion'] == 'v2'
            and {'cpu', 'memory', 'pids'} <= set(host['cgroupControllers']),
            'preflight: missing cgroup v2 resource controllers')
    require(security['seccompEnabled'] and security['selinuxEnabled']
            and run('getenforce', deadline=deadline) == 'Enforcing', 'preflight: enforcing SELinux/seccomp required')
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    capacity(len(os.sched_getaffinity(0)), int(memory['MemAvailable'].split()[0]) * 1024)
    total, free, used = gpu_state(gpu, deadline)
    require(free >= total * .8 + 6 * GIB, 'preflight: insufficient GPU memory')
    gpu_processes(gpu, baseline, deadline=deadline)
    image(deadline)
    require({p.name for p in (state / 'model').iterdir()} == FILES,
            'verify: unexpected or missing model directory entry')
    for item in selected(json.loads((state / 'metadata.json').read_text())):
        verify(state / 'model' / item['rfilename'], item, deadline)
    return info

def argv(state, gpu, name, network):
    args = ['podman', 'create', '--name', name, '--pull=never', '--network', network,
            '--no-hosts', '--http-proxy=false', '--read-only', '--read-only-tmpfs=false',
            '--image-volume=ignore', '--cap-drop=all', '--security-opt=no-new-privileges',
            '--security-opt=label=type:granite_server.process', '--ipc=private', '--pid=private',
            '--cgroupns=private', '--memory=32g', '--memory-swap=32g', '--cpus=8',
            '--pids-limit=1024', '--shm-size=4g', '--tmpfs=/dev/shm:rw,size=4g,mode=1777',
            '--tmpfs=/tmp:rw,size=1g,mode=1777',
            '--tmpfs=/run:rw,size=64m', '--device', f'nvidia.com/gpu={gpu}',
            '--timeout=3600', '--stop-timeout=30', '--log-driver=k8s-file',
            '--log-opt=max-size=64mb', f'--log-opt=path={state}/logs/container.log',
            '-p', '127.0.0.1:8000:8000', '-v', f'{state}/model:/model:ro,Z',
            '-v', f'{state}/cache:/cache:rw,Z']
    env = {'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
           'VLLM_NO_USAGE_STATS': '1', 'VLLM_PLUGINS': '', 'HOME': '/tmp',
           'HF_HOME': '/cache/hf', 'XDG_CACHE_HOME': '/cache', 'VLLM_CACHE_ROOT': '/cache/vllm',
           'TORCHINDUCTOR_CACHE_DIR': '/cache/inductor', 'TRITON_CACHE_DIR': '/cache/triton',
           'CUDA_CACHE_PATH': '/cache/cuda', 'OMP_NUM_THREADS': '8',
           'MKL_NUM_THREADS': '8', 'OPENBLAS_NUM_THREADS': '8'}
    for key, value in env.items():
        args += ['-e', f'{key}={value}']
    return args

DIAGNOSTIC_SERVER = ('import http.server,os,signal,sys; os.chdir("/tmp"); '
                     'signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); '
                     'http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler, '
                     'port=8000, bind="0.0.0.0")')

PROBE = '''import json,mmap,os,sys,tempfile
from importlib.metadata import version
assert version("vllm")=="0.32.0"
nodes={p:os.stat(p).st_rdev for p in json.loads(sys.argv[1])}
assert all(os.statvfs(p).f_flag & os.ST_RDONLY for p in ("/","/model"))
assert os.statvfs("/tmp").f_blocks*os.statvfs("/tmp").f_frsize==1024**3
print(json.dumps(nodes))
assert os.statvfs("/dev/shm").f_blocks*os.statvfs("/dev/shm").f_frsize==4*1024**3
with open("/dev/shm/granite-probe","x") as probe:probe.write("ok")
os.unlink("/dev/shm/granite-probe")
with tempfile.TemporaryFile(dir="/cache") as cache:
 cache.write(b"cache-probe");cache.flush();cache.seek(0)
 assert cache.read()==b"cache-probe"
 with mmap.mmap(cache.fileno(),0,prot=mmap.PROT_READ|mmap.PROT_EXEC) as mapped:
  assert mapped[:]==b"cache-probe"
'''
NETWORK = '''import json,socket,sys
for host,port in json.loads(sys.argv[1]):
 s=socket.socket();s.settimeout(1)
 try:s.connect((host,port))
 except OSError:pass
 else:raise RuntimeError("network boundary reachable")
 finally:s.close()
'''

def device_proof(devices, nodes, gpu, deadline=None):
    expected = {d['path']: os.makedev(d['major'], d['minor']) for d in devices}
    require(len(expected) == len(devices) and nodes == expected, 'runtime: incomplete OCI device view')
    pci = run('nvidia-smi', '-i', gpu, '--query-gpu=pci.bus_id',
              '--format=csv,noheader', deadline=deadline)
    info = Path('/proc/driver/nvidia/gpus') / pci.lower()[-12:] / 'information'
    fields = dict(line.split(':', 1) for line in info.read_text().splitlines())
    require(fields['GPU UUID'].strip() == gpu, 'runtime: NVIDIA device identity mismatch')
    minor = fields['Device Minor'].strip()
    indexed = [d for d in devices if re.fullmatch('/dev/nvidia[0-9]+', d['path'])]
    require(len(indexed) == 1 and indexed[0]['minor'] == int(minor), 'runtime: wrong GPU device')
    for device in devices:
        path, major, number = device['path'], device['major'], device['minor']
        require(device['type'] == 'c' and os.stat(path).st_rdev == expected[path],
                'runtime: host/OCI device mismatch')
        require(path.startswith(('/dev/nvidia', '/dev/dri/')), 'runtime: unexpected device grant')
        if path.startswith('/dev/dri/'):
            require((Path(f'/sys/dev/char/{major}:{number}') / 'device').resolve().name
                    == pci.lower()[-12:], 'runtime: DRM device belongs to another PCI GPU')

def observe(name, gpu, deadline):
    value = json.loads(run('podman', 'inspect', name, deadline=deadline))[0]
    pid = value['State']['Pid']
    require(pid > 0 and not value['State']['OOMKilled'], 'runtime: exited or OOM killed')
    status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines())
    require(status['NoNewPrivs'].strip() == '1' and status['Seccomp'].strip() == '2'
            and int(status['CapEff'].strip(), 16) == 0, 'runtime: process security mismatch')
    label = Path(f'/proc/{pid}/attr/current').read_text()
    require(':granite_server.process:s0:c' in label, 'runtime: SELinux type/MCS mismatch')
    group = Path(f'/proc/{pid}/cgroup').read_text().strip().split('::', 1)[1]
    root = Path('/sys/fs/cgroup') / group.lstrip('/')
    for file, expected in [('memory.max', 32 * GIB), ('memory.swap.max', 0), ('pids.max', 1024)]:
        require(int((root / file).read_text()) == expected, f'runtime: {file} mismatch')
    quota, period = (root / 'cpu.max').read_text().split()
    require(int(quota) / int(period) == 8, 'runtime: CPU quota mismatch')
    require(run('podman', 'exec', name, 'nvidia-smi', '--query-gpu=uuid',
                '--format=csv,noheader', deadline=deadline) == gpu, 'runtime: GPU identity mismatch')
    devices = json.loads(Path(value['OCIConfigPath']).read_text())['linux']['devices']
    paths = json.dumps([device['path'] for device in devices])
    nodes = json.loads(run('podman', 'exec', name, 'python3', '-c', PROBE, paths, deadline=deadline))
    device_proof(devices, nodes, gpu, deadline)
    remaining(deadline)
    require(int(dict(line.split() for line in (root / 'memory.events').read_text().splitlines())
                ['oom_kill']) == 0, 'runtime: cgroup OOM event')
    value['GraniteProof'] = {'devices': nodes, 'status': status, 'label': label, 'cgroup': group}
    return value

def readiness(diagnostic, deadline):
    end = min(deadline, time.monotonic() + 1)
    path = '/' if diagnostic else '/health'
    with socket.create_connection(('127.0.0.1', 8000), timeout=remaining(end)) as connection:
        connection.settimeout(remaining(end))
        connection.sendall(f'GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
        headers = b''
        while b'\r\n\r\n' not in headers:
            seconds = end - time.monotonic()
            if seconds <= 0:
                raise TimeoutError('readiness: total exchange exceeded one second')
            connection.settimeout(seconds)
            block = connection.recv(4096)
            if not block or len(headers) + len(block) > 65536:
                return False
            headers += block
        if time.monotonic() >= end:
            raise TimeoutError('readiness: total exchange exceeded one second')
        status = headers.split(b'\r\n', 1)[0]
        return re.fullmatch(rb'HTTP/1\.[01] 200(?: [^\r\n]*)?', status) is not None

def reachable(host, port, deadline=None):
    timeout = min(1, remaining(deadline)) if deadline else 1
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def network_check(name, network, deadline):
    net = json.loads(run('podman', 'network', 'inspect', network, deadline=deadline))[0]
    require(net['internal'] and not net['dns_enabled'] and not net['ipv6_enabled']
            and all('gateway' not in item for item in net['subnets']),
            'runtime: network must be internal, IPv4-only, without DNS or gateway')
    addresses = json.loads(run('ip', '-j', 'address', 'show', deadline=deadline))
    hosts = [a['local'] for link in addresses for a in link['addr_info']
             if a['family'] == 'inet' and a['scope'] != 'host']
    require(hosts, 'diagnostic: need non-loopback host address to test publication')
    require(all(not reachable(host, 8000, deadline) for host in hosts), 'runtime: non-loopback ingress')
    with socket.socket() as sentinel:
        sentinel.bind(('0.0.0.0', 0))
        sentinel.listen()
        port = sentinel.getsockname()[1]
        targets = [('1.1.1.1', 443), ('169.254.1.2', port)] + [(x, port) for x in hosts]
        run('podman', 'exec', name, 'python3', '-c', NETWORK, json.dumps(targets), deadline=deadline)

def exists(name, network=False):
    args = ['network', 'ls', '-q'] if network else ['ps', '-a', '--format={{.Names}}']
    return name in run('podman', *args).splitlines()

def cleanup(name, network):
    errors = []
    handlers = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
    actions = [('stop', '--ignore', '--time=30', name),
               ('inspect', '--format={{.State.ExitCode}}', name),
               ('rm', '--ignore', '--force', name), ('network', 'rm', network)]
    try:
        for action in actions:
            try:
                if action[0] == 'inspect' and not exists(name):
                    continue
                if action[0] == 'network' and not exists(network, True):
                    continue
                result = run('podman', *action)
                require(action[0] != 'inspect' or result != '137', 'cleanup: forced kill')
            except Exception as error:
                errors.append(str(error))
        for identity, is_network in ((name, False), (network, True)):
            try:
                require(not exists(identity, is_network), 'cleanup: owned resource remains')
            except Exception as error:
                errors.append(str(error))
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    require(not errors, 'cleanup failed: ' + '; '.join(errors))

def active(name, observation, gpu, budget, baseline, deadline):
    budget.check(deadline=deadline)
    used = gpu_state(gpu, deadline)[2]
    group = observation['GraniteProof']['cgroup']
    root = Path('/sys/fs/cgroup') / group.lstrip('/')
    sample = {'gpu_sample_bytes': used,
              'memory_current_bytes': int((root / 'memory.current').read_text()),
              'memory_peak_bytes': int((root / 'memory.peak').read_text())}
    peaks = observation.setdefault('GranitePeaks', {})
    for key, value in sample.items():
        peaks[key] = max(value, peaks.get(key, 0))
    require(used <= 40 * GIB, 'runtime: observed GPU memory exceeds 40 GiB')
    gpu_processes(gpu, baseline, group, deadline)
    events = dict(line.split() for line in (root / 'memory.events').read_text().splitlines())
    require(events['oom_kill'] == '0', 'runtime: cgroup OOM; stop failed trial')
    current = json.loads(run('podman', 'inspect', name, deadline=deadline))[0]['State']
    require(current['Running'] and not current['OOMKilled'], 'runtime: server stopped/OOM')
    return sample

def launch(state, gpu, budget, diagnostic, baseline=None, workload=None, session_deadline=None):
    token = uuid.uuid4().hex
    name, network = 'granite-' + token, 'granite-net-' + token
    require(not exists(name) and not exists(network, True), 'launch: resource name exists; refuse')
    observation = {}
    try:
        (state / 'logs' / 'resources.json').write_text(json.dumps([name, network]))
        run('podman', 'network', 'create', '--internal', '--disable-dns', network)
        args = argv(state, gpu, name, network)
        if diagnostic:
            args += ['--entrypoint=python3', IMAGE, '-c', DIAGNOSTIC_SERVER]
        else:
            args += ['--entrypoint=vllm', IMAGE, 'serve', '/model', '--tokenizer', '/model',
                     '--served-model-name', 'granite', '--host', '0.0.0.0', '--port', '8000',
                     '--dtype', 'bfloat16', '--kv-cache-dtype', 'auto', '--tensor-parallel-size', '1',
                     '--attention-config', '{"backend":"FLASH_ATTN","flash_attn_version":2}',
                     '--max-model-len', '4096', '--max-num-seqs', '2',
                     '--max-num-batched-tokens', '4096', '--gpu-memory-utilization', '0.80',
                     '--generation-config', 'vllm', '--override-generation-config',
                     '{"max_new_tokens":256}', '--disable-log-requests', '--disable-uvicorn-access-log']
        run(*args)
        start = time.monotonic()
        deadline = min(start + (30 if diagnostic else 600), session_deadline or float('inf'))
        run('podman', 'start', name, deadline=deadline)
        observation = observe(name, gpu, deadline)
        remaining(deadline)
        (state / 'logs' / 'inspect.json').write_text(json.dumps(observation))
        ready = False
        while time.monotonic() - start < 3600:
            active_deadline = deadline if not ready else min(
                start + 3600, session_deadline or float('inf'))
            active(name, observation, gpu, budget, baseline, active_deadline)
            if not ready:
                remaining(deadline)
                try:
                    ready = readiness(diagnostic, deadline)
                except OSError:
                    pass
                remaining(deadline)
                if ready:
                    network_check(name, network, deadline)
                    remaining(deadline)
                    print('Diagnostic passed.' if diagnostic else 'Ready: http://127.0.0.1:8000')
                    if workload:
                        return workload(name, observation, start, deadline)
            if diagnostic and ready:
                return
            time.sleep(1)
        raise RuntimeError('runtime: 60-minute session ended; stop and record incomplete trial')
    finally:
        original = sys.exc_info()[1]
        try:
            (state / 'logs' / 'runtime-peaks.json').write_text(
                json.dumps(observation.get('GranitePeaks', {})))
        finally:
            cleanup(name, network)
        try:
            require(not reachable('127.0.0.1', 8000), 'cleanup: endpoint remains; inspect host')
        except Exception as error:
            raise RuntimeError(f'{original or "run ended"}; {error}') from error

def main():
    global ERROR_LOG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['acquire', 'check', 'serve'])
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--gpu')
    parser.add_argument('--desktop-baseline', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    state = args.state.absolute()
    require(not any(c in str(state) for c in ':\n'), 'state: colon/newline path refused')
    require(not state.is_symlink() and state == state.resolve(), 'state: symlink path refused')
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(state.stat().st_uid == os.getuid() and state.stat().st_mode & 0o077 == 0,
            'state: require owned mode-0700 directory')
    require(not any(p.is_symlink() for p in state.rglob('*')), 'state: symlink entry refused')
    with (state / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for folder in ('model', 'cache', 'logs', 'pull-tmp'):
            (state / folder).mkdir(mode=0o700, exist_ok=True)
        ERROR_LOG = state / 'logs' / 'command-error.log'
        info = json.loads(run('podman', 'info', '--format=json'))
        require(info['host']['security']['rootless'] and os.getuid() != 0,
                'preflight: rootless Podman required')
        budget = Budget(state, info, runtime=args.action != 'acquire')
        if args.action == 'acquire':
            acquire(state, budget)
        else:
            require(args.gpu, 'preflight: --gpu UUID required')
            baseline = desktop_baseline(args.desktop_baseline, args.gpu)
            preflight(state, args.gpu, baseline)
            budget.check(True)
            launch(state, args.gpu, budget, True, baseline)
            if args.action == 'serve':
                preflight(state, args.gpu, baseline)
                launch(state, args.gpu, budget, False, baseline)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(143))
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'granite: {error}; stop and inspect private state before retrying', file=sys.stderr)
        sys.exit(1)
