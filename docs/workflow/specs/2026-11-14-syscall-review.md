# Offline syscall requirements review — issue #7

## Problem

Successful #6 captures need interpretation against the exact default profile before #8
can choose policy. Observation alone cannot establish safe removal or sufficient confinement.

## Scope

One Cast unit adds a bounded offline inventory entry consuming retained cold/warm/restart
capture metadata and the baseline profile, reusing tracing.validate for completeness.
It hashes inputs before analysis, joins unfinished/resumed records, counts successes/errors,
and emits only syscall names and explicitly selected scalar argument values for clone,
ioctl, mmap/mprotect and futex. Raw pointed data, paths, task identities and addresses
remain private. A sanitized report records profile hash and per-session capture hashes,
counts, syscall inventory and baseline-rule review with conditional rules preserved.
Human interpretation documents required, unexplained and removal-candidate classes,
architecture/error-path gaps and session-level workload attribution.
Custom policy/fail-closed selection belongs to #8, controls to #9, comparison to #10,
fresh-state installation/maintenance to #11. New captures require separate authorization.
No new dependencies, enforcement, architecture decisions or profile mutation.

Failure model: trusted retained diagnostic files on the documented x86_64 host; reject
hash/completeness mismatches, malformed or unresolved records, and unsupported scalar forms
rather than publishing raw text. Counts are observations, not policy authorization.
Unobserved runtime resource recovery, alternate architectures and hostile tracer evasion
are disclosed limits; enforcement validation belongs to #8/#9.

## Success

Reproduction over all retained successful #6 sessions produces deterministic sanitized
inventory tied to exact hashes and session workload IDs. Baseline rules retain action,
conditions and argument constraints for review; no trace absence alone approves removal.
Review addresses clone variants, GPU ioctl exposure, memory flags, futex operations and
device initialization; seccomp cannot inspect pointed data or authorize paths (#7 Expected).

## Validation

- focused-test: inventory joins interleaved/resumed/failed records, counts exits correctly,
  rejects inconsistent inputs, and allowlists scalar publication without paths/pointers.
  tests/test_syscall_review.py; expected red missing module/entry; green command:
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_syscall_review.py -v
- task-test-not-applicable: requirements interpretation is a human evidence judgment;
  no executable consumer or prose assertion establishes syscall necessity or safe removal.
- Run offline against retained complete cold/warm/restart traces and exact profile,
  inspect every generated field, then repository unit suite and git diff --check.
