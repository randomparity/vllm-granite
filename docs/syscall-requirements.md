# Syscall requirements against the baseline

This issue #7 review consumes the successful [#6 trial](evidence/tracing-second-attempt.md),
not a new capture. The [deterministic inventory](evidence/syscall-inventory.json) retains
all three raw hashes/counts and the exact baseline SHA256
`2598b3b98e6970f37f917e210202fa8976aefcd99abf8955803a6e35bba17eb4`.
Its source trial JSON SHA256 is
`5ee5d3361ed5a0dddcc9fcbc54567e0d22ab68e1f9af95fdae65102f46cead99`;
image/model, fixture hashes, versions and resource settings remain those of that trial.
No custom policy or new enforcement evidence is produced here.

## Reproduce offline

Set `RETAINED_RUN` to the private successful baseline directory and `BASELINE_PROFILE`
to the exact installed profile file, then run from the repository root:

```bash
umask 077
PYTHONDONTWRITEBYTECODE=1 python3 scripts/syscall_review.py \
  --run "$RETAINED_RUN" --profile "$BASELINE_PROFILE" \
  --evidence docs/evidence/tracing-second-attempt.json > "$PRIVATE_INVENTORY"
cmp "$PRIVATE_INVENTORY" docs/evidence/syscall-inventory.json
```

Set `PRIVATE_INVENTORY` to a new private output file first. Failure exits nonzero,
prints a generic diagnostic and emits no JSON; inspect inputs locally. Do not publish
raw traces or diagnostics. The script uses Python stdlib and existing completeness
validation; it neither runs the workload nor changes the profile. Unknown syscall names
outside the baseline plus the reviewed `io_uring_setup` probe fail for local review.
Selected scalar forms are deliberately bounded; unsupported formats fail rather than
leaking text. Public output contains no pointers, paths, task IDs or ioctl payloads.

## Boundary and scenario attribution

The retained hook actually captured OCI initialization before root successful exec.
Earlier capture documentation understated this. `pre_exec_syscalls` separates calls
**starting** before that exec; `syscalls` includes the successful exec and subsequent
call starts. Pending calls retain their start phase across resumed/terminal records.
This is a temporal boundary across traced tasks, not proof of each descendant's role;
it does not identify a syscall's library, request or file/device target. Runtime setup
calls must not become serving allowances merely because the whole capture contains them.

| Session | Pre-exec records | Application-phase records | Distinct application names | Scenario attribution |
| --- | ---: | ---: | ---: | --- |
| cold | 9,214 | 2,597,012 | 113 | W-start cold compilation, W-chat concurrency 1/2 streaming/nonstreaming |
| warm | 9,276 | 1,985,039 | 106 | W-start warm, W-chat, W-context, W-invalid, W-cancel, W-stop active stream |
| restart | 9,202 | 1,479,928 | 105 | W-start after stop and readiness/first completion, W-stop cleanup |

The union contains 114 application-phase names. W-resource was a synthetic zero-allocation
refusal outside serving and has no traced runtime-recovery claim. Request clocks are
monotonic while trace clocks are epoch based: no precise request-to-syscall correlation
is asserted. Capture totals remain 2,606,226 / 1,994,315 / 1,489,130, including bootstrap.
`outcomes` distinguishes success, errno, restart pseudo-errors, no-return and calls still
unfinished at terminal task exit; neither a failed probe nor an unfinished call proves
an allowance is necessary. `symlink` returned only ENOENT and remains an unexplained
error-path probe; `exit`/`exit_group` no-return records represent task termination, not
failed permission checks. Scalar histograms are marginal counts, not argument tuples.

## Required, unexplained and removal candidates

Here **required** means retain for the next functional candidate unless a narrower
alternative is justified and tested; it is not a mathematically minimal allowlist.
Every baseline rule is preserved with its original zero-based index, action, args,
includes/excludes and observed-name intersection in the JSON. Intersection is only
name overlap; it does not mean that rule's conditions matched or caused the result.

