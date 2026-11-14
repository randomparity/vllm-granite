# Bounded inference baseline

## Problem and authority

Issue #5 and the operator-approved baseline trial require an executable proof of the
fixed launch and workload in [compatibility](../../compatibility.md) and
[scenarios](../../threat-model-and-workload.md). The approved scope is recorded in
WORK:SCOPE q5-52a0ea4d on #5. No pins, limits, privileges or scenario semantics change.

## Design and ownership

Extend the existing launcher with an optional ready-work callback and a reusable active
runtime check; its normal serve/check behavior remains. The launcher owns creation,
readiness, containment verification, resource enforcement and cleanup. The callback owns
bounded HTTP clients, fixture execution and measurements; it returns to the launcher's
existing finally cleanup. No caller migration or obsolete path is needed.

Add scripts/baseline.py as an explicit GPU CLI using the existing state lock, preflight,
Budget and launch. It runs one cold and one warm start, then a stop/restart verification.
Cold means project compilation-cache contents empty, acquired weights and OS cache warm.
Only an explicit reset option permits removal of disposable cache contents after the
state lock is held and owned resources are absent. Keep mount/backing and weights/results.

Materialize synthetic fixtures through the pinned image's installed tokenizer and local
model template, offline, without remote code or new dependencies. Freeze exact request
UTF-8 bytes, hashes, tokenizer/template identity and rendered counts. F-long selects the
largest allowed repetition count; deterministic token padding constructs exact 3840 and
4097 rendered counts and fails if round-trip verification cannot establish them.
Retain immutable fixture data privately and commit only IDs, hashes/counts/settings;
raw prompt/output bytes never enter public evidence. Later comparison reuses private bytes.

HTTP uses fixed loopback transport, no redirects/proxies, finite body/line/total-byte
bounds and one absolute request deadline. Validate nonstream JSON and SSE one-choice,
nonempty content, finish reason, terminal marker and usage; malformed/truncated/duplicate
completion fails. Include streaming usage for achieved token counts. The main callback
supervises at most two request threads and calls the launcher's resource check while
waiting; faults close active connections before propagating to cleanup.

Per cache class: first F-short, two warmups, then 20 requests at concurrency1 and 20 at
concurrency2, five each of short/long crossed with stream/nonstream in fixed alternating
order. Report per-class nearest-rank p95, median, streaming TTFT, achieved output tokens
and aggregate tokens divided by class elapsed time. Functional cases run once per trial.
The first completion deadline is min(request start + 120s, launch start + 600s, trial deadline).
Context/invalid cases assert client error and recovery F-short. Cancellation closes after
first text then requires server running/waiting request gauges to return to zero before
F-short; without observable release it is incomplete. W-stop retains a stream after its
first text while the callback returns for graceful launcher cleanup; record interruption,
stop time, old cgroup/device/endpoint disappearance, then warm restart and F-short.

Sample device use and cgroup memory/current/peak and OOM state externally during requests.
Preserve resource peaks before cgroup removal, actual runtime/profile/config identities,
commit, fixture hashes, cache class and sanitized outcomes in private bounded JSON evidence.
A failed or incomplete case cannot produce a passing trial. A naturally occurring resource
error ends the trial; at most one explicitly recorded recovery restart after clean teardown
and restored preflight is diagnostic, never converts failure to pass. No stress injection. Before allocation, call the existing capacity validator with synthetic
insufficient CPU/RAM and record its refusal/no-allocation separately from conditional recovery.

## AI evaluation

User is the local operator; trigger is explicit baseline invocation; inputs are the frozen
synthetic single-user chat fixtures; output is local text plus metrics. Only pinned image,
model/tokenizer/template are allowed sources; tools/downloads/remote code are disabled.
No fallback model or relaxed launch is allowed. Startup600s, request120s, stop30s and whole
trial3600s cap apply. Success means protocol-valid nonempty output and scenario contracts,
not exact wording or general model quality. Evaluate short/long, exact context boundary,
invalid bodies, disconnect and graceful stop; public results contain no raw generation.

## Failure model

- Actors and deployments: trusted local operator on Fedora44/x86_64/A6000; untrusted local
  model HTTP output; rootless pinned container with enforcing SELinux/default seccomp.
- Invariants/assets: unchanged envelope and containment; no unrelated deletion, writer or
  competing GPU process; absolute deadlines; bounded clients/evidence; truthful incomplete
  results; cleanup of project workers, allocations and endpoint.
- Accepted classes: model wording variation; runtime allocator recovery unexercised on a
  healthy run; OS/weight caches remain warm. These do not waive mandatory scenario coverage.
- Covered elsewhere: traces#6, syscall review#7, custom policy#8, enforcement#9, three-pair
  comparison#10, fresh-state reproduction#11. Existing launcher checks pins/containment.

## Threat model

Added boundaries: HTTP/SSE output from the container, CLI state/fixture/evidence paths,
and tokenizer output from the pinned container. Existing launch boundary is reused.
The local operator controls paths and invocation; model output is untrusted. Use private
owned non-symlink state, exclusive lock, fixed loopback endpoint, body/deadline bounds,
strict protocol validation and whitelist-only public summaries. Reject mismatched fixture
pins/hashes/counts before requests. Do not persist model text in public results.
Container compromise and GPU-driver exploitation remain the experiment's existing risks;
no new prevention claim is made. Other local API callers are excluded from the measured
trial and detected where observable; loopback supplies no authentication.

## Validation

Use focused unit tests for fixture count/identity validation, HTTP/SSE malformed/error and
completion handling, deadlines, metrics grouping/p95, and launch callback cleanup. Confirm
new tests red before implementation. Existing launcher regressions protect normal callers.
Run unittest discover and diff check; explicitly invoke the GPU CLI only after committing
the tested executable code, rechecking host prerequisites and exact approved desktop record.
Publish the first bounded live outcome with its tested commit and limits, including failures.
