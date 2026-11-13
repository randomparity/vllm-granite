# Pinned acquisition and confined GPU launch (#4)

## Authority and ownership

Frozen #4 `WORK:SCOPE` q4-862fd2c0 governs C1–C6/exclusions and fixed M denominator 250.
The operator approved the prior 840-line design exception and the specific 38 MiB desktop baseline.
The installed policy/cached-image probes establish only host access. ADR0001's grant is unchanged.
`scripts/granite.py` owns acquisition/check/serving; `tests/test_granite.py` owns boundary tests;
`docs/launch.md` owns commands, linked by README. No callers/migration; the plan stays private.
CLI: `python3 scripts/granite.py {acquire,check,serve} --state PATH [--gpu GPU-UUID]`.
Optional `--desktop-baseline PATH` consumes the operator-supplied private JSON only; no auto-capture.
Use private state and an exact GPU UUID for check/serve; no index/all/fallback/passthrough.
Acquire is online and credential-free. Offline check uses an HTTP/device/resource diagnostic,
without loading weights. Serve repeats check then supervises foreground with SIGINT/SIGTERM cleanup.
Publish loopback port 8000, alias `granite`; a busy port fails.

## Global Constraints

Target Fedora 44/x86_64 (OCI linux/amd64), rootless Podman 5.8.7, crun 1.28,
NVIDIA Container Toolkit 1.19.1, container-selinux 2.251.0 and Python 3 as installed.
These are the observed supported deployment, not a promise for older versions or other targets.
Use Python standard library and installed platform commands only; add no dependency or tool floor.
Consume the exact image digest, model/tokenizer revision, BF16/FA2 settings and resource bounds
in `docs/compatibility.md`; keep SELinux enforcing and the runtime default seccomp profile.
No rootful, privileged, label-disable, permissive, boolean or automatic policy-grant fallback.

## Acquisition and state (C1, C4)

Record rootless-store allocated bytes before pulling; verify immutable linux/amd64 digest/platform.
HTTPS metadata must match the model revision and 13 allowed config/tokenizer/safetensors files;
reject missing/duplicate names, invalid sizes/hashes and totals above 20 GiB. Exclude repository code.
Download to partial files; verify size and LFS SHA-256/Git-blob SHA-1 before atomic replacement.
Persist validated metadata and reverify offline. Identity checks do not establish publisher trust.
State is UID-owned/mode-0700/non-symlink/exclusively locked; reject existing symlinks. Only readonly
model and persistent cache enter the container. Raw evidence stays private; publish sanitized results.
Require 80 GiB free per affected filesystem before acquisition; monitor store growth/pull scratch
32 GiB, model 20, cache 8, logs/state 4, total 64. Charge shared-store growth conservatively;
no concurrent shared-store mutation or pruning. Disk scans detect/stop breaches, with overshoot;
they are not quotas. Preserve cache for #5. Retain at most 64 KiB command-refusal stderr privately,
identify its path in actionable errors, and preserve the primary failure when cleanup also fails.

## Runtime boundaries (C2–C4)

