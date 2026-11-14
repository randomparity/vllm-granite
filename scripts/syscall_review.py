#!/usr/bin/env python3
"""Offline, scalar-only interpretation of retained complete diagnostic captures."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

try:
    from scripts import tracing
except ModuleNotFoundError:
    import tracing


SCALARS = {'ioctl': (1,), 'mmap': (2, 3), 'mmap2': (2, 3), 'mprotect': (2,),
           'pkey_mprotect': (2,), 'futex': (1,), 'futex_time64': (1,), 'socket': (0, 1, 2)}
CLONE_FLAGS = dict(zip(('CLONE_VM CLONE_FS CLONE_FILES CLONE_SIGHAND CLONE_PIDFD '
    'CLONE_PTRACE CLONE_VFORK CLONE_PARENT CLONE_THREAD CLONE_NEWNS CLONE_SYSVSEM '
    'CLONE_SETTLS CLONE_PARENT_SETTID CLONE_CHILD_CLEARTID CLONE_DETACHED '
    'CLONE_UNTRACED CLONE_CHILD_SETTID CLONE_NEWCGROUP CLONE_NEWUTS CLONE_NEWIPC '
    'CLONE_NEWUSER CLONE_NEWPID CLONE_NEWNET CLONE_IO').split(),
    (1 << bit for bit in range(8, 32))))
CLONE_FLAGS.update({'SIGCHLD': 17, '0': 0, 'CLONE_CLEAR_SIGHAND': 1 << 32,
                    'CLONE_INTO_CGROUP': 1 << 33})


def require(ok, message):
    tracing.require(ok, 'inventory: ' + message)


def scalars(name, args):
    result = {}
    if name in ('clone', 'clone3'):
        flags = re.search(r'(?:^|[,{] *)flags=([A-Z0-9_|]+)\s*(?=[,}]|$)', args)
        require(flags is not None, 'unsupported creation flags; inspect private input')
        tokens = flags[1].split('|')
        require(all(token in CLONE_FLAGS for token in tokens), 'unknown creation flag')
        value = 0
        for token in tokens:
            value |= CLONE_FLAGS[token]
        # clone3 flags are decoded pointed data, not a seccomp-filterable scalar argument.
        result['decoded_flags' if name == 'clone3' else 'arg0_flags'] = hex(value)
    for index in SCALARS.get(name, ()):
        fields = args.split(',')
        require(len(fields) > index and re.fullmatch(r'\s*(?:0x[0-9a-f]+|\d+)\s*',
                                                    fields[index]),
                'unsupported scalar form; inspect private input')
        value = int(fields[index].strip(), 0)
        require(0 <= value <= 0xffffffff, 'scalar outside reviewed 32-bit range')
        result['arg' + str(index)] = hex(value)
    return result


def inventory(path, root, names):
    pending, calls, pre_exec, bootstrap = {}, {}, {}, 0
    active = False
    with path.open() as source:
        for line in source:
            match = re.fullmatch(r'(\d+)\s+\d+\.\d+\s+(.+)\n', line)
            require(match is not None, 'malformed record')
            pid, body = int(match[1]), match[2]
            if body.startswith('--- SIG'):
                continue
            if body.startswith('+++'):
                if pid in pending:
                    name, args, started = pending.pop(pid)
                    record(calls if started else pre_exec, name, args, 'unfinished-at-exit')
                continue
            started = active
            resumed = re.match(r'<\.\.\. (\w+) resumed>(.*)', body)
            if resumed:
                if pid not in pending:
                    require(pid == root, 'unmatched completion')
                    bootstrap += 1
                    continue
                name, prefix, started = pending.pop(pid)
                require(name == resumed[1], 'mismatched completion')
                body = name + '(' + prefix + resumed[2]
            call = re.fullmatch(r'(\w+)\((.*)', body)
            require(call is not None and call[1] in names, 'unsupported syscall name')
            name, rest = call[1], call[2]
            if rest.endswith('<unfinished ...>'):
                require(pid not in pending, 'overlapping calls')
                pending[pid] = (name, rest.removesuffix('<unfinished ...>'), started)
                continue
            done = re.fullmatch(r'(.*)\) += (.*)', rest)
            require(done is not None, 'missing completion')
            returned = re.match(r'(-?0x[0-9a-f]+|-?\d+|\?)(?:\s+([A-Z][A-Z0-9_]+))?', done[2])
            require(returned is not None, 'unsupported return')
            if returned[2]:
                outcome = returned[2]
            elif returned[1] == '?':
                outcome = 'no-return'
            else:
                outcome = 'error' if int(returned[1], 0) < 0 else 'success'
            if pid == root and name in ('execve', 'execveat') and outcome == 'success':
                active, started = True, True
            record(calls if started else pre_exec, name, done[1], outcome)
    require(not pending, 'unresolved calls')
    return {'syscalls': dict(sorted(calls.items())),
            'pre_exec_syscalls': dict(sorted(pre_exec.items())), 'bootstrap_resumed': bootstrap}


def record(calls, name, args, outcome):
    entry = calls.setdefault(name, {'calls': 0, 'outcomes': Counter(), 'scalars': {}})
    entry['calls'] += 1
    entry['outcomes'][outcome] += 1
    for field, value in scalars(name, args).items():
        entry['scalars'].setdefault(field, Counter())[value] += 1


def review(folder, profile_path, evidence):
    raw_profile = profile_path.read_bytes()
    profile_hash = hashlib.sha256(raw_profile).hexdigest()
    require(profile_hash == evidence['default_profile_sha256'], 'baseline hash mismatch')
    profile = json.loads(raw_profile)
    names = {name for rule in profile['syscalls'] for name in rule['names']}
    require(all(re.fullmatch('[a-z_][a-z0-9_]{0,40}', name) for name in names),
            'unsupported baseline name')
    sessions, observed = {}, set()
    require(evidence['status'] == 'passed' and evidence['traces'], 'successful evidence required')
    for expected in evidence['traces']:
        cache = expected['cache']
        require(cache in ('cold', 'warm', 'restart') and cache not in sessions,
                'invalid/duplicate session')
        capture = folder / 'traces' / cache
        armed = json.loads((capture / 'armed.json').read_text())
        path = capture / 'raw.strace'
        checked = tracing.validate(path, armed['root'], armed['pidns'])
        summary = json.loads((capture / 'summary.json').read_text())
        require(all(checked[k] == expected[k] == summary[k] for k in checked),
                'capture hash/completeness mismatch')
        data = inventory(path, armed['root'], names | {'io_uring_setup'})
        require(sum(entry['calls'] for phase in ('syscalls', 'pre_exec_syscalls')
                    for entry in data[phase].values()) ==
                checked['syscall_records'], 'inventory count mismatch')
        sessions[cache] = dict(data, **checked)
        observed.update(data['syscalls'])
    rules = []
    for index, rule in enumerate(profile['syscalls']):
        selected = {k: rule[k] for k in ('names', 'action', 'args', 'includes', 'excludes',
                                        'errnoRet') if k in rule}
        rules.append(dict(selected, index=index, observed_names=sorted(set(rule['names']) & observed)))
    baseline = {k: profile[k] for k in ('defaultAction', 'defaultErrnoRet', 'archMap') if k in profile}
    baseline['rules'] = rules
    return {'default_profile_sha256': profile_hash, 'baseline': baseline, 'sessions': sessions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True, help='private retained baseline directory')
    parser.add_argument('--profile', type=Path, required=True, help='exact baseline profile file')
    parser.add_argument('--evidence', type=Path, required=True, help='reviewed sanitized trial JSON')
    args = parser.parse_args()
    try:
        evidence = json.loads(args.evidence.read_text())
        print(json.dumps(review(args.run, args.profile, evidence), sort_keys=True, separators=(',', ':')))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print('inventory: failed; inspect retained inputs privately; no report emitted', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
