# Third baseline attempt: failed active stop

Provenance: issue #5, operator-authorized third bounded baseline-only trial, 2026-11-13.
Executable: `e09c880a0e8f90b2091c3f62e4423f555db672dd`. Status **failed**, elapsed **498.469895 s**.
The fixed image/model/template/fixture hashes are in [the fixture manifest](baseline-fixtures.json).
The exact retained sanitized record has SHA-256:
`b770135db793f4dccbb629048148c2afddaafe680bd0ee31c87b5a15c011893f`.

## Configuration and observations

Same A6000 alias GPU-A, vLLM 0.32.0, BF16/automatic KV dtype, FLASH_ATTN version 2, TP1,
GPU utilization 0.80, context 4096, max sequences 2, batched tokens 4096, CPU 8, PID 1024,
shared memory 4 GiB; GPU ceiling 40 GiB and cgroup RAM/swap ceiling 32 GiB.
Bounds: startup 600 s, request 120 s, graceful stop 30 s, whole trial 3600 s.
Cold means empty project compilation cache with acquired weights and OS cache warm.

| Cache | Ready (s) | First completion (s) |
| --- | ---: | ---: |
| cold | 53.019620 | 54.105803 |
| warm | 30.559583 | 31.646229 |

All 80 timed requests validated. Each row has 5 requests. Latency and streaming TTFT use
median/p95 seconds; `—` means TTFT was not measured for nonstreaming responses.
Output tokens are achieved totals. Throughput divides those totals by the interval from
the class’s first request start to last completion, including interleaved classes.

| Cache | C | Fixture | Stream | Latency med/p95 | TTFT med/p95 | Output | Window s | Tokens/s |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| cold | 1 | F-long | false | 6.805110/6.829744 | — | 1110 | 72.013087 | 15.413865 |
| cold | 1 | F-long | true | 6.815332/6.837829 | 0.044277/0.058729 | 1280 | 74.868080 | 17.096739 |
| cold | 1 | F-short | false | 1.081393/1.082967 | — | 210 | 65.182003 | 3.221748 |
| cold | 1 | F-short | true | 1.082672/1.087742 | 0.032576/0.041758 | 210 | 69.146445 | 3.037032 |
| cold | 2 | F-long | false | 6.832947/6.846240 | — | 1203 | 64.644325 | 18.609522 |
| cold | 2 | F-long | true | 6.848316/6.850994 | 0.064869/0.066007 | 1280 | 66.253330 | 19.319784 |
| cold | 2 | F-short | false | 1.163044/1.163518 | — | 210 | 58.974198 | 3.560879 |
| cold | 2 | F-short | true | 1.127603/1.162381 | 0.033803/0.072577 | 210 | 60.530429 | 3.469329 |
| warm | 1 | F-long | false | 6.822022/6.841370 | — | 1110 | 72.186826 | 15.376767 |
| warm | 1 | F-long | true | 6.826673/6.846583 | 0.044109/0.058745 | 1280 | 75.040335 | 17.057493 |
| warm | 1 | F-short | false | 1.084390/1.085088 | — | 210 | 65.322233 | 3.214832 |
| warm | 1 | F-short | true | 1.084819/1.090286 | 0.032377/0.040949 | 210 | 69.303553 | 3.030148 |
| warm | 2 | F-long | false | 6.836394/6.836824 | — | 1280 | 67.887127 | 18.854826 |
| warm | 2 | F-long | true | 6.852646/6.853372 | 0.064401/0.064967 | 1280 | 67.904003 | 18.850140 |
| warm | 2 | F-short | false | 1.164742/1.164879 | — | 210 | 62.214954 | 3.375394 |
| warm | 2 | F-short | true | 1.127999/1.164114 | 0.032855/0.073049 | 210 | 62.179033 | 3.377344 |

Sampled device peak: **41386246144 bytes** (38.54 GiB). Cgroup memory.peak:
**2659934208 bytes** (2.48 GiB). Configured ceilings are distinct from observed peaks.

## Functional outcomes and limits

- W-start: cold/warm readiness and first nonempty completions observed as above.
- W-chat: all 80 timed requests passed; full exact request records retained privately.
- W-context: valid 3840-token input admitted; 4097-token input rejected; subsequent F-short passed.
- W-invalid: malformed/missing/empty/zero returned 400; unknown model 404; F-short then passed.
- W-cancel: outstanding gauge 1→0 after disconnect, release0.109506 s; F-short then passed.
- W-resource: synthetic CPU 7/available RAM 47 GiB refused with 0 allocations. Natural resource-error
  recovery unexercised; no stress injection or allocation failure occurred.
- W-stop: failed forced kill at outer 30-second bound, exit 137; restart not run.

Cold cleanup passed in 1.205941 s with old cgroup, GPU processes and endpoint removed.
Device memory before/after was 336592896 bytes. Warm graceful cleanup failed.
A separate manual post-failure observation verified both original cgroups, project GPU
processes, endpoint, project networks and running containers absent. Device memory returned
to 336592896 bytes (free 50608472064 bytes). This proves release after failure, not graceful stop.

The original W-start/W-chat/W-stop status flags remained `not-run` because they were assigned
only after whole-trial success. Startup/request records independently establish the partial
observations above. Functional response checks passed, but their individual latency/output-token
records were not retained. This failed trial does not prove active graceful stop or restart.

## Diagnosis and unproven repair

Private server log: shutdown selected `mode=abort timeout=0s`, killed EngineCore, then HTTP
shutdown waited for the held streaming connection until the outer stop killed the API process.
Launcher error: `run ended; cleanup failed: cleanup: forced kill`.
Repair `4b938b7e046ee4a65ad0be43ba1dffd3f079ea7c` requests native `--shutdown-timeout 20`
within the unchanged 30-second outer stop limit. The [versioned CLI reference](https://docs.vllm.ai/en/v0.32.0/cli/serve/) documents positive values as request draining.
Regression red before repair; 49 tests green afterward. **No live run of the repaired path.**
The successful earlier complete no-load serving-CLI validation covered the pre-repair arguments.

## Runtime identity

Driver 615.71.09; kernel 7.2.9-200.fc44.x86_64; Podman 5.8.7; crun 1.28-1.fc44.x86_64;
NVIDIA Container Toolkit CLI 1.19.1, commit 09ceee5dde66ba9ce25c7cc69b1ebd5e6e3266fa.
Runtime-default seccomp source SHA-256:
`2598b3b98e6970f37f917e210202fa8976aefcd99abf8955803a6e35bba17eb4`.
Warm-session resolved OCI seccomp canonical JSON SHA-256:
`a72d56cf20d9616e7121a2e2f2840f08fd69772a71a72896142f5b912389450c`.
Observed default action SCMP_ACT_ERRNO; architectures X86_64/X86/X32. Cold resolved OCI
profile was not separately captured. Enforcement analysis belongs to later issues.

A subsequent separately authorized [fourth trial](baseline-fourth-attempt.md) proved the repair.
This third attempt remains failed.