Require 48 GiB MemAvailable, eight CPUs, delegated cpu/memory/pids v2 and enforcing SELinux/seccomp;
the A6000 needs free memory covering its 0.80 allocation plus 6 GiB. Use one UUID CDI device,
private IPC/PID/cgroup, RAM 32 GiB/no swap, aggregate CPU-time quota 8, PIDs 1024, shm 4 GiB,
readonly root, dropped capabilities and NNP. Ignore image volumes; explicitly bound writable
/dev/shm to 4 GiB, /tmp to 1 GiB and /run to 64 MiB. Model/cache use private SELinux relabeling.
Default GPU occupancy is zero other compute processes. The sole approved exception is the recorded
terminal baseline, matched by UUID/PID/starttime/executable and capped at 38 MiB. Before launch and
during supervision, require each process to be that exact baseline or in the owned container cgroup;
identity reuse, memory growth and additional workloads fail. Never stop unrelated processes.
Literal offline/cache settings disable proxy inheritance and plugin discovery; no broad host mounts.
Create an internal IPv4 bridge without DNS, aliases or gateway; publish only loopback. Prove
loopback HTTP, refused non-loopback publication and failed external/mapped-host/host-address TCP
against a host sentinel, corroborated by network structure; samples do not exhaust packet paths.
Inspect post-CDI OCI linux.devices, enumerate those device nodes inside the container, compare
host/OCI device numbers, selected UUID/minor and DRM sysfs PCI identity. Observe MCS/type, NNP,
capabilities, seccomp and actual cgroup limits externally; repeat for the serving process.
Use vLLM 0.32.0/local tokenizer/BF16/FLASH_ATTN FA2/TP1, context and batch 4096, sequences 2,
GPU utilization 0.80/output 256; no parser, remote code, plugin or CPU offload. #5 owns client
concurrency/request deadlines. Start the 600-second readiness clock immediately before Podman start;
observations count against it. Monitor GPU 40 GiB/session 3600 seconds; exit/OOM/breach fails.
Stop allows 30 seconds; forced kill fails. Before mutation, verify unique per-run names absent;
put creation inside cleanup scope. Reconcile uncertain creation by exact-name cleanup, independently
attempt stop/removal/verification, and never remove preexisting resources. Catchable interrupts
clean owned state; failed cleanup requires operator inspection before retry. Retain cache/logs.

## Failure model

- Actors/deployments: trusted local operator on the observed Fedora host; hostile local API input
  and compromised workers; registry/model services supply artifacts.
- Assets/invariants: host files/credentials, other GPUs/workloads, pinned identities, confinement,
  availability, bounded private evidence and truthful outcomes.
- Accepted classes: kernel/driver bugs and trusted same-UID/operator/admin compromise are outside
  prevention; disk/GPU scan overshoot is detected/stopped, not hard-capped; SIGKILL/power loss needs
  manual inspection; concurrent shared-store mutation violates the stated prerequisite.
- Covered elsewhere: #3/#5 inference/fit, requests, cold/warm/output cases; #6/#7 syscall inventory;
  #8/#9 custom seccomp/enforcement; #10 paired regression; #11 full operations guide; #2/operator pins.

## Threat model

- Added boundaries: HTTPS→state, CLI path/UUID→argv, artifacts→container, container→devices/files/
  network/cgroups; container HTTP responses→host readiness client. Widened boundary: only ADR0001's approved, installed process-device grant.
- Trust: operator/kernel/runtime/driver/TLS roots/upstream publishers are trusted; workers/API input
  are untrusted. Local clients share the API; hostile same-UID naming races are not promised against.
- Controls: exact allowlist/hash/size, argv without shell, private locked state, readonly model,
  UUID/OCI/PCI checks, minimal mounts/caps, enforcing domain/default seccomp, internal network,
  fixed-loopback direct HTTP status with no redirects, one-second total exchange and 64 KiB header cap, hard cgroups and monitored disk/GPU. Failure details remain private.
- Out of scope: local-user authentication, driver exploit prevention, signature trust roots,
  remote exposure and orchestration, as excluded by #1/operator.

## AI surface and validation

AI-SPEC: the local operator starts the pinned server; synthetic chat produces bounded text using
only acquired model/tokenizer/template. No tools/retrieval/remote code/downloads; failure stops,
without fallback. #2's budgets apply; #4 succeeds on launch/access evidence, not inference quality.
Severity-5 privacy/tool/egress modes use mount/offline/network checks; severity-4 identity/backend/
budget modes use pin/CLI/cgroup checks. #3's F-short/F-context/F-invalid/W-resource/W-stop cover
happy, ambiguous/invalid, expensive/recovery cases; #5 materializes them. Unsafe/stale/conflicting
inputs introduce no new tool/retrieval or refusal requirement; no self-grading model is used.
Focused boundary tests and live acquire/check cover #4; commit guarded source before live proof,
record the tested HEAD, and keep #5's unrun fit/workload evidence distinct.
