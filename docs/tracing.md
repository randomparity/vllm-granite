# Diagnostic syscall capture

Use this only for an explicitly approved diagnostic workload. Production serving needs
no tracer, hook or extra permission. Capture retains rootless Podman, enforcing SELinux,
the existing project domain, default seccomp and the pinned image/model/resources.

Prerequisites are the [confined launch](launch.md) and [baseline](baseline.md) setup,
plus host `strace` (tested 7.2). Upstream stable is [7.3](https://strace.io/files/7.3/)
as checked on2026-11-13; this change uses the already installed7.2 and upgrades no host tool. Check `strace --version` before scheduling the run.
On Fedora, an administrator can provision the distribution's `strace` package if absent;
installation is a separate operator action. No additional package enters the image.
The tested host uses Fedora44/x86_64, Podman5.8.7 and crun1.28. A different version or
host policy needs revalidation; inability to attach is a failure, not permission to relax it.

From the repository root, after separate approval for one traced baseline:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/baseline.py \
  --state "$GRANITE_STATE" --gpu "$GRANITE_GPU" --reset-cache --trace
```

Add `--desktop-baseline "$GRANITE_DESKTOP_BASELINE"` only for the already explicitly
approved exact private desktop-process record. `--reset-cache` removes only disposable
project compilation contents after the existing exclusive lock/reference checks. Weights,
OS cache and existing evidence remain. Do not run another project/cache/GPU writer.

The existing trial performs tokenizer preparation, then cold, warm and restart serving
sessions. Each serving session gets its own private prestart hook and host observer;
tokenizer preparation is not a serving capture. The hook acknowledges `TracerPid` before
the runtime executes the application. strace follows process/thread creation and remains
until the final traced task exits, including launch cleanup. Its PID-namespace translation
keeps child return values and host task prefixes in one identity domain. No global hook,
new device, container capability or tracing privilege is installed. See [ADR0003](adr/0003-rootless-prestart-observer.md).

Bounds remain600s startup,120s/request,30s graceful stop and3600s/trial. ptrace can slow
the workload substantially; diagnostic timing does not establish the paired overhead
comparison. A deadline, observer failure, unavailable record, malformed/truncated output,
missing application exec/child/exit/namespace translation or exhausted trace budget fails
the trial. Traced mode suppresses automatic resource-error recovery. Affected cases need
a newly authorized rerun; there is no automatic capture retry.

Each raw trace and observer stderr has a hard256MiB file-size bound: three raw files total
at most768MiB, plus at most768MiB separately bounded observer diagnostics. Normal attachment
notices are small. The existing80GiB free-space check still applies. Files are private under
mode0700 `results/baseline-<random>/traces/{cold,warm,restart}/`, with umask077. Raw syscalls,
arguments, process IDs, identities, paths and errors must stay local. Keep the failed run
for inspection; do not copy raw traces into GitHub even after attempted text redaction.

The trial's `sanitized.json` includes explicit allowlisted trace status, cache IDs, task and
syscall-record counts, byte counts, raw SHA256 and tracer version, alongside baseline
versions, workload/fixture IDs and tested artifact hashes. Review its entire contents before
publishing. A complete capture is evidence for this workload, not an inferred syscall
allowlist. Interpretation belongs to #7 and policy decisions to #8.

Coverage begins at the application exec boundary. Earlier runtime bootstrap calls and
deliberate hostile observer evasion are outside this diagnostic evidence claim. ptrace is
synchronous rather than sampled; no perf/BPF loss counter applies. Attachment gaps,
detaches, unavailable records, write errors or premature observer exit invalidate coverage.
If the operator kills the launcher forcibly, reconcile only its exact project container,
network and retained observer identities using private artifacts before another run.

## Verification status

Two separately approved no-GPU probes established rootless attachment and prestart arming
with application exec, one thread, a forked child and final exits. The second used136,317
private bytes in0.873s and removed its exact container; the observer exited naturally.
Those preliminary probes did not validate the final collector/parser or GPU workload.
Ordinary tests exercise the final observer against a harmless host child and private
PID-namespace fixtures. A separately approved complete traced GPU trial is still required.

Upstream references: [OCI hook configuration](https://github.com/containers/common/blob/main/pkg/hooks/docs/oci-hooks.5.md),
[strace7.2 manual](https://github.com/strace/strace/blob/v7.2/doc/strace.1.in),
[PID translation](https://github.com/strace/strace/blob/v7.2/src/pidns.c).
