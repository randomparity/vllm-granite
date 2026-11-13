#!/usr/bin/env python3
"""Explicit, bounded baseline trial; ordinary tests never launch a GPU workload."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
import fcntl
import errno
import hashlib
import http.client
import inspect
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import uuid

if __package__:
    from . import granite as g
else:
    import granite as g


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def seconds(deadline):
    value = deadline - time.monotonic()
    g.require(value > 0, 'request: absolute deadline exceeded; stop trial')
    return value


def request_deadline(trial, startup=None):
    return min(time.monotonic() + 120, trial, startup or float('inf'))


def fixture_payloads(tokenizer):
    def count(text):
        return len(tokenizer.apply_chat_template([{'role': 'user', 'content': text}],
                   tokenize=True, add_generation_prompt=True, return_dict=False))
    def fill(unit, target):
        lo, hi = 0, target
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if count(unit * mid) <= target:
                lo = mid
            else:
                hi = mid - 1
        return unit * lo, lo
    long, repetitions = fill('The test token is amber. ', 3840)
    values = {'F-short': {'text': 'Reply with the word ready.'},
              'F-long': {'text': long, 'repetitions': repetitions}}
    for name, target in (('F-context', 3840), ('F-over', 4097)):
        text, _ = fill(' x', target)
        if count(text) != target:
            raise RuntimeError('fixtures: exact template count unavailable; case incomplete')
        values[name] = {'text': text}
    for value in values.values():
        value['input_tokens'] = count(value['text'])
    return values


def freeze_fixtures(values, template_hash):
    fixtures = {}
    for name, value in values.items():
        payload = {'model': 'granite', 'messages': [{'role': 'user', 'content': value['text']}],
                   'n': 1, 'temperature': 0, 'seed': 0,
                   'max_tokens': 1 if name == 'F-over' else 256}
        bodies = {}
        for mode in ('plain', 'stream'):
            body = dict(payload, stream=mode == 'stream')
            if mode == 'stream':
                body['stream_options'] = {'include_usage': True}
            bodies[mode] = encoded(body).decode()
        fixtures[name] = {'input_tokens': value['input_tokens'], 'bodies': bodies,
                          'sha256': {k: hashlib.sha256(v.encode()).hexdigest()
                                     for k, v in bodies.items()}}
        if 'repetitions' in value:
            fixtures[name]['repetitions'] = value['repetitions']
    short = json.loads(fixtures['F-short']['bodies']['plain'])
    invalid = {'malformed': '{', 'missing': encoded({'model': 'granite'}).decode(),
               'empty': encoded(dict(short, messages=[])).decode(),
               'model': encoded(dict(short, model='invalid-test-model')).decode(),
               'zero': encoded(dict(short, max_tokens=0)).decode()}
    return {'image': g.IMAGE, 'model': g.MODEL, 'revision': g.REV,
            'template_sha256': template_hash, 'add_generation_prompt': True,
            'fixtures': fixtures, 'invalid': invalid,
            'order': [['F-short', False], ['F-long', False],
                      ['F-short', True], ['F-long', True]] * 5}


def validate_fixtures(value):
    g.require(value['image'] == g.IMAGE and value['model'] == g.MODEL
              and value['revision'] == g.REV and value['add_generation_prompt'] is True,
              'fixtures: pin/template-setting mismatch; do not execute')
    expected = {'F-short', 'F-long', 'F-context', 'F-over'}
    g.require(set(value['fixtures']) == expected, 'fixtures: wrong fixture set')
    for name, fixture in value['fixtures'].items():
        count = fixture['input_tokens']
        g.require(type(count) is int and 0 < count <= (4097 if name == 'F-over' else 3840),
                  'fixtures: invalid input count')
        if name in ('F-context', 'F-over'):
            g.require(count == (3840 if name == 'F-context' else 4097),
                      'fixtures: exact context count mismatch')
        for mode in ('plain', 'stream'):
            raw = fixture['bodies'][mode].encode()
            g.require(hashlib.sha256(raw).hexdigest() == fixture['sha256'][mode],
                      'fixtures: payload hash mismatch; do not execute')
            body = json.loads(raw)
            g.require(body['model'] == 'granite' and body['n'] == 1 and body['temperature'] == 0
                      and body['seed'] == 0
                      and body['max_tokens'] == (1 if name == 'F-over' else 256)
                      and body['stream'] == (mode == 'stream')
                      and len(body['messages']) == 1 and body['messages'][0]['role'] == 'user',
                      'fixtures: request settings mismatch')


def immutable_write(path, value):
    with path.open('xb') as output:
        output.write(encoded(value))
    path.chmod(0o400)


def synthetic_refusal():
    try:
        g.capacity(7, 47 * g.GIB)
    except RuntimeError:
        return {'status': 'passed', 'input_kind': 'synthetic', 'cpus': 7,
                'available_ram_gib': 47, 'allocations': 0, 'runtime_recovery': 'unexercised'}
    raise RuntimeError('W-resource: synthetic insufficient capacity was admitted')


def usage(data):
    prompt, output = data['prompt_tokens'], data['completion_tokens']
    g.require(type(prompt) is int and type(output) is int and 0 < prompt <= 3840
              and 0 < output <= 256 and data['total_tokens'] == prompt + output
              and prompt + output <= 4096, 'response: invalid token usage')
    return {'input_tokens': prompt, 'output_tokens': output}


def parse_completion(data):
    g.require(data.get('model') == 'granite' and len(data['choices']) == 1,
              'response: expected one pinned-model completion')
    choice = data['choices'][0]
    g.require(choice['index'] == 0 and choice['finish_reason'] in ('stop', 'length')
              and isinstance(choice['message']['content'], str)
              and choice['message']['content'].strip(), 'response: empty or invalid completion')
    return dict(usage(data['usage']), finish_reason=choice['finish_reason'])


def parse_stream(source, check, first_only=False):
    total, identity, text, finished, tokens, first = 0, None, False, None, None, None
    while True:
        check()
        line = source.readline(65537)
        total += len(line)
        g.require(len(line) <= 65536 and total <= 2 * 1024 * 1024,
                  'stream: line/body bound exceeded')
        g.require(line, 'stream: missing terminal completion')
        if line in (b'\n', b'\r\n') or line.startswith(b':'):
            continue
        g.require(line.startswith(b'data: ') and line.endswith(b'\n'), 'stream: malformed event')
        item = line[6:].strip()
        if item == b'[DONE]':
            g.require(text and finished and tokens, 'stream: missing text/finish/usage')
            # One terminal marker; trailing events or another completion are invalid.
            tail = source.read(65537)
            g.require(len(tail) <= 65536 and not tail.strip(), 'stream: data after terminal marker')
            return dict(tokens, finish_reason=finished, first_text_at=first)
        data = json.loads(item)
        g.require(data.get('model') == 'granite' and 'error' not in data,
                  'stream: wrong model or error event')
        if identity is None:
            identity = data['id']
        g.require(data['id'] == identity, 'stream: completion identity changed')
        choices = data['choices']
        if not choices:
            g.require(finished and tokens is None and data.get('usage'),
                      'stream: early or duplicate usage')
            tokens = usage(data['usage'])
            continue
        g.require(len(choices) == 1 and choices[0]['index'] == 0 and not finished,
                  'stream: duplicate/invalid completion')
        choice = choices[0]
        content = choice['delta'].get('content')
        g.require(content is None or isinstance(content, str), 'stream: invalid text chunk')
        if content:
            text = text or bool(content.strip())
            first = first or time.monotonic()
            if first_only:
                return {'first_text_at': first, 'finish_reason': choice.get('finish_reason')}
        if choice.get('finish_reason') is not None:
            g.require(choice['finish_reason'] in ('stop', 'length'),
                      'stream: invalid finish reason')
            finished = choice['finish_reason']


class ResponseFailure(RuntimeError):
    def __init__(self, status, body):
        super().__init__(f'request: unexpected HTTP {status}; inspect private response evidence')
        self.body = body
        self.resource_class = None
        try:
            error = json.loads(body).get('error', {})
            text = (str(error.get('message', '')) + ' ' + str(error.get('type', ''))).lower()
        except (ValueError, AttributeError):
            return
        for pattern, category in ((r'cuda.*out of memory', 'gpu-allocation'),
                (r'outofmemoryerror|cannot allocate memory', 'memory-allocation'),
                (r'no space left on device', 'disk-allocation')):
            if re.search(pattern, text):
                self.resource_class = category
                break


class Client:
    def __init__(self, deadline):
        self.deadline = deadline
        self.connection = http.client.HTTPConnection('127.0.0.1', 8000, timeout=seconds(deadline))
        self.sock = None
        self.response = None
        self.closed = threading.Event()
        self.timer = threading.Timer(seconds(deadline), self.close)
        self.timer.daemon = True
        self.timer.start()

    def check(self):
        g.require(not self.closed.is_set(), 'request: client cancelled')
        timeout = seconds(self.deadline)
        if self.sock and self.sock.fileno() >= 0:
            self.sock.settimeout(timeout)

    def close(self):
        self.timer.cancel()
        self.closed.set()
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.connection.close()
        if self.response:
            self.response.close()

    def open(self, path, raw=None):
        self.connection.connect()
        self.sock = self.connection.sock
        self.check()
        self.connection.request('POST' if raw is not None else 'GET', path, body=raw,
                                headers={'Content-Type': 'application/json', 'Connection': 'close'})
        self.response = self.connection.getresponse()
        return self.response

    def chat(self, raw, stream=False, reject=False, hold=False):
        start = time.monotonic()
        response = self.open('/v1/chat/completions', raw)
        if reject:
            g.require(400 <= response.status < 500, 'request: expected client rejection')
            data = response.read(65537)
            self.check()
            g.require(len(data) <= 65536, 'request: error body exceeds bound')
            return {'status': response.status, 'error_class': 'expected-client-error'}
        if response.status != 200:
            body = response.read(65537)
            self.check()
            g.require(len(body) <= 65536, 'response: error body exceeds bound')
            raise ResponseFailure(response.status, body)
        if stream:
            g.require(response.getheader('Content-Type', '').startswith('text/event-stream'),
                      'stream: wrong media type')
            value = parse_stream(response, self.check, first_only=hold)
        else:
            raw = response.read(2 * 1024 * 1024 + 1)
            self.check()
            g.require(len(raw) <= 2 * 1024 * 1024, 'response: body bound exceeded')
            value = parse_completion(json.loads(raw))
        end = time.monotonic()
        self.check()
        first = value.pop('first_text_at', None)
        return dict(value, status=response.status, latency_s=end - start,
                    ttft_s=first - start if first else None,
                    started_s=start, ended_s=end)


def request_gauges(raw):
    values = {}
    for line in raw.splitlines():
        match = re.fullmatch(r'vllm:num_requests_(running|waiting)(?:\{[^\n]*\})? ([0-9.eE+-]+)', line)
        if match:
            values[match[1]] = values.get(match[1], 0) + float(match[2])
    g.require(set(values) == {'running', 'waiting'} and all(math.isfinite(x) and x >= 0
              for x in values.values()), 'cancellation: outstanding request gauges unavailable')
    return sum(values.values())


def summarize(rows):
    groups = {}
    for row in rows:
        key = row['cache'], row['concurrency'], row['fixture'], row['stream']
        groups.setdefault(key, []).append(row)
    summaries = []
    for (cache, concurrency, fixture, stream), values in sorted(groups.items()):
        latency = sorted(row['latency_s'] for row in values)
        ttft = sorted(row['ttft_s'] for row in values if row['ttft_s'] is not None)
        window = max(v['ended_s'] for v in values) - min(v['started_s'] for v in values)
        count = sum(v['output_tokens'] for v in values)
        summaries.append({'cache': cache, 'concurrency': concurrency, 'fixture': fixture,
                          'stream': stream, 'requests': len(values), 'output_tokens': count,
                          'observation_window_s': window, 'output_tokens_per_s': count / window,
                          'latency_median_s': statistics.median(latency),
                          'latency_p95_s': latency[math.ceil(len(latency) * .95) - 1],
                          'ttft_median_s': statistics.median(ttft) if ttft else None,
                          'ttft_p95_s': ttft[math.ceil(len(ttft) * .95) - 1] if ttft else None})
    return summaries


class Trial:
    def __init__(self, state, gpu, budget, baseline, fixtures, result, deadline):
        self.state, self.gpu, self.budget, self.baseline = state, gpu, budget, baseline
        self.fixtures, self.result, self.deadline = fixtures, result, deadline
        self.name = self.observation = None
        self.held = None
        self.last_sample = 0

    def sample(self, deadline=None, force=False):
        if force or time.monotonic() - self.last_sample >= 1:
            values = g.active(self.name, self.observation, self.gpu, self.budget,
                              self.baseline, min(deadline or self.deadline, self.deadline))
            for key, value in values.items():
                self.result['resource_peaks'][key] = max(
                    value, self.result['resource_peaks'].get(key, 0))
            self.last_sample = time.monotonic()

    def batch(self, jobs, cache, concurrency=1, startup=None, hold=False):
        clients = [Client(request_deadline(self.deadline, startup)) for _ in jobs]
        pool = ThreadPoolExecutor(max_workers=len(jobs))
        futures = []
        try:
            for client, (fixture, stream, reject, raw) in zip(clients, jobs):
                mode = 'stream' if stream else 'plain'
                raw = raw or self.fixtures['fixtures'][fixture]['bodies'][mode].encode()
                futures.append(pool.submit(client.chat, raw, stream, reject, hold))
            pending = set(futures)
            while pending:
                _, pending = wait(pending, timeout=.1)
                for client, future in zip(clients, futures):
                    if not future.done():
                        seconds(client.deadline)
                self.sample(min(c.deadline for c in clients))
                for future in futures:
                    if future.done() and future.exception():
                        raise future.exception()
            values = []
            for job, future in zip(jobs, futures):
                fixture, stream, reject, raw = job
                value = future.result()
                if not reject and not hold:
                    g.require(value['input_tokens'] ==
                              self.fixtures['fixtures'][fixture]['input_tokens'],
                              'fixtures: server template count differs; stop comparison')
                mode = 'stream' if stream else 'plain'
                digest = hashlib.sha256(raw).hexdigest() if raw else \
                    self.fixtures['fixtures'][fixture]['sha256'][mode]
                value.update(cache=cache, fixture=fixture, stream=stream, concurrency=concurrency,
                             request_sha256=digest)
                values.append(value)
            if hold:
                self.held = clients.pop()
            return values
        finally:
            for client in clients:
                client.close()
            pool.shutdown(wait=True, cancel_futures=True)

    def one(self, fixture='F-short', stream=False, cache='warm', reject=False, raw=None,
            startup=None, hold=False):
        return self.batch([(fixture, stream, reject, raw)], cache, startup=startup, hold=hold)[0]

    def gauges(self):
        client = Client(min(self.deadline, time.monotonic() + 5))
        try:
            response = client.open('/metrics')
            g.require(response.status == 200, 'metrics: endpoint unavailable')
            raw = response.read(2 * 1024 * 1024 + 1)
            client.check()
            g.require(len(raw) <= 2 * 1024 * 1024, 'metrics: body bound exceeded')
            return request_gauges(raw.decode())
        finally:
            client.close()

    def cancel(self):
        first = self.one('F-long', True, hold=True)
        try:
            outstanding = self.gauges()
            g.require(first['finish_reason'] is None and outstanding > 0,
                      'W-cancel: generation completed first; cancellation unexercised')
            self.held.close()
            self.held = None
            start = time.monotonic()
            end = request_deadline(self.deadline)
            while self.gauges() != 0:
                seconds(end)
                self.sample(end)
                time.sleep(.1)
            self.result['scenarios']['W-cancel'] = {
                'status': 'passed', 'before_disconnect_outstanding': outstanding,
                'after_disconnect_outstanding': 0, 'slot_release_s': time.monotonic() - start,
                'proof': 'server gauges running+waiting, then successful F-short'}
            self.one()
        finally:
            if self.held:
                self.held.close()
                self.held = None

    def functional(self):
        self.one('F-context')
        self.one('F-over', reject=True)
        self.one()
        self.result['scenarios']['W-context'] = {'status': 'passed', 'valid_input_tokens': 3840,
                                                'rejected_input_tokens': 4097}
        errors = {}
        for name, body in self.fixtures['invalid'].items():
            errors[name] = self.one(reject=True, raw=body.encode())['status']
        self.one()
        self.result['scenarios']['W-invalid'] = {'status': 'passed', 'http_statuses': errors}
        self.cancel()

    def workload(self, cache, functional=False, stop=False, first_only=False):
        def callback(name, observation, start, startup_deadline):
            self.name, self.observation = name, observation
            self.result['private_runtime'].append(observation)
            for key, value in observation.get('GranitePeaks', {}).items():
                self.result['resource_peaks'][key] = max(
                    value, self.result['resource_peaks'].get(key, 0))
            ready = time.monotonic()
            first = self.one(cache=cache, startup=startup_deadline)
            self.result['startups'].append({'cache': cache, 'ready_s': ready - start,
                                            'first_completion_s': time.monotonic() - start,
                                            'first': first})
            self.sample(force=True)
            if not first_only:
                self.one(cache=cache)
                self.one(cache=cache)
                for concurrency in (1, 2):
                    order = self.fixtures['order']
                    for offset in range(0, len(order), concurrency):
                        jobs = [(fixture, stream, False, None)
                                for fixture, stream in order[offset:offset + concurrency]]
                        self.result['requests'].extend(self.batch(jobs, cache, concurrency))
            if functional:
                self.functional()
            if stop:
                first = self.one('F-long', True, hold=True)
                g.require(first['finish_reason'] is None and self.gauges() > 0,
                          'W-stop: generation completed first; active stop unexercised')
            self.sample(force=True)
            self.result['callback_returned_at'] = time.monotonic()
        return callback

    def verify_teardown(self, cache, before):
        logs = self.state / 'logs'
        name = json.loads((logs / 'resources.json').read_text())[0]
        clean = json.loads((logs / 'cleanup.json').read_text())
        g.require(clean['name'] == name and clean['status'] == 'passed',
                  'cleanup: launcher teardown was not verified')
        g.require(clean['elapsed_s'] <= 30, 'W-stop: graceful cleanup exceeded 30 seconds')
        observation = self.observation
        if observation is None:
            observation = json.loads((logs / 'inspect.json').read_text())
            g.require(observation['Name'].lstrip('/') == name,
                      'cleanup: original cgroup telemetry unavailable')
        group = observation['GraniteProof']['cgroup']
        end = time.monotonic() + 30
        root = Path('/sys/fs/cgroup') / group.lstrip('/')
        while root.exists():
            seconds(end)
            time.sleep(.1)
        g.gpu_processes(self.gpu, self.baseline, deadline=end)
        after = g.gpu_state(self.gpu, end)[2]
        g.require(after <= before + 64 * 1024 ** 2,
                  'cleanup: device allocation not released to initial baseline')
        g.require(not g.reachable('127.0.0.1', 8000, end), 'cleanup: endpoint remains')
        return {'cache': cache, 'status': 'passed', 'graceful_stop_and_remove_s': clean['elapsed_s'],
                'old_cgroup_removed': True, 'project_gpu_processes_removed': True,
                'endpoint_closed': True, 'device_before_bytes': before, 'device_after_bytes': after}

    def session(self, cache, functional=False, stop=False, first_only=False):
        seconds(self.deadline)
        g.preflight(self.state, self.gpu, self.baseline, deadline=self.deadline)
        seconds(self.deadline)
        before = g.gpu_state(self.gpu)[2]
        self.name = self.observation = None
        try:
            g.launch(self.state, self.gpu, self.budget, False, self.baseline,
                     workload=self.workload(cache, functional, stop, first_only),
                     session_deadline=self.deadline)
            if stop:
                try:
                    tail = self.held.response.read(2 * 1024 * 1024 + 1)
                    interruption = 'terminal' if b'data: [DONE]' in tail else 'eof'
                except (OSError, http.client.HTTPException):
                    interruption = 'interrupted'
                self.result['scenarios']['W-stop'] = {'status': 'stopped',
                    'active_stream_termination': interruption}
        finally:
            original = sys.exc_info()[1]
            try:
                cleanup_result = self.verify_teardown(cache, before)
                self.result['cleanups'].append(cleanup_result)
                if stop and original is None:
                    self.result['scenarios']['W-stop']['stop_s'] = \
                        cleanup_result['graceful_stop_and_remove_s']
            except BaseException as error:
                self.result['cleanups'].append({'cache': cache,
                    'status': 'unavailable' if isinstance(error, FileNotFoundError) else 'failed',
                    'failure_class': type(error).__name__})
                self.result.setdefault('private_cleanup_errors', []).append(str(error))
                if original is None:
                    raise
            finally:
                if self.held:
                    self.held.close()
                    self.held = None


def materialize(name, state, deadline):
    source = ('import json\nfrom transformers import AutoTokenizer\n'
              + inspect.getsource(fixture_payloads)
              + '\nt=AutoTokenizer.from_pretrained("/model",local_files_only=True,'
                'trust_remote_code=False)\nprint(json.dumps(fixture_payloads(t)))')
    raw = g.run('podman', 'exec', name, 'python3', '-c', source, deadline=deadline)
    g.require(len(raw.encode()) <= 1024 * 1024, 'fixtures: tokenizer output exceeds bound')
    template = hashlib.sha256((state / 'model' / 'chat_template.jinja').read_bytes()).hexdigest()
    return freeze_fixtures(json.loads(raw), template)


def reset_cache(state):
    g.cache_bytes(state / 'cache')
    containers = json.loads(g.run('podman', 'ps', '-a', '--format=json'))
    for container in containers:
        entry = json.loads(g.run('podman', 'inspect', container['Id']))[0]
        g.require(not any(m.get('Source') == str(state / 'cache') for m in entry['Mounts']),
                  'cache: container still references compilation cache; stop and inspect')
    for path in (state / 'cache').iterdir():
        g.require(not path.is_symlink() and not path.is_mount(), 'cache: unsafe nested entry')
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def public_result(result, fixtures):
    fields = ('status', 'commit', 'profile', 'gpu_alias', 'requests', 'resource_peaks',
              'startups', 'cleanups', 'scenarios', 'limits', 'configuration',
              'cold_definition', 'throughput_definition', 'default_profile_sha256',
              'versions', 'failure_class', 'resource_error_class', 'elapsed_s')
    value = {key: result[key] for key in fields if key in result}
    fields = ('image', 'model', 'revision', 'template_sha256', 'add_generation_prompt', 'order')
    value['fixture_manifest'] = {key: fixtures[key] for key in fields if key in fixtures}
    value['fixture_manifest']['fixtures'] = {
        name: {key: item[key] for key in ('input_tokens', 'repetitions', 'sha256') if key in item}
        for name, item in fixtures.get('fixtures', {}).items()}
    value['fixture_manifest']['invalid_sha256'] = {
        name: hashlib.sha256(raw.encode()).hexdigest()
        for name, raw in fixtures.get('invalid', {}).items()}
    value['summary'] = summarize(result['requests'])
    return value


def run_trial(args):
    os.umask(0o077)
    state = args.state.absolute()
    g.require(state == state.resolve() and state.is_dir() and not state.is_symlink()
              and state.stat().st_uid == os.getuid() and state.stat().st_mode & 0o077 == 0,
              'state: existing private owned directory required')
    g.require(not any(p.is_symlink() for p in state.rglob('*')), 'state: symlink entry refused')
    g.ERROR_LOG = state / 'logs' / 'command-error.log'
    with (state / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        g.require(not g.reachable('127.0.0.1', 8000), 'preflight: loopback endpoint occupied')
        result = {'status': 'incomplete', 'commit': g.run('git', 'rev-parse', 'HEAD'),
                  'profile': 'runtime-default', 'gpu_alias': 'GPU-A', 'requests': [],
                  'resource_peaks': {}, 'startups': [], 'cleanups': [], 'private_runtime': [],
                  'scenarios': {name: {'status': 'not-run'} for name in (
                    'W-start', 'W-chat', 'W-context', 'W-invalid',
                    'W-cancel', 'W-stop', 'W-resource')},
                  'limits': {'startup_s': 600, 'request_s': 120, 'stop_s': 30,
                    'trial_s': 3600, 'context_tokens': 4096, 'concurrency': 2,
                    'gpu_bytes': 40*g.GIB,
                    'memory_bytes': 32*g.GIB},
                  'configuration': {'dtype': 'bfloat16', 'kv_cache_dtype': 'auto',
                    'backend': 'FLASH_ATTN', 'flash_attn_version': 2, 'vllm_version': '0.32.0',
                    'gpu_utilization': .80, 'max_model_len': 4096, 'max_num_seqs': 2,
                    'max_num_batched_tokens': 4096, 'cpus': 8, 'pids': 1024,
                    'shared_memory_bytes': 4*g.GIB},
                  'cold_definition': ('empty project compilation cache; '
                                      'warm acquired weights/OS cache'),
                  'throughput_definition': 'class output tokens / first-start to last-end window'}
        result['scenarios']['W-resource'] = synthetic_refusal()
        folder = state / 'results' / ('baseline-' + uuid.uuid4().hex)
        folder.mkdir(mode=0o700, parents=True)
        fixtures, trial = {}, None
        started, deadline = time.monotonic(), time.monotonic() + 3600
        try:
            baseline = g.desktop_baseline(args.desktop_baseline, args.gpu)
            info = g.preflight(state, args.gpu, baseline, deadline=deadline)
            budget = g.Budget(state, info, runtime=True)
            budget.check(True, deadline=deadline)
            for path in (state, budget.store):
                g.require(shutil.disk_usage(path).free >= 80 * g.GIB,
                          'preflight: require 80 GiB free on each affected filesystem')
            seccomp = Path(info['host']['security']['seccompProfilePath'])
            result['default_profile_sha256'] = hashlib.sha256(seccomp.read_bytes()).hexdigest()
            result['versions'] = {'kernel': os.uname().release,
                'podman': info['version']['Version'], 'runtime': info['host']['ociRuntime']['package'],
                'driver': g.run('nvidia-smi', '-i', args.gpu, '--query-gpu=driver_version',
                                '--format=csv,noheader'), 'toolkit': g.run('nvidia-ctk', '--version')}
            def build(name, observation, start, end):
                nonlocal fixtures
                fixtures = materialize(name, state, min(deadline, time.monotonic() + 120))
            g.launch(state, args.gpu, budget, True, baseline, workload=build,
                     session_deadline=deadline)
            validate_fixtures(fixtures)
            fixture_path = state / 'baseline-fixtures.json'
            if fixture_path.exists():
                g.require(fixture_path.stat().st_mode & 0o777 == 0o400
                          and fixture_path.read_bytes() == encoded(fixtures),
                          'fixtures: existing immutable set differs; stop and inspect')
            else:
                immutable_write(fixture_path, fixtures)
            if args.reset_cache:
                reset_cache(state)
            g.require(not list((state / 'cache').iterdir()),
                      'cache: cold start requires empty compilation cache; explicit reset needed')
            trial = Trial(state, args.gpu, budget, baseline, fixtures, result, deadline)
            trial.session('cold')
            trial.session('warm', functional=True, stop=True)
            trial.session('restart', first_only=True)
            result['scenarios']['W-start'] = {'status': 'passed'}
            result['scenarios']['W-chat'] = {
                'status': 'passed', 'timed_requests': len(result['requests'])}
            result['scenarios']['W-stop']['status'] = 'passed'
            result['status'] = 'passed'
        except BaseException as error:
            result['status'] = 'failed'
            result['failure_class'] = type(error).__name__
            # Exception text can contain paths, identities or untrusted server data; private only.
            (folder / 'failure.txt').write_text(str(error))
            if isinstance(error, ResponseFailure):
                (folder / 'response-error.bin').write_bytes(error.body)
                result['resource_error_class'] = error.resource_class
            resource_error = (isinstance(error, ResponseFailure) and error.resource_class is not None
                or isinstance(error, OSError)
                and error.errno in (errno.ENOMEM, errno.ENOSPC)
                or any(word in str(error) for word in ('cgroup OOM', 'server stopped/OOM',
                                                       'GPU memory exceeds', 'disk:')))
            if (trial and resource_error and result['cleanups']
                    and result['cleanups'][-1]['status'] == 'passed'):
                resource = result['scenarios']['W-resource']
                resource['runtime_recovery'] = 'attempted-once'
                try:
                    trial.session('recovery', first_only=True)
                    resource['runtime_recovery'] = 'passed-diagnostic; trial remains failed'
                except BaseException as recovery_error:
                    resource['runtime_recovery'] = 'failed-or-prerequisites-unrestored'
                    (folder / 'recovery-failure.txt').write_text(str(recovery_error))
            raise
        finally:
            peaks = state / 'logs' / 'runtime-peaks.json'
            if peaks.exists():
                for key, value in json.loads(peaks.read_text()).items():
                    result['resource_peaks'][key] = max(value, result['resource_peaks'].get(key, 0))
            result['elapsed_s'] = time.monotonic() - started
            (folder / 'private.json').write_bytes(encoded(result))
            (folder / 'sanitized.json').write_bytes(encoded(public_result(result, fixtures)))
            print(f'Baseline {result["status"]}; private results: {folder}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--gpu', required=True)
    parser.add_argument('--desktop-baseline', type=Path)
    parser.add_argument('--reset-cache', action='store_true',
                        help='discard only project compilation-cache contents before cold start')
    args = parser.parse_args()
    run_trial(args)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('baseline: trial failed; inspect retained private results before another run',
              file=sys.stderr)
        sys.exit(1)
