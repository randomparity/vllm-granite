import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import baseline as b
from scripts import granite as g


def event(**values):
    return ('data: ' + json.dumps(values) + '\n\n').encode()


class ProtocolCases(unittest.TestCase):
    def stream(self):
        return (event(id='one', model='granite', choices=[{
            'index': 0, 'delta': {'content': 'ready'}, 'finish_reason': None}])
            + event(id='one', model='granite', choices=[{
                'index': 0, 'delta': {}, 'finish_reason': 'stop'}])
            + event(id='one', model='granite', choices=[], usage={
                'prompt_tokens': 20, 'completion_tokens': 2, 'total_tokens': 22})
            + b'data: [DONE]\n\n')

    def test_stream_contract(self):
        result = b.parse_stream(io.BytesIO(self.stream()), lambda: None)
        self.assertEqual(result['output_tokens'], 2)
        self.assertEqual(result['input_tokens'], 20)
        self.assertEqual(result['finish_reason'], 'stop')
        for data in (self.stream().replace(b'data: [DONE]\n\n', b''),
                     self.stream().replace(b'"index": 0', b'"index": 1'),
                     self.stream().replace(b'"content": "ready"', b'"content": ""'),
                     self.stream() + self.stream(), b'data: {\n\n',
                     event(error={'message': 'private'}), b'x' * 65537):
            with self.subTest(data=data[:30]), self.assertRaises((RuntimeError, ValueError)):
                b.parse_stream(io.BytesIO(data), lambda: None)

    def test_duplicate_finish_or_usage(self):
        duplicate = event(id='one', model='granite', choices=[{
            'index': 0, 'delta': {}, 'finish_reason': 'stop'}])
        data = self.stream().replace(b'data: [DONE]', duplicate + b'data: [DONE]')
        with self.assertRaises(RuntimeError):
            b.parse_stream(io.BytesIO(data), lambda: None)

    def test_json_contract(self):
        data = {'model': 'granite', 'choices': [{'index': 0, 'message': {'content': 'ready'},
                 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 20,
                 'completion_tokens': 2, 'total_tokens': 22}}
        self.assertEqual(b.parse_completion(data)['output_tokens'], 2)
        for key, value in (('choices', []), ('usage', {'completion_tokens': 257}),
                           ('model', 'wrong')):
            bad = copy.deepcopy(data)
            bad[key] = value
            with self.assertRaises((RuntimeError, KeyError)):
                b.parse_completion(bad)

    def test_absolute_deadline(self):
        with patch.object(b.time, 'monotonic', return_value=600):
            with self.assertRaises(RuntimeError):
                b.seconds(600)
            self.assertEqual(b.request_deadline(1000, 601), 601)


class FixtureCases(unittest.TestCase):
    def test_fixture_freeze_and_tampering(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return list(range(len(messages[0]['content'].split()) + 17))
        value = b.fixture_payloads(Tokenizer())
        self.assertEqual(value['F-context']['input_tokens'], 3840)
        self.assertEqual(value['F-over']['input_tokens'], 4097)
        self.assertLessEqual(value['F-long']['input_tokens'], 3840)
        frozen = b.freeze_fixtures(value, 'a' * 64)
        b.validate_fixtures(frozen)
        for mutate in (lambda v: v.update(revision='wrong'),
                       lambda v: v['fixtures']['F-context'].update(input_tokens=3839),
                       lambda v: v['fixtures']['F-short']['bodies'].update(plain='{}')):
            wrong = copy.deepcopy(frozen)
            mutate(wrong)
            with self.assertRaises(RuntimeError):
                b.validate_fixtures(wrong)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixtures.json'
            b.immutable_write(path, frozen)
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            with self.assertRaises(FileExistsError):
                b.immutable_write(path, frozen)

    def test_synthetic_refusal_no_allocation(self):
        with patch.object(g, 'launch') as launch:
            result = b.synthetic_refusal()
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['input_kind'], 'synthetic')
            launch.assert_not_called()


class MetricCases(unittest.TestCase):
    def test_separate_classes_nearest_rank_and_throughput(self):
        rows = [{'cache': 'cold', 'fixture': 'F-short', 'stream': True, 'concurrency': 1,
                 'latency_s': n, 'ttft_s': n / 10, 'output_tokens': 2,
                 'started_s': 0, 'ended_s': n} for n in range(1, 6)]
        rows += [dict(rows[0], cache='warm', latency_s=100, ended_s=100)]
        groups = b.summarize(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['latency_p95_s'], 5)
        self.assertEqual(groups[0]['latency_median_s'], 3)
        self.assertEqual(groups[0]['output_tokens_per_s'], 2)
        self.assertEqual(groups[1]['latency_p95_s'], 100)

    def test_request_gauges_require_both(self):
        self.assertEqual(b.request_gauges('vllm:num_requests_running{model="granite"} 1\n'
                                          'vllm:num_requests_waiting{model="granite"} 0\n'), 1)
        with self.assertRaises(RuntimeError):
            b.request_gauges('vllm:num_requests_running 0\n')

class LifecycleCases(unittest.TestCase):
    def test_callback_failure_cleans_owned_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'logs').mkdir()
            with patch.object(g, 'exists', return_value=False), \
                 patch.object(g, 'run', return_value=''), \
                 patch.object(g, 'observe', return_value={'GraniteProof': {'cgroup': '/owned'}}), \
                 patch.object(g, 'active', return_value={}), \
                 patch.object(g, 'readiness', return_value=True), \
                 patch.object(g, 'network_check'), patch.object(g, 'reachable', return_value=False), \
                 patch.object(g, 'cleanup') as cleanup:
                def workload(*args):
                    raise RuntimeError('workload failure')
                with self.assertRaisesRegex(RuntimeError, 'workload failure'):
                    g.launch(state, 'GPU-test', None, True, workload=workload)
                cleanup.assert_called_once()

