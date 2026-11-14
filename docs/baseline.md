# Bounded baseline harness

`scripts/baseline.py` explicitly runs the default-seccomp baseline using the existing
[pinned acquisition and confined launcher](launch.md). Ordinary unit tests run no GPU
workload. The host must already meet that launcher's provisioning, containment and
[resource prerequisites](compatibility.md); this command changes no host policy.

From the repository root, after checking the selected A6000 and any exact operator-approved
private desktop record, use the existing state and GPU variables from the launch guide:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/baseline.py \
  --state "$GRANITE_STATE" --gpu "$GRANITE_GPU" --reset-cache
```

If a specific private desktop identity was explicitly approved, add
`--desktop-baseline "$GRANITE_DESKTOP_BASELINE"`. The command checks that exact process
identity and 38 MiB ceiling; it never creates an exemption. `--reset-cache` explicitly
discards only the project's disposable compilation-cache contents after acquiring the
exclusive state lock and refusing containers that still reference the cache. It retains
weights, evidence and the mounted cache/backing. Without that flag an occupied cold cache
is refused. Never run another cache/store writer or GPU workload during the trial.

The trial limit is 60 minutes. It materializes immutable mode0400 private request bytes
using the pinned image's local tokenizer/template and explicit token-ID return, then runs
cold and warm starts with a first completion, two warmups and 20 timed requests at each
concurrency1/2 for each cache class. Requests use one user message/completion, temperature0, seed0 and cap256 (over-context
rejection cap1). The fixed order cycles short/plain, long/plain,
short/stream, long/stream five times. Functional cases cover exact context admission,
five invalid bodies, observed disconnect/slot release, active graceful stop/restart and a
synthetic insufficient-capacity refusal. A naturally occurring resource failure preserves
a failed trial; at most one restart after restored preflight can establish diagnostic
recovery. No stress allocation is performed.

Private `baseline-fixtures.json` contains the frozen payloads; retain it for #10. Each run
creates a private `results/baseline-<random>/` directory. `private.json` retains runtime
observations; `sanitized.json` contains IDs/hashes/counts, settings and numerical outcomes,
without prompts, outputs, device identities or host paths. Errors are private. Review the
entire sanitized file before publication. Missing/unexercised required cases cannot pass.
The endpoint and project container/network are removed on normal error/signal cleanup;
a killed launcher still needs the owned-resource reconciliation described in the launch guide.

Latency and TTFT are grouped by cache, concurrency, fixture and stream mode. p95 uses
nearest rank. Class throughput divides achieved output tokens by the interval from that
class's first start to last completion, including interleaved classes; it is not isolated
single-class decoding throughput. Device memory is a sampled maximum; cgroup memory.peak
is kernel-maintained. Configured ceilings remain distinct from these observations.
The three paired baseline/custom trials and ratio judgments belong to #10.

## First actual result: failed before inference

On 2026-11-13, executable commit
`3ec2f62e11985702151bfd75e26b47d4af72daab` stopped after **20.504 seconds** while
materializing fixtures. The pinned image's transformers5.19.0 returned a two-field
`BatchEncoding` from `apply_chat_template`; the original harness counted fields instead
of token IDs. The failure was retained, the diagnostic container/network were cleaned,
and no model weight load, inference, cold/warm measurement or timed request ran.
The synthetic W-resource refusal passed; the remaining scenarios are explicitly not-run.
See the [sanitized failed result](evidence/baseline-first-attempt.json).

One separately authorized offline tokenizer-only diagnostic reproduced the return shape
and verified the repair, explicit `return_dict=False`, without loading weights or running
inference. It confirmed rendered counts **21, 3838, 3840 and 4097** for F-short, F-long,
F-context and rejection-only F-over; F-long uses637 repetitions. The regression failed
before the fix and passed afterward. Repair commit:
`025f60778d2bd3c79e0c1b128bbbfbe74dba340b`.
The [fixture manifest](evidence/baseline-fixtures.json) freezes hashes/counts/settings;
the corresponding exact private bytes are retained. This verifies fixture construction,
not server admission or GPU inference. The operator subsequently approved one additional bounded measurement trial; its failed
result is recorded below.

## Second actual result: rejected serving argument

The additional authorized attempt at executable commit
`3ac96203f784adc176bc6d8990d9e6864a9dbe18` failed after **42.760 seconds**. Fixture
materialization succeeded, but vLLM exited2 before readiness with
`vllm: error: unrecognized arguments: --disable-log-requests`.
The observer then encountered the already removed cgroup; the retained container log
established the original CLI cause. No inference or timed request ran.

Cold-session cleanup was independently verified in **0.379 seconds**: the original cgroup,
project GPU processes and endpoint disappeared, and device memory returned to its initial
sampled baseline. See the [sanitized second result](evidence/baseline-second-attempt.json).
The request-logging option is now the supported `--no-enable-log-requests`; the
[versioned vLLM0.32 CLI reference](https://docs.vllm.ai/en/v0.32.0/cli/serve/)
also records request logging's default as false. Repair commit
`3b82ee2d8a88cb68a29cdfacd688ffe74acfc67c` also records server exit state before reading
removed cgroup files, preserving the actionable startup cause. Both behaviors have focused
regressions. A subsequent complete pinned serving-CLI parser/validation probe passed without
loading weights or constructing an inference engine, followed by the authorized third trial below.

## Third actual result: measurements retained, active stop failed

One further explicitly authorized trial at executable commit
`e09c880a0e8f90b2091c3f62e4423f555db672dd` failed after **498.470 seconds**.
Cold readiness/first completion were **53.020/54.106 seconds**; warm times were
**30.560/31.646 seconds**. All **80 timed requests** completed with validated JSON/SSE
contracts. The [sanitized third result](evidence/baseline-third-attempt.md) retains all
16 cache/concurrency/fixture/stream class summaries, including achieved output counts,
median/p95 latency, streaming TTFT and throughput under the definition above.

The 3840-token context was admitted and the 4097-token input rejected. All five invalid
cases returned client errors; continued service was checked afterward. Disconnect handling
observed outstanding requests fall from1 to0 in **0.110 seconds**, followed by a successful
F-short. Sampled device memory peaked at **38.54 GiB** below40 GiB; kernel cgroup memory.peak
was **2.48 GiB** below32 GiB. The mandatory synthetic resource refusal passed; actual
allocator recovery was unexercised. Cold cleanup passed in **1.206 seconds**.

The warm session then attempted W-stop with a streaming request active. The pinned server's
default zero shutdown timeout selected engine abort mode; its HTTP server waited for the
held connection until the outer 30-second stop forced a kill, exit137. The trial stopped;
restart was **not run**. A separate post-failure observation verified both original cgroups,
project GPU processes, endpoint and project networks were absent, with device memory back
to its initial sampled baseline. That establishes resource release after failure, not a
successful graceful stop.

Repair `4b938b7e046ee4a65ad0be43ba1dffd3f079ea7c` sets the native `--shutdown-timeout` to20 seconds inside the unchanged
30-second outer stop bound. The [versioned vLLM reference](https://docs.vllm.ai/en/v0.32.0/cli/serve/)
documents positive values as an in-flight drain period. A focused regression failed before
the repair; all49 unit tests passed afterward. **The repaired stop path has not run live.**
The earlier parser probe applies to the pre-repair candidate; it did not validate this added
option. The third result retains the original scenario flags, which were finalized only at
whole-trial success; the completed startup/request records supply the partial observations.
Functional response checks passed, but their individual latency/output-token records were
not retained. These limits are not replaced by the timed-request measurements.

The inference baseline remains **incomplete** because active graceful stop and restart are
unproven. All three authorized measurement attempts are consumed; another requires an
explicit operator decision. Pins, resource limits and security settings remain unchanged.
A failure stays a failed trial.
