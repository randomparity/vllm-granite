# 0003: Rootless diagnostic prestart observer

## Status
Accepted by operator decision on 2026-11-13, for issue #6 diagnostic capture only.

## Context
The workload requires application startup through shutdown and worker-thread coverage.
The existing post-readiness observer cannot establish startup coverage. Production
must retain rootless operation, enforcing SELinux and its default seccomp profile.

## Decision
Use installed host strace through a private, per-invocation OCI prestart hook.
Before the runtime executes the application, acknowledge that its init PID has
the expected TracerPid. Follow forks and threads; retain the observer until traced
tasks exit. Reject observer errors, incomplete process lifecycle or truncated output.
Keep raw captures private and bounded; publish only explicit summary fields and hashes.
The operator approved this design and its second no-GPU proof separately from GPU capture.

## Consequences
No tracing privilege enters the container and no global hook or policy is installed.
ptrace changes scheduling and latency; these runs are diagnostic, not overhead comparisons.
The runtime's bootstrap before prestart is outside application syscall coverage.
Rootless attach depends on host policy and must fail closed when that policy changes.
Application descendants that deliberately evade observation invalidate the experiment;
this is a trusted workload evidence tool, not an adversarial containment mechanism.

## Considered & rejected
- **Late attach:** verified: at base d9738fcc87c0f8c24de003baf7b53968c3427f67,
  scripts/granite.py starts the container before observe(); earlier application calls are missed.
- **Privileged cgroup observer:** judgment: broader observer authority and setup than
  the successful rootless prestart proof requires for this single-container experiment.
- **In-container tracer:** judgment: changes the pinned image or container permissions;
  the host observer keeps diagnostic tooling outside production.
- **No tracing:** judgment: cannot meet issue #6's syscall-evidence criterion.

The authorized pinned-image no-GPU proof on Fedora 44/x86_64, Podman 5.8.7,
crun 1.28 and strace 7.2 acknowledged prearming, then recorded application exec,
one thread, one forked child and three exits; cleanup and observer exit passed.
Only 136,317 private bytes were produced in 0.873 seconds. This is not GPU proof.