class TransportCases(unittest.TestCase):
    def test_actual_http_connection_stream_and_rejection(self):
        import socket
        import threading
        body = ProtocolCases().stream()
        for status, payload, streaming, rejection in (
                (200, body, True, False), (400, b'{"error":"synthetic"}', False, True)):
            client_socket, server_socket = socket.socketpair()
            def serve():
                with server_socket:
                    request = b''
                    while b'\r\n\r\n' not in request:
                        request += server_socket.recv(4096)
                    headers = (f'HTTP/1.1 {status} Result\r\nContent-Length: {len(payload)}\r\n'
                               'Content-Type: text/event-stream\r\nConnection: close\r\n\r\n').encode()
                    server_socket.sendall(headers + payload)
            server = threading.Thread(target=serve)
            server.start()
            client = b.Client(b.time.monotonic() + 2)
            def connect(connection):
                connection.sock = client_socket
            try:
                with patch.object(b.http.client.HTTPConnection, 'connect', connect):
                    result = client.chat(b'{}', streaming, rejection)
                self.assertEqual(result['status'], status)
                if streaming:
                    self.assertEqual(result['output_tokens'], 2)
                    self.assertGreaterEqual(result['ttft_s'], 0)
            finally:
                client.close()
                server.join(timeout=2)
            self.assertFalse(server.is_alive())

    def test_supervisor_closes_stalled_request_at_absolute_deadline(self):
        import threading
        closed = threading.Event()
        class Stalled(b.Client):
            def chat(self, *args):
                closed.wait(timeout=2)
                raise RuntimeError('request closed')
            def close(self):
                closed.set()
        trial = b.Trial(None, None, None, None,
                        {'fixtures': {'F-short': {'bodies': {'plain': '{}'}}}}, {},
                        b.time.monotonic() + .05)
        with patch.object(b, 'Client', Stalled), patch.object(trial, 'sample'):
            with self.assertRaises(RuntimeError):
                trial.batch([('F-short', False, False, None)], 'cold')
        self.assertTrue(closed.is_set())

