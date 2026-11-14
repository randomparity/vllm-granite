# Fourth baseline attempt: passed

Provenance: issue #5, explicit operator approval “Approve review and one trial”, 2026-11-13.
Executable: `ecd344796385ccd958431f0eaa3ffd75817e12fc`. Status **passed**, elapsed **538.325729 s**.
All three preceding failures remain recorded; this is one baseline-only trial, not a paired comparison.
Exact retained sanitized record SHA-256:
`c64b669e641a879ece9eb48c6d02a276991fb49fce107d84131f1b84d48cd7bf`.

## Fixed configuration

A6000 alias GPU-A; pinned image/model/template/fixture hashes: [manifest](baseline-fixtures.json).
vLLM 0.32.0, BF16/automatic KV dtype, FLASH_ATTN version 2, TP1, GPU utilization 0.80,
context 4096, max sequences 2, batched tokens 4096, CPU 8, PID 1024, shared memory 4 GiB.
GPU ceiling 40 GiB; cgroup RAM/swap ceiling 32 GiB; native request drain 20 s.
Bounds: startup 600 s, request 120 s, graceful stop 30 s, whole trial 3600 s.
Cold means empty project compilation cache with acquired weights and OS cache warm.
Exact committed script bytes were compared with HEAD before execution. The complete real
serving command passed pinned ServeSubcommand parser/validate without weights/inference first.

## Startup and cleanup

| Cache | Ready s | First completion s | Graceful stop/remove s |
| --- | ---: | ---: | ---: |
| cold | 54.975487 | 56.061872 | 4.524177 |
| warm | 30.975653 | 32.063088 | 12.066869 |
| restart | 31.925692 | 33.013448 | 4.679660 |

For all three sessions: original cgroup, project GPU processes and endpoint disappeared;
device memory returned from 336592896 bytes before launch to 336592896 bytes after cleanup.

## Timed requests

All 80 timed requests validated. Each row has 5 requests. Values are median/p95 seconds;
`—` means nonstreaming TTFT unmeasured. Output tokens are achieved totals. Throughput uses
first class request start to last completion, including interleaved classes.

| Cache | C | Fixture | Stream | Latency med/p95 | TTFT med/p95 | Output | Window s | Tokens/s |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| cold | 1 | F-long | false | 6.807213/6.830785 | — | 1110 | 71.861531 | 15.446373 |
| cold | 1 | F-long | true | 6.815768/6.838804 | 0.044960/0.059003 | 1280 | 75.782415 | 16.890462 |
| cold | 1 | F-short | false | 1.082716/1.083023 | — | 210 | 64.814402 | 3.240021 |
| cold | 1 | F-short | true | 1.083781/1.100071 | 0.032832/0.053316 | 210 | 70.065987 | 2.997175 |
| cold | 2 | F-long | false | 6.848420/6.850517 | — | 1280 | 68.492442 | 18.688193 |
| cold | 2 | F-long | true | 6.848561/6.853290 | 0.064668/0.065121 | 1280 | 68.515515 | 18.681900 |
| cold | 2 | F-short | false | 1.127994/1.163770 | — | 210 | 62.769556 | 3.345571 |
| cold | 2 | F-short | true | 1.127451/1.127542 | 0.033068/0.033351 | 210 | 62.789744 | 3.344495 |
| warm | 1 | F-long | false | 6.822197/6.844476 | — | 1110 | 73.084842 | 15.187828 |
| warm | 1 | F-long | true | 6.830858/6.848079 | 0.046163/0.060861 | 1280 | 75.893465 | 16.865747 |
| warm | 1 | F-short | false | 1.085363/1.086937 | — | 210 | 65.898367 | 3.186725 |
| warm | 1 | F-short | true | 1.085995/1.091515 | 0.032954/0.041882 | 210 | 70.165555 | 2.992922 |
| warm | 2 | F-long | false | 6.838986/6.858273 | — | 1203 | 60.942463 | 19.739931 |
| warm | 2 | F-long | true | 6.855299/6.856815 | 0.066185/0.067088 | 1280 | 64.486096 | 19.849240 |
| warm | 2 | F-short | false | 1.166095/1.167315 | — | 210 | 55.214682 | 3.803336 |
| warm | 2 | F-short | true | 1.129614/1.130169 | 0.034482/0.035382 | 210 | 58.761302 | 3.573781 |

Sampled device peak: **41386246144 bytes** (38.54 GiB).
Kernel cgroup memory.peak: **2634403840 bytes** (2.45 GiB).

## Required scenarios

- W-start/W-chat: cold/warm first completions and all 80 timed JSON/SSE requests passed.
- W-context: valid 3840-token input admitted; 4097-token input rejected; F-short then passed.
- W-invalid: malformed/missing/empty/zero returned 400; unknown model 404; F-short then passed.
- W-cancel: outstanding gauge 1→0 after disconnect in 0.111712 s; F-short then passed.
- W-stop: active stream terminated with terminal marker; stop 12.066869 s; restart passed.
- W-resource: synthetic CPU 7/available RAM 47 GiB refused with 0 allocations. Natural allocator
  recovery unexercised; no allocation error or stress injection occurred.

Full exact timed request records and immutable fixture bytes remain private. Individual
functional latency/output-token records were not retained; functional response validation passed.
Sampled GPU peaks can miss transients; cgroup memory.peak is kernel-maintained.
This does not establish custom-policy enforcement, matched ratios or fresh-host reproduction.

## Runtime identity

Driver 615.71.09; kernel 7.2.9-200.fc44.x86_64; Podman 5.8.7; crun 1.28-1.fc44.x86_64;
NVIDIA Container Toolkit CLI 1.19.1, commit 09ceee5dde66ba9ce25c7cc69b1ebd5e6e3266fa.
Runtime-default seccomp source SHA-256:
`2598b3b98e6970f37f917e210202fa8976aefcd99abf8955803a6e35bba17eb4`.
Resolved OCI seccomp canonical JSON SHA-256 observed in the cold session:
`a72d56cf20d9616e7121a2e2f2840f08fd69772a71a72896142f5b912389450c`.
Default action SCMP_ACT_ERRNO; architectures X86_64/X86/X32. This profile observation
does not substitute for later tracing, syscall review or enforcement evidence.
