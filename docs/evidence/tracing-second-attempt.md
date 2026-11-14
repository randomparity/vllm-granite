# Second traced workload attempt: passed

The human-invoked issue #6 campaign separately approved one <=60 s no-GPU
split-create/start proof and, only if it passed, one additional traced baseline.
The proof passed in 1.372 s using the actual collector: four tasks, 1,269 syscall
records, 98,996 private bytes, exact cleanup. Its raw SHA256 is
`7c06670b67b0326cc7919b459d641801eccf960422e474713d9c14838ad9f884`.
The earlier [failed attempt](tracing-first-attempt.md) remains failed and retained.

## Tested run

Executable commit: `bc55d95fc2a1da9f57615b9ca933c073dd1574ea`.
The single conditional invocation exited 0 after 649.663 s; the trial report records
649.555096 s. No automatic retry/recovery, administrator action, privilege
relaxation, profile change or extra GPU invocation occurred. Cold means a reset
of disposable project compilation contents with acquired weights and OS cache warm.
Cold initialization included the pinned vLLM compilation path; warm/restart retained cache.

Versions: Fedora 44/x86_64, kernel 7.2.9-200.fc44.x86_64, Podman 5.8.7,
crun 1.28-1.fc44.x86_64, driver 615.71.09, toolkit 1.19.1, vLLM 0.32.0,
host strace 7.2. Image/model/resource settings match the baseline.

| Session | Ready s | First completion s | Graceful stop/remove s |
| --- | ---: | ---: | ---: |
| cold | 98.696751 | 99.804974 | 4.267552 |
| warm | 55.103134 | 56.211679 | 10.562238 |
| restart | 55.178770 | 56.285588 | 3.953671 |

## Capture completeness

The private prestart hook acknowledged TracerPid before application exec. The
observer followed task creation including worker threads through final exits;
namespace-translated lineage, application exec and terminal records validated.
Each observer exited 0 with only permitted attachment diagnostics. Independent
streamed SHA256/byte checks matched the retained summaries. Decoded creation
records containing CLONE_THREAD were present in each session (165/154/152 records;
these are record counts, not an interpretation of syscall necessity).

| Session | Traced tasks | Syscall records | Raw bytes | Raw SHA256 |
| --- | ---: | ---: | ---: | --- |
| cold | 245 | 2606226 | 229391572 | 50dd7dfbabffc675d7d394b3a0bbb5640d223db8d7e345207fb683fc50b130fe |
| warm | 189 | 1994315 | 184458315 | 885d6a05dc889499adf262849ccf6ebc95e01d55a777686ba4a935f02c904f04 |
| restart | 188 | 1489130 | 125729570 | f43b42e09bd0ab4f7009f6ed429b55545f0a695867089b8768381cc8c9142ee2 |

Total raw evidence: 539579457 bytes, below the 768 MiB trial
budget; each file stayed below 256 MiB. Raw files and metadata are mode 0600 beneath
mode 0700 private directories. No detach, unavailable record, truncation, exhausted
budget, observer failure or incomplete lifecycle was accepted as complete.

## Workload and teardown

W-start, W-chat, W-context, W-invalid, W-cancel, W-stop and W-resource passed.
There were 80 timed JSON/SSE requests across cold/warm concurrency 1/2 classes.
Context 3840 passed and 4097 was rejected; invalid cases returned 400/404.
Cancellation gauges went 1 to 0, with slot release in 0.112493 s and a successful
following short completion. Active graceful stop terminated with the SSE terminal
marker in 10.562238 s; restart completed successfully. W-resource used the declared
synthetic refusal with zero allocations; runtime resource-error recovery remained
unexercised. No host OOM or GPU stress was induced.

Sampled GPU peak was 38.543945 GiB, below 40 GiB;
cgroup memory.peak was 2676670464 bytes, below 32 GiB.
All three cleanups passed. Independent final checks confirmed the exact container,
network, session cgroups and endpoint absent/closed, observers no longer running,
and selected-device processes back to the unchanged approved desktop record.

## Public and private artifacts

The [sanitized result](tracing-second-attempt.json) is an exact copy of the reviewed
allowlisted output; SHA256 `5ee5d3361ed5a0dddcc9fcbc54567e0d22ab68e1f9af95fdae65102f46cead99`. It retains versions,
workload/fixture IDs, request hashes, settings, numeric outcomes and capture hashes.
Image digest: `6ee133356d49ed24cee03dd0cda3d3980279a11c107ce3e752c89e76540f41c9`.
Model revision: `a7042144125ce5ae64f89610e8289647fc000b9a`.
Default profile file SHA256: `2598b3b98e6970f37f917e210202fa8976aefcd99abf8955803a6e35bba17eb4`.
Fixture-template SHA256: `f0ba43f79b3cabca5e5a7584c77aec92f49feae45cdf7779c87d9fc54cd90258`.
Raw traces, prompts, outputs, process/device identities, paths and diagnostics remain
local. No raw text was automatically redacted and published. Runtime bootstrap
before the application-exec boundary and deliberate hostile observer evasion are
outside this trusted diagnostic claim. This single diagnostic run establishes no
paired overhead result, universal syscall inventory or security-policy sufficiency;
those downstream decisions remain #7–#10.