class EvidenceCases(unittest.TestCase):
    def test_public_result_excludes_runtime_and_payloads(self):
        private = 'sensitive-machine-prompt'
        result = {'private_runtime': [private], 'callback_returned_at': 1, 'requests': [],
                  'status': 'failed', 'command_error': private}
        fixtures = {'fixtures': {'F-short': {'bodies': {'plain': private},
                    'input_tokens': 20, 'raw_text': private}},
                    'invalid': {'case': private}, 'tokenizer_error': private}
        value = b.public_result(result, fixtures)
        self.assertNotIn(private, json.dumps(value))
        self.assertEqual(value['status'], 'failed')

    def test_cache_reset_requires_no_referencing_container(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            cache = state / 'cache'
            cache.mkdir()
            content = cache / 'keep'
            content.write_text('compilation')
            def command(*args):
                if args[1] == 'ps':
                    return '[{"Id":"owned"}]'
                return json.dumps([{'Mounts': [{'Source': str(cache)}]}])
            with patch.object(g, 'cache_bytes'), patch.object(g, 'run', side_effect=command):
                with self.assertRaisesRegex(RuntimeError, 'still references'):
                    b.reset_cache(state)
            self.assertEqual(content.read_text(), 'compilation')

class TokenizerReturnCases(unittest.TestCase):
    def test_explicit_token_ids_with_transformers_mapping_default(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                ids = list(range(len(messages[0]['content'].split()) + 17))
                if kwargs.get('return_dict') is False:
                    return ids
                return {'input_ids': ids, 'attention_mask': [1] * len(ids)}
        values = b.fixture_payloads(Tokenizer())
        self.assertEqual(values['F-context']['input_tokens'], 3840)
        self.assertEqual(values['F-over']['input_tokens'], 4097)

class SlowDripCases(unittest.TestCase):
    def test_absolute_deadline_closes_dripping_headers_and_metrics_body(self):
        import socket
        import threading
        for stage in ('headers', 'body'):
            left, right = socket.socketpair()
            completed = threading.Event()
            stop = threading.Event()
            headers = b'HTTP/1.1 200 OK\r\nContent-Length: 64\r\nConnection: close\r\n\r\n'
            def serve():
                with right:
                    try:
                        request = b''
                        while b'\r\n\r\n' not in request:
                            request += right.recv(4096)
                        if stage == 'body':
                            right.sendall(headers)
                        data = headers if stage == 'headers' else b'x' * 64
                        for byte in data:
                            if stop.wait(.01):
                                return
                            right.sendall(bytes([byte]))
                        completed.set()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            server = threading.Thread(target=serve)
            server.start()
            client = b.Client(b.time.monotonic() + .08)
            def connect(connection):
                connection.sock = left
            try:
                with patch.object(b.http.client.HTTPConnection, 'connect', connect):
                    with self.assertRaises((RuntimeError, OSError, b.http.client.HTTPException)):
                        response = client.open('/metrics')
                        if stage == 'body':
                            response.read(2 * 1024 * 1024 + 1)
                        client.check()
                self.assertFalse(completed.is_set(), 'read waited for complete dripped response')
            finally:
                stop.set()
                client.close()
                server.join(timeout=2)
            self.assertFalse(server.is_alive())

class AllocationResponseCases(unittest.TestCase):
    def test_http_allocation_error_is_classified_and_retained_privately(self):
        from types import SimpleNamespace
        for message, expected in (('CUDA out of memory', 'gpu-allocation'),
                                  ('No space left on device', 'disk-allocation'),
                                  ('unrelated server error', None)):
            body = json.dumps({'error': {'message': message, 'type': 'InternalServerError'}}).encode()
            response = SimpleNamespace(status=500, read=lambda size: body)
            client = b.Client(b.time.monotonic() + 2)
            try:
                with patch.object(client, 'open', return_value=response):
                    with self.assertRaises(RuntimeError) as caught:
                        client.chat(b'{}')
                self.assertEqual(getattr(caught.exception, 'resource_class', None), expected)
                self.assertEqual(getattr(caught.exception, 'body', None), body)
                self.assertNotIn(message, str(caught.exception))
            finally:
                client.close()

class FailedCleanupCases(unittest.TestCase):
    def test_failed_session_verifies_teardown_and_preserves_original_error(self):
        for leaked in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                (state / 'logs').mkdir()
                (state / 'logs' / 'resources.json').write_text('["owned", "net"]')
                (state / 'logs' / 'cleanup.json').write_text(json.dumps({
                    'name': 'owned', 'status': 'passed', 'elapsed_s': .01}))
                (state / 'logs' / 'inspect.json').write_text(json.dumps({
                    'Name': 'owned', 'GraniteProof': {'cgroup': '/granite-test-absent-cgroup'}}))
                result = {'cleanups': []}
                trial = b.Trial(state, 'GPU-test', None, None, {}, result,
                                b.time.monotonic() + 2)
                fault = RuntimeError('request failed')
                gpu_fault = RuntimeError('compute allocation remains') if leaked else None
                with patch.object(g, 'preflight'), \
                     patch.object(g, 'gpu_state', return_value=[0, 0, 321]), \
                     patch.object(g, 'launch', side_effect=fault), \
                     patch.object(g, 'gpu_processes', side_effect=gpu_fault) as processes, \
                     patch.object(g, 'reachable', return_value=False):
                    with self.assertRaisesRegex(RuntimeError, 'request failed') as caught:
                        trial.session('cold')
                self.assertIs(caught.exception, fault)
                self.assertEqual(result['cleanups'][-1]['status'], 'failed' if leaked else 'passed')
                processes.assert_called_once()
