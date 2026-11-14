# Container-scoped diagnostic capture — issue #6

## Problem and authority
Issue #6 and epic #1 require syscall evidence for the pinned baseline workload.
The operator approved the exact exclusions, implementation, rootless diagnostic
OCI prestart-hook design and two bounded no-GPU probes. Both probes are consumed.
GPU capture requires a later concrete approval. See [ADR0003](../../adr/0003-rootless-prestart-observer.md).

## Scope and ownership
Extend granite.launch with an optional capture lifecycle; ordinary serving stays unchanged.
Add scripts/tracing.py as the host observer owner. baseline.Trial creates one capture
for each cold, warm and restart serving session, excluding tokenizer fixture preparation.
No owner migration or obsolete path exists: baseline still owns requests/cache transitions,
and granite still owns container creation, confinement and cleanup.
Syscall interpretation belongs to #7, policy to #8, controls to #9, comparison to #10,
fresh-state reproduction/maintenance to #11. No pin, global hook, privilege or policy changes.

## Design and success
Provide baseline's explicit --trace switch. Create private capture directories under its
existing private results directory. Capture requires the tested Fedora44/x86_64 toolchain,
host strace7.2, Python3, rootless Podman5.8.7/crun1.28 and existing confinement prerequisites.
Use a per-container annotation and private --hooks-dir; hook timeout6s, arming timeout4s.
Read OCI state, validate its init PID and container identity, then start a separate host
observer supervisor. Verify TracerPid before allowing the prestart hook to return.
Use strace -f --always-show-pid -ttt --decode-pids=pidns with raw=!clone,clone3,fork,vfork
argument formatting and one output file. Decoded process-creation results retain host PID
translation comments; reconcile clone return IDs to host record prefixes. In a private PID
namespace, missing translations or child lifecycle records fail coverage. Keep the remaining
arguments raw; process-creation arguments and PID translations remain private.
Follow observed clone/fork/vfork descendants including threads, through final task exits.
No container devices, capabilities, namespaces or security settings change for tracing.
Keep the observer alive through granite.cleanup; then require its successful exit and
complete trace validation. Missing hook, exec, task exit, clone relationship, malformed line,
observer diagnostic other than attachment notices, partial line or full file budget fails
the session/trial. No automatic retry or automatic resource-error recovery when tracing.
Each raw file and observer stderr has a hard RLIMIT_FSIZE ceiling of256MiB; at most three
serving captures per trial. Existing80GiB free-space preflight remains. Check observer health
in startup and workload sampling; cleanup runs even when tracing fails.
Validate the strace stream incrementally rather than loading256MiB into RAM. Require root
application exec, lineage closure and terminal records for the observed task set. A prestart
bootstrap resumed syscall may precede the first application exec; record no completeness
claim for earlier runtime setup. ptrace stops are synchronous; there is no sampled-event
loss counter. Treat detach, unknown output, write failure or observer death as coverage loss.
Sanitized summary allowlists status, cache/workload IDs, task/syscall-record counts,
capture bytes/SHA256 and tracer version. Existing baseline summaries retain tested versions,
commit, image/model/profile and fixture hashes. No raw lines, arguments, PIDs, paths,
container IDs or observer diagnostics enter public summaries. Failed evidence remains private.
Document explicit provisioning and operator invocation; untraced runs retain prior behavior.

## Failure model
- Actors and deployments: trusted local operator and pinned baseline image/model on the
  selected Fedora44/x86_64 enforcing-SELinux host; potentially malformed local API input.
- Invariants and assets: startup/descendant/teardown evidence completeness; private arguments;
  bounded local disk/RAM; exact-container cleanup; unchanged production confinement.
- Accepted failure classes: prestart runtime bootstrap calls are outside application coverage;
  ptrace overhead is diagnostic cost, bounded by unchanged600s startup/3600s trial deadlines;
  hostile deliberate observer evasion is outside this trusted workload's evidence claim.
- Covered elsewhere: application request limits/cleanup=baseline and granite; syscall meaning=#7;
  policy/control/comparison=#8/#9/#10; fresh setup/revalidation=#11. Failed runs require a new
  explicit operator decision to rerun, not an automatic capture retry.

## Threat model
- Added boundaries: OCI hook state to host observer; syscall stream and diagnostics to validator;
  private results to sanitized public summary. Widened boundary: optional launch arguments.
- Actors: trust the operator, same-user private directory and pinned application; API callers
  may cause arbitrary private syscall argument text. Same-user malicious tampering and root
  are outside the existing private-state trust model.
- Controls: verify hook identity/PID/TracerPid; explicit argv, no shell interpolation; private
  owned directories/umask077; RLIMIT plus bounded streaming parser; fail closed on loss;
  summary field allowlist, no exception text in public output; exact project cleanup only.
- Exclusions: no host-wide observer, privilege escalation, production tracing, hostile-kernel
  resistance or automated allowlist generation. Existing threat-model-and-workload.md applies.

## Validation
Run meaningful parser/lifecycle/integration red-green tests and the repository unittest suite,
plus git diff --check. Exercise real rootless prestart/exec/short-lived descendants/final
teardown using the installed tooling and pinned image; the approved feasibility proof passed.
Before declaring issue complete, obtain separate approval and execute one traced baseline
cold/warm/restart workload with unchanged limits, publish sanitized evidence and hashes,
and disclose failed/skipped cases. No automatic GPU execution is authorized by this spec.
