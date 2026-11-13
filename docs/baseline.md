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
not server admission or GPU inference. The operator subsequently approved one additional bounded measurement trial; its execution
is pending.

The first inference baseline remains **incomplete**. No fit, startup, latency, throughput,
cancellation or active-stop success is claimed from this attempt. The additional approval covers exactly one further baseline-only attempt; pins, resource
limits and security settings remain unchanged. A failure remains a failed trial.
