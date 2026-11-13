# Threat model and validation workload

Defined for [#3](https://github.com/randomparity/vllm-granite/issues/3) and epic #1.
**Status: intended access and test expectations; no containment or inference proof yet.**
Use the [compatibility record](compatibility.md) for immutable candidates, every numeric
resource/deadline bound and the baseline/custom comparison protocol. This document consumes
those decisions; it does not replace them. Target Fedora 44/x86_64, one RTX A6000,
Granite 4.2 8B, rootless Podman, loopback publication and enforcing SELinux.

## Attacker, assets and trust boundaries

Assume hostile local API input and arbitrary code execution in the inference process or one
of its workers. The attacker can use the container's actual credentials, mounts, devices,
network and allowed syscalls. Treat prompts and model output as untrusted data. Local API
clients are not mutually isolated: loopback access alone supplies neither authentication nor
protection from another local user. Use synthetic, non-sensitive requests for this experiment.

Protect host files/credentials, other workloads and GPUs, kernel/driver integrity, host
availability, pinned model/image integrity, request privacy and trustworthy measurement results.
Acquisition is a separate trusted operator action; serving consumes pre-acquired artifacts.
A trusted image/model source remains a supply-chain assumption, not something seccomp proves.
Use plain chat with the pinned tokenizer/template; no remote model code, repository plugins,
tool execution or custom reasoning parser. Reasoning tokens, if produced, count in the budget.

| Surface | Intended permitted access and residual exposure |
| --- | --- |
| GPU | Only the selected A6000 plus the supporting NVIDIA control/UVM interfaces needed for it; #4 must enumerate actual injected devices and prove identity. No blanket device access or additional GPU. Device files are an attack surface even with only one GPU selected. |
| Files | Read acquired model/tokenizer and image runtime files; write only private project compilation cache, temporary state and bounded results/logs. Keep model mounts read-only. No host home, credentials, container-engine socket or unrelated host tree; no broad parent-directory mounts. Cache/log writers can corrupt their own writable data. |
| Processes / IPC | Container workers and private shared memory within #2 CPU/PID/RAM bounds. No host PID/IPC namespace, tracing privileges or privileged serving. No-new-privileges and minimal capabilities are launch responsibilities in #4. |
| Network | Local client-to-API traffic and necessary container-private worker communication only. Serving needs no acquisition credentials, DNS lookups or outbound downloads. External clients, host services and outbound connections are outside permitted use. Loopback publication does not establish an egress restriction; #4 must report actual reachability and any unmet access boundary before validation. |
| Evidence | Raw prompts, outputs, traces and logs stay private and bounded; publish fixture IDs, counts, sanitized outcomes and hashes. A compromised process can falsify its own logs, so runtime observations must be corroborated from outside that process where feasible. |

These are requirements to check, not assertions about a running container. Rootless operation
limits privilege but still exposes resources granted to the host user/container. Keep SELinux
enforcing and start the baseline with the runtime default seccomp profile. Any needed exception
is an explicit decision for #4; do not silently use rootful, privileged or unconfined serving.

[Linux documents seccomp as syscall-surface reduction, not a complete sandbox](https://docs.kernel.org/userspace-api/seccomp_filter.html).
Its filters inspect syscall numbers and argument values without dereferencing pointers.
Consequently, allowing GPU `ioctl` operations leaves driver code reachable and does not validate
the pointed-to request structures. Rootless namespaces, SELinux and a custom seccomp profile do
not establish GPU-driver exploit prevention. Driver flaws, device sharing and untested paths
remain residual risks. Host administrator compromise and hostile kernel/driver behavior are
outside this experiment's prevention claims. [Podman's run reference](https://docs.podman.io/en/stable/markdown/podman-run.1.html)
describes the separate device, publication, namespace, security and resource controls; a seccomp
allowlist is not proof of filesystem or network policy. #8/#9 own enforcement evidence.

## Fixture definitions and bounds

#5 materializes these fixtures and freezes exact UTF-8 payloads, image/model/tokenizer pins,
template-aware token counts and request settings before execution. #10 reuses identical bytes
in both comparison arms. The intended API is local chat completions; verify actual candidate
support in #4/#5. Use one user message, one completion, temperature 0, seed 0 and output cap
256 unless a case below changes a field. Set `model` to the configured pinned served alias.
No tools, files, secrets, user documents or external URLs enter the prompts.

- **F-short:** user text `Reply with the word ready.`; require nonempty text, not an exact
  model wording match. **F-long:** repeat `The test token is amber. ` to fill the largest
  template-aware input at or below 3840 tokens; freeze repetition count and bytes. Tokenize
  the whole rendered chat template, not the user message alone. Total input plus allowed
  output stays within 4096. Do not assume the model must use its entire output cap.
- **F-context:** freeze one exact 3840-token rendered input using the pinned tokenizer and
  deterministic synthetic padding; output cap 256. Freeze a second payload whose rendered
  input plus requested output exceeds 4096 by one token. If exact construction or candidate
  admission semantics cannot be established, report the boundary case incomplete, not passed.
- **F-invalid:** send one each: malformed JSON bytes `{`, missing `messages`, empty `messages`,
  unknown model alias `invalid-test-model`, and `max_tokens: 0`. Send each separately; fix
  exact bodies in #5 without changing these semantics. Rejections are expected, not crashes.

Inherit #2's concurrency 1 normally / 2 maximum, at most 2 sequences and 4096 batched tokens;
never use an unbounded client queue. Every request has its 120 s deadline, startup 600 s,
graceful stop 30 s and session 60 min. Apply all GPU/RAM/CPU/PID/shared-memory/disk prerequisites
and ceilings from #2 before starting. Check delegation and isolation first. Fewer available
CPUs, restricted RAM, slow disk or GPU occupancy can make the run infeasible or incomplete;
do not raise limits, switch devices, drop host caches or weaken security to make it pass.

## Required scenarios

Run functional cases once per arm/trial unless #2 specifies measured repetitions. Keep malformed,
cancellation and failure cases out of timed performance samples. Time and report each class
separately. For timed traffic use F-short and F-long, each in streaming and nonstreaming mode:
at each concurrency, issue five of each of these four classes (20 requests total), respecting
#2's two warmups before timing. Alternate classes deterministically and freeze the order.
Concurrency 2 means two active client requests, not two completions per request.

| ID | Bounded action | Expected outcome and case cleanup |
| --- | --- | --- |
| W-start | Launch with a fresh project compilation cache; after readiness send F-short. Stop, retain that cache and restart for the warm case. Acquired weights and OS file cache remain warm as #2 defines. | Ready and first nonempty completion within startup deadline; record both times and cache class separately. Stop old workers before restart; never share a live cache writer across arms. |
| W-chat | F-short and F-long in nonstreaming and streaming modes, at concurrency 1 then 2. | Successful chat response with one completion; stream has consumable text chunks and terminal completion, without protocol error or duplicate completion. Observe nonempty text, finish reason, output token count and deadlines; do not score literary correctness or exact token equality. Close each response/stream. |
| W-context | F-context valid boundary, then over-limit payload, one request at a time. | Valid boundary succeeds within envelope; over-limit request returns a client error before generation, not silent truncation or allocation failure. Record template counts and actual admission behavior. Close responses and send F-short to prove continued service. |
| W-invalid | Each F-invalid case, sequentially. | Bounded client-error response, no process exit or prompt echo in public results. Exact error wording is not a contract. Close responses; a subsequent F-short succeeds. |
| W-cancel | Send streaming F-long; close client connection after first text chunk. If it completes first, report cancellation unexercised. | Worker request ends and releases its active slot within request deadline; a following F-short succeeds. Capture abort/completion status and outstanding request count where observable. Never mistake client disconnect alone for server cancellation proof. |
| W-stop | With one streaming F-long active, request graceful container stop; then restart with the same pinned model/cache and send F-short. | Stop within 30 s, stream terminates cleanly or with recorded interruption, old container workers disappear and its device allocation is released; restart succeeds within startup bound. If graceful stop fails, stop the trial, terminate only project container workers and record failure. |
| W-resource | Exercise a preflight refusal using a synthetic insufficient-capacity observation against #2's required minima; do not allocate to manufacture exhaustion. For a naturally occurring bounded container/GPU allocation or disk-space error, run the recovery path below. | Preflight refuses launch with operation/resource/remedy and no allocations. Label synthetic input explicitly. Actual resource errors stop the trial and preserve the failure; after cleanup and restored prerequisites, at most one restart plus F-short proves recovery. If no actual error occurs, report runtime resource-error recovery unexercised; synthetic refusal does not prove allocator recovery. |

For runtime resource errors, stop admission, close active clients and stop only the project
container. Record exit status, resource class and bounded outside-process observations; a
container OOM is a failed trial, never a successful stress test. Restore prerequisites without
removing unrelated data; rerun the preflight before the single recovery attempt. A second error,
missing telemetry or unmet prerequisite ends the session as failed/incomplete. No host OOM,
GPU fault injection, stress loop, oversized allocations, disk filling or host-wide cache purge.
An unexercised required case prevents a complete passing workload result; #5/#10 must retain
that limitation rather than claim comprehensive recovery or cancellation coverage.

## Evidence, stop conditions and cleanup

Record fixture ID/hash, actual template/input/output counts, stream mode, concurrency,
status/error class, timing, resource peaks and cleanup result. Keep configured ceilings distinct
from observed consumption. Retain worker lifecycle and cancellation observations privately;
publish sanitized values only, replacing GPU/machine identifiers with stable anonymous aliases.
Use #2's paired-trial schedule and thresholds unchanged; this definition supplies no measurements.

Stop on any deadline/bound breach, unexpected denial, unplanned failure, unmet containment or
conflicting device use. Close clients, stop/remove only the project container, and verify its
workers and device allocations disappear, the endpoint closes and no project job remains.
Do not require zero whole-device memory: unrelated driver state may remain; compare against the
recorded idle state and identify project process removal. Keep bounded private failure evidence.
Delete only disposable project cache/temp state when its case requires it; retain acquired
artifacts and comparison results unless explicitly choosing a fresh-project reproduction.
Never prune shared stores or delete unrelated caches. If cleanup cannot be verified, record
failure and require operator inspection before another run.

#4 owns acquisition/launch and access feasibility; #5 owns the executable baseline/harness;
#6/#7 own traces/syscall review; #8/#9 own policy/enforcement; #10 owns full comparison;
#11 owns reproduction commands. These scenarios define the experiment without implementing them.
