# Pinned acquisition and confined GPU launch (#4)

## Authority and status

Frozen #4 `WORK:SCOPE` q4-862fd2c0 governs C1–C6/exclusions and fixed M denominator 250.
Installed policy/cached-image probes prove only host access. The private plan records branch/checks.

## Outcome and ownership

`scripts/granite.py` owns acquisition/check/serving; `tests/test_granite.py` owns boundary tests.
`docs/launch.md` owns commands, linked by README. No migration; ADR0001/policy grant is unchanged.

`python3 scripts/granite.py {acquire,check,serve} --state PATH [--gpu GPU-UUID]`
requires private state and, for check/serve, an exact GPU UUID; no index/all/fallback/passthrough.
Online credential-free acquire is separate from offline HTTP/device/resource check (no weights
loaded). Serve repeats check then supervises foreground; SIGINT/SIGTERM clean owned resources.
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

Record rootless-store allocated bytes before pulling the immutable linux/amd64 child digest;
verify local digest/platform. HTTPS model metadata must match the revision and 13 allowed root
config/tokenizer/safetensors names. Reject duplicate/missing names, malformed size/hash and totals
over 20 GiB. Repository Python code is excluded.
Download to owned partial files with size and LFS SHA-256/Git-blob SHA-1 checks before atomic
replacement. Persist validated metadata and reverify offline. No credentials enter serving;
digest checks establish identity, not publisher authenticity.

State is UID-owned, mode 0700, non-symlink, exclusively locked. Only readonly model and persistent
cache enter the container; reject existing state symlinks. Raw evidence stays private; published
identities are sanitized. Cache persists for #5 cold/warm cases.
Monitor allocated disk usage: image/store growth 32 GiB, model 20 GiB,
cache 8 GiB, logs/state 4 GiB, total 64 GiB. Pull scratch belongs to the image bucket.
Require 80 GiB free on affected store/state filesystems before acquisition. Charge shared-store
growth conservatively; operator must not concurrently mutate the shared store during a run.
Disk scans detect/stop breaches with possible overshoot; they are not quotas. No shared-store pruning.

## Runtime boundaries (C2, C3, C4)

Require 48 GiB MemAvailable, eight CPUs, delegated cpu/memory/pids v2, enforcing SELinux/seccomp,
and the selected idle A6000 with free memory covering its 0.80 allocation plus 6 GiB.
Use one UUID CDI device, private IPC/PID/cgroup, 32 GiB RAM/no swap, 8 CPU quota/affinity,
1024 PIDs, 4 GiB shared memory, readonly root, dropped capabilities and NNP.
Ignore image-declared volumes; disable automatic writable root tmpfs and declare writable
/dev/shm (4 GiB), /tmp (1 GiB) and /run (64 MiB). Cache and model use private SELinux relabeling, no broad mounts.
Offline/cache environment is literal; disable HTTP proxy inheritance and vLLM plugin discovery.

Create one owned internal bridge network with DNS disabled, no host aliases, and no gateway.
Publish only loopback; do not use default pasta egress. A diagnostic proves loopback HTTP,
refused non-loopback publication, and failed external/mapped-host/host-address TCP attempts
against a controlled listening host sentinel. Structural route/network checks complement these
samples; they do not claim to exhaust every packet path. Verify selected UUID inside the
container, enumerate injected device nodes, and compare GPU node device numbers to the host.
Observe process label/MCS, NNP, capabilities, seccomp and actual cgroup limit files externally;
container-only assertions do not establish confinement. Recheck the serving process likewise.

Use vLLM v0.32.0, local model/tokenizer, BF16, FLASH_ATTN FA2, tensor parallel 1,
context 4096, batched tokens 4096, sequences 2, GPU utilization 0.80 and max output 256.
No reasoning parser, remote code, repository plugin or CPU offload. Client concurrency and
120-second request deadlines remain #5's bounded workload responsibility, not an API tenancy claim.
Readiness is bounded to 600 seconds, GPU observation to 40 GiB, session to 3600 seconds.
Exit/OOM/breach stops the run; stop allows 30 seconds and forced kill is failure. Retain cache
and bounded logs. Verify container/network removal and endpoint closure; cleanup failure blocks retry.

## Failure model

- Actors and deployments: trusted local operator on the observed Fedora host; hostile local API
  input and compromised inference workers; public registry/model services are supply-chain inputs.
- Invariants and assets at stake: host credentials/files, other GPUs/workloads, acquired identities,
  confinement, host availability, bounded private logs and truthful pass/fail evidence.
- Accepted failure classes: GPU-driver/kernel bugs and trusted same-UID/operator/admin compromise
  are outside prevention claims; scan-latency disk/GPU overshoot is detected, stopped and reported,
  not a hard quota; SIGKILL/power failure can leave owned state needing explicit inspection;
  shared-store concurrent mutation violates the stated single-operator acquisition prerequisite.
- Covered elsewhere: executable inference/fit, 120-second requests, cold/warm cases and model-output
  quality by #5/#3; syscall inventory #6/#7; custom seccomp/enforcement #8/#9; paired regression #10;
  complete maintenance/installation guide #11; pin/envelope changes #2/operator. None is claimed passed.

## Threat model

- Added boundaries: HTTPS metadata/files into private state; operator UUID/path into subprocess
  arguments; acquired artifacts into a container; container into GPU/filesystem/network/cgroups.
  Widened boundary: only ADR 0001's approved process-domain device grant, already installed.
- Actors and trust: operator, host kernel/runtime/driver, TLS roots and upstream artifact publishers
  are trusted. Inference workers and local API inputs are untrusted; local clients share an API.
- Controls: exact metadata allowlist/hash/size, argv without shell, owned private state/lock,
  read-only verified model, one CDI UUID, minimal mounts/caps, enforcing domain/default seccomp,
  internal no-gateway network, loopback ingress, hard cgroup limits and monitored disk/GPU bounds.
  Failure details stay private; errors identify the failed operation and required inspection.
- Out of scope: authenticating local users, GPU-driver exploit prevention, signature trust roots,
  remote exposure and orchestration. Those are excluded by #1/operator, not hidden guarantees.

## AI surface and validation

AI-SPEC: the local experiment operator explicitly starts the pinned server; synthetic chat inputs
produce bounded chat text using only acquired model/tokenizer/template data. Tools, retrieval,
remote code and external downloads are disallowed. Failure stops the run; no model/device fallback.
Budgets are the unchanged #2 envelope; successful launch/access and honest readiness status are
#4's signal. A ready server is not an inference/evaluation pass.
Severity-5 privacy/tool/egress modes are covered by offline/mount/network diagnostics; severity-4
wrong identity/backend/budget modes by identity, CLI and cgroup checks. #3's F-short, F-context,
F-invalid and W-resource/W-stop specify happy, ambiguous/invalid, expensive and recovery cases;
#5 materializes them. Unsafe instructions, stale/conflicting data and model-output judgments
introduce no new tools/retrieval or normative refusal requirement here; no self-grading model.
Focused tests exercise malformed metadata, wrong digest/size, partial writes, unsafe paths,
insufficient capacity, offline argv and boundary failures. Live `acquire` then `check` proves
candidate access on the target; final artifacts distinguish that from #5's unrun full inference.
