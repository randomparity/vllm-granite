import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import syscall_review as s


class InventoryCases(unittest.TestCase):
    def inventory(self, extra='', profile=None, mutate=None, before=''):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            profile = profile or {'defaultAction': 'SCMP_ACT_ERRNO', 'syscalls': [
                {'names': ['execve', 'ioctl', 'futex', 'mmap', 'clone', 'clone3', 'exit_group'],
                 'action': 'SCMP_ACT_ALLOW', 'args': [], 'includes': {}, 'excludes': {}}]}
            p = root / 'profile.json'
            p.write_text(json.dumps(profile))
            trace = (before + '10 1.000 execve(0x11111111, 0x22222222, 0x33333333) = 0\n' + extra +
                     '10 1.900 exit_group(0) = ?\n10 2.000 +++ exited with 0 +++\n')
            if extra.endswith('<unfinished ...>\n'):
                trace = trace.replace('10 1.900 exit_group(0) = ?\n', '')
            capture = root / 'traces' / 'cold'
            capture.mkdir(parents=True)
            raw = capture / 'raw.strace'
            raw.write_text(trace)
            (capture / 'armed.json').write_text(json.dumps({'root': 10, 'pidns': False}))
            summary = s.tracing.validate(raw, 10)
            (capture / 'summary.json').write_text(json.dumps(summary))
            evidence = {'default_profile_sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                        'status': 'passed', 'traces': [dict(summary, cache='cold')]}
            if mutate:
                mutate(capture, evidence)
            return s.review(root, p, evidence)

    def test_join_failed_resumed_and_scalar_privacy(self):
        value = self.inventory(
            '10 1.100 ioctl(0x123, 0x5401, 0x12345678 <unfinished ...>\n'
            '10 1.200 <... ioctl resumed>) = -1 ENOTTY (private diagnostic)\n'
            '10 1.300 futex(0x12345678, 0x80, 0, 0, 0, 0) = 0\n'
            '10 1.400 mmap(0, 0x1000, 0x3, 0x22, 0xffffffff, 0) = 0x12345678\n')
        calls = value['sessions']['cold']['syscalls']
        self.assertEqual(calls['ioctl']['outcomes'], {'ENOTTY': 1})
        self.assertEqual(calls['ioctl']['scalars'], {'arg1': {'0x5401': 1}})
        self.assertEqual(calls['mmap']['scalars'], {'arg2': {'0x3': 1}, 'arg3': {'0x22': 1}})
        self.assertEqual(sum(x['calls'] for x in calls.values()), 5)
        self.assertNotIn('private', json.dumps(value))
        self.assertNotIn('12345678', json.dumps(value))

    def test_unlisted_io_uring_probe_is_inventory_not_implied_allow(self):
        value = self.inventory('10 1.100 io_uring_setup(0x8, 0x12345678) = -1 '
                               'ENOSYS (not implemented)\n')
        self.assertEqual(value['sessions']['cold']['syscalls']['io_uring_setup']['outcomes'],
                         {'ENOSYS': 1})
        self.assertFalse(any('io_uring_setup' in rule['names']
                             for rule in value['baseline']['rules']))

    def test_runtime_pre_exec_is_separate_from_application(self):
        value = self.inventory(before='10 0.100 ioctl(0x1, 0x5401, 0x2) = 0\n')
        session = value['sessions']['cold']
        self.assertNotIn('ioctl', session['syscalls'])
        self.assertEqual(session['pre_exec_syscalls']['ioctl']['calls'], 1)
        self.assertEqual(session['syscall_records'], 3)

    def test_baseline_conditions_and_constraint_survive(self):
        p = {'defaultAction': 'SCMP_ACT_ERRNO', 'defaultErrnoRet': 38, 'syscalls': [
            {'names': ['execve', 'exit_group'], 'action': 'SCMP_ACT_ALLOW'},
            {'names': ['ioctl'], 'action': 'SCMP_ACT_ERRNO', 'errnoRet': 1,
             'args': [{'index': 1, 'value': 1, 'op': 'SCMP_CMP_EQ'}],
             'includes': {'caps': ['CAP_SYS_ADMIN']}, 'excludes': {'arches': ['arm']}}]}
        rule = self.inventory(profile=p)['baseline']['rules'][1]
        self.assertEqual(rule['action'], 'SCMP_ACT_ERRNO')
        self.assertEqual(rule['includes'], {'caps': ['CAP_SYS_ADMIN']})
        self.assertEqual(rule['args'][0]['value'], 1)
        self.assertEqual(rule['observed_names'], [])

    def test_unsupported_scalar_and_unknown_call_fail_closed(self):
        for call in ('ioctl(0x1, "private", 0x2) = 0',
                     'ioctl(0x1, 0x123456789, 0x2) = 0', 'private_syscall() = 0'):
            with self.subTest(call=call), self.assertRaises(RuntimeError):
                self.inventory('10 1.100 ' + call + '\n')

    def test_changed_hash_summary_duplicate_and_empty_evidence_rejected(self):
        def summary(capture, evidence):
            data = json.loads((capture / 'summary.json').read_text())
            data['tasks'] += 1
            (capture / 'summary.json').write_text(json.dumps(data))

        mutations = [lambda c, e: e.update(default_profile_sha256='0' * 64),
                     lambda c, e: e['traces'][0].update(sha256='0' * 64), summary,
                     lambda c, e: e['traces'].append(e['traces'][0]),
                     lambda c, e: e.update(traces=[])]
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaises(RuntimeError):
                self.inventory(mutate=mutate)

    def test_unfinished_on_exit_is_not_counted_as_success(self):
        calls = self.inventory('10 1.100 futex(0x1, 0x80 <unfinished ...>\n')
        self.assertEqual(calls['sessions']['cold']['syscalls']['futex']['outcomes'],
                         {'unfinished-at-exit': 1})

    def test_creation_abandoned_before_argument_separator(self):
        value = self.inventory('10 1.100 clone(child_stack=NULL, '
                               'flags=CLONE_VM|CLONE_PIDFD|CLONE_VFORK <unfinished ...>\n')
        clone = value['sessions']['cold']['syscalls']['clone']
        self.assertEqual(clone['outcomes'], {'unfinished-at-exit': 1})
        self.assertEqual(clone['scalars'], {'arg0_flags': {'0x5100': 1}})

    def test_decoded_clone3_flags_only_and_cannot_inspect_pointer(self):
        calls = self.inventory('10 1.100 clone3({flags=CLONE_VM|CLONE_THREAD, '
                               'stack=0x12345678}, 88) = -1 ENOSYS (not implemented)\n')
        clone = calls['sessions']['cold']['syscalls']['clone3']
        self.assertEqual(clone['scalars'], {'decoded_flags': {'0x10100': 1}})
        self.assertNotIn('stack', json.dumps(clone))


if __name__ == '__main__':
    unittest.main()