| Baseline rules | Review and disposition for #8 |
| --- | --- |
| 0 | Retain explicit EPERM denials, including userfaultfd, kexec and newer futex interfaces. Lack of observations does not justify weakening them. |
| 1 | Required candidate: observed successful application I/O, memory, synchronization, signals, process lifecycle and networking. The large multi-ABI allow bundle is not justified as a whole: all other names are unexplained until assessed against error recovery and the threat model. Do not copy runtime-only mount/pivot_root/sethostname/seccomp allowances. |
| 2–6 | personality value restrictions are unobserved/unexplained; preserve the constraints if retained. Absence supplies no license for an unconditional personality allowance. |
| 7–8, 11–12 | Foreign architecture branches are removal candidates for the explicitly x86_64-only target, based on target scope, not trace absence. #8 must implement ABI handling; this review approves no cross-architecture policy. |
| 9 | arch_prctl is observed in the x86_64 application phase; retain that architecture restriction. |
| 10 | modify_ldt is unobserved and unexplained; do not infer x86/x32 compatibility from x86_64 success. |
| 13, 15, 17, 19, 21, 23, 25, 27, 29, 37, 39 | Capability-gated ALLOW branches are removal candidates because production drops all capabilities and privileged administration is outside the threat model. Resolve overlapping names/actions and runtime preprocessing in #8; do not turn inactive branches into unconditional allows. |
| 14, 16, 18, 20, 22, 24, 26, 28, 30, 36, 38 | Retain matching EPERM restrictions for missing capabilities, including module, ptrace-related, BPF, clock and perf operations. |
| 31–35 | Preserve socket domain/protocol restrictions, including AF_VSOCK and audit-netlink handling. Observed socket names alone do not justify deleting deny branches or flattening capability conditions. |

`io_uring_setup` is absent from all 40 explicit rules and returned ENOSYS once per
application session, consistent with the baseline default ENOSYS (38). Preserve fallback
semantics until independently verified; it is not an allow candidate. Errors can also
come from capabilities, namespaces, SELinux, drivers or the application, so these traces
do not isolate seccomp as the cause of any denial. The other 330 baseline names absent
from the application union remain unproven, including ABI aliases and default-denied rules.

## Scalar and device review

- **clone/clone3:** all eight decoded clone calls/session precede root exec. Post-exec
  clone3 succeeded 172/118/117 times; thread flags `0x3d0f00` occurred 130/118/117 times.
  Cold compilation also used 42 `0x100004100` combinations. The JSON labels clone3 flags
  `decoded_flags`: they reside in pointed-to `struct clone_args`, so classic seccomp
  cannot constrain them as argument zero. Legacy clone flags are a scalar on x86_64,
  but alternate ABI ordering and clone/fork fallback remain untested.
- **ioctl/device initialization:** post-exec ioctl totals are 43,267/32,211/32,173,
  with 1,969/1,657/1,615 successes; many terminal probes returned ENOTTY. Command numbers
  such as `0xc020462a` and `0xc030462b` are inventoried, but not mapped to device identities
  or payload semantics. GPU initialization and later requests share session traces.
  An observed command list is insufficient to authorize all GPU-driver operations;
  ioctl payloads and fd/device provenance are outside seccomp's pointer inspection.
- **mmap/mprotect:** observed protections include NONE/R/RW/RX and RWX (`0x7`).
  RWX mmap occurred 3/2/2 times and RWX mprotect eight times/session. Removing executable
  mappings would break observed behavior unless JIT/loader alternatives are proved.
  Keep protection and mapping-flag histograms as evidence; they do not identify which
  mapping is safe, and their marginal values are not tested allowed combinations.
- **futex:** operations include private WAIT/WAKE (`0x80`/`0x81`) and WAIT_BITSET with
  private/clock bits (`0x89`, `0x109`, `0x189`). EAGAIN, ETIMEDOUT and kernel restart
  pseudo-errors are expected observations to preserve through cancellation/shutdown.
  futex_time64, futex_waitv and the newer family remain unobserved; retain baseline denies
  and resolve ABI fallback explicitly rather than inventing universal coverage.

File/device paths cannot be authorized by classic seccomp: it sees syscall numbers,
architecture and scalar arguments, not pointed-to path strings, clone3 flags or ioctl
payloads. Keep mount, capability, namespace, SELinux and device controls alongside it.
See [kernel seccomp documentation](https://docs.kernel.org/userspace-api/seccomp_filter.html).

Runtime resource failure/recovery, rare signal/error paths, allocator pressure, alternate
kernels/drivers/libcs/ABIs and changed compilation paths are not covered by this one run.
Absence alone never establishes safe removal. Custom policy/runtime acceptance belongs
to #8, causal enforcement controls to #9, paired regression/performance to #10 and fresh
installation/maintenance to #11. Recapture requires separate operator approval.
