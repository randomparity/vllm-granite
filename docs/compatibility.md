# Compatibility candidates and initial budget

Recorded 2026-11-13 for [#2](https://github.com/randomparity/vllm-granite/issues/2)
and [epic #1](https://github.com/randomparity/vllm-granite/issues/1).
**Status: inventory and proposed baseline; inference, rootless GPU access and policy
compatibility are unvalidated.** Metadata inspection downloaded no image layers or weights.

## Host matrix

These are sanitized read-only observations, not a tested combination or vendor certification.
Recollect them before measurement; retain raw output privately and publish only selected fields.

| Component | Observation | Evidence and qualification |
| --- | --- | --- |
| OS / architecture | Fedora 44 Workstation / x86_64 | OS release metadata; `uname -m` |
| Kernel | 7.2.9-200.fc44.x86_64 | `uname -r`; GPU/container integration untested |
| GPU / driver | RTX A6000, 49140 MiB reported, compute capability 8.6 / 615.71.09 | `nvidia-smi` selected name, memory, capability, driver fields; other GPUs exist and must be excluded |
| Podman | 5.8.7 | `podman --version`; rootless reported by `podman info` |
| OCI runtime | crun 1.28 | `podman info` selects crun; `crun --version` reports SELinux/seccomp support |
| NVIDIA Container Toolkit | 1.19.1 | `nvidia-ctk --version`; CDI and device access untested |
| Cgroups | v2 / systemd; memory, cpu, io, pids controllers reported | `podman info`; delegation and actual limit enforcement untested |
| SELinux | Enforcing; Podman reports enabled | `getenforce`, selected `podman info` fields; GPU labels/access untested |
| Seccomp | Podman reports enabled; default profile is installed | `podman info`; this does not prove a filter is loaded into a future container |

The toolkit's [tested platform list](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/supported-platforms.html)
does not list Fedora 44. Treat it as an unqualified host integration candidate; #4 must prove
feasibility and report blockers without changing distro, privileges or security settings silently.
Keep enforcing SELinux, the runtime default seccomp baseline and loopback-only publication.
[Podman documents profile selection and defaults](https://docs.podman.io/en/stable/markdown/podman-run.1.html);
[NVIDIA documents Podman/CDI integration](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html).
Rootless Podman inventory alone proves neither GPU access nor resource-limit enforcement.

## Immutable upstream candidates

Candidate selection is source-backed; successful execution remains #4/#5 work.

- vLLM **v0.32.0**, [published non-prerelease](https://github.com/vllm-project/vllm/releases/tag/v0.32.0).
  The [GitHub releases API](https://api.github.com/repos/vllm-project/vllm/releases?per_page=10) returned v0.33.0rc3 as latest with `prerelease:false`, while
  v0.33.0 tag lookup returned 404. Choose the newest returned non-RC release rather than
  treating inconsistent latest/tag metadata as a stable pin. Recheck this decision before acquisition.
- Image: `docker.io/vllm/vllm-openai@sha256:6ee133356d49ed24cee03dd0cda3d3980279a11c107ce3e752c89e76540f41c9`
  (linux/amd64 child manifest). Registry v0.32.0 index:
  `sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34`.
  Read through the [Docker Registry API](https://distribution.github.io/distribution/spec/api/):
  resolve the tag index, select linux/amd64, fetch the child manifest and config blob;
  require each response digest to match. This is metadata resolution, not signature verification.
  Config records CUDA 13.0.2 and build commit `5df63a7203cdb9328d824a27b682e77c7b9928be`;
  compressed layers total 9,205,727,079 bytes. #4 must verify the acquired digest and runtime version.
- Model/tokenizer: `ibm-granite/granite-4.2-8b`, revision
  `a7042144125ce5ae64f89610e8289647fc000b9a`, returned by the
  [model metadata API](https://huggingface.co/api/models/ibm-granite/granite-4.2-8b).
  Pin tokenizer to the same revision; do not resolve `main` during serving.
  [Pinned config](https://huggingface.co/ibm-granite/granite-4.2-8b/blob/a7042144125ce5ae64f89610e8289647fc000b9a/config.json)
  is `GraniteForCausalLM`, BF16, 40 layers, 8 KV heads, 4096 hidden / 32 attention heads.
  The [pinned weight index](https://huggingface.co/ibm-granite/granite-4.2-8b/blob/a7042144125ce5ae64f89610e8289647fc000b9a/model.safetensors.index.json)
  reports 16,761,102,336 weight bytes (about 15.61 GiB).
- Precision/backend proposal: BF16 weights and KV cache (`--dtype bfloat16`,
  `--kv-cache-dtype auto`), no quantization, one GPU/tensor-parallel size 1,
  `FLASH_ATTN` using FA2. The [versioned backend matrix](https://docs.vllm.ai/en/v0.32.0/design/attention_backends/)
  supports BF16 FA2 on compute capability >=8.0; FA3 requires 9.x. The A6000 is 8.6.
  [IBM's pinned model card](https://huggingface.co/ibm-granite/granite-4.2-8b/blob/a7042144125ce5ae64f89610e8289647fc000b9a/README.md)
  specifies BF16 and vLLM v0.20+ for its optional custom reasoning parser.
  Parser/plugin selection belongs to #3/#4; do not execute repository plugins implicitly.
- [Versioned GPU requirements](https://docs.vllm.ai/en/v0.32.0/getting_started/installation/gpu/)
  state CUDA 13 images normally need R580+ and Linux 4.15+. Inventory exceeds these floors,
  but kernel/driver numbering alone does not establish binary/model/backend compatibility.
  No host CUDA toolkit installation is introduced by this record.

## Initial envelope (proposed, not measured)

Freeze these values before #5; revise openly and restart affected baseline comparisons if they
fail feasibility. GiB means 2^30 bytes. Stop on allocation failure or unmet prerequisites.

| Resource | Initial bound |
| --- | --- |
| Context | 4096 total tokens per sequence, including template, prompt, reasoning and output; output at most 256 tokens and input/template at most 3840 |
| Concurrency | 1 normally, at most 2 active requests; at most 2 sequences; batched-token ceiling 4096 |
| GPU | Exactly one A6000; utilization target 0.80 (~38.39 GiB of reported memory); observed device peak at most 40 GiB; at least 6 GiB initially free outside the proposed allocation; no competing GPU workloads |
| Host RAM | Container limit 32 GiB, no additional swap; require at least 48 GiB available before starting; stop the container on its OOM, never stress the host to OOM |
| CPU / processes | At most 8 CPUs and 1024 PIDs; verify delegation first; do not infer worker count from the host CPU count |
| Shared memory | Private IPC, at most 4 GiB tmpfs, counted within the RAM limit; no host IPC |
| Disk | Reserve 80 GiB free on each affected filesystem before acquisition; project growth ceiling 64 GiB total: image/store 32, model 20, compilation cache 8, logs/results 4; no unrelated cache cleanup |
| Time | Startup deadline 600 s, request deadline 120 s, graceful stop 30 s; one comparison session at most 60 min |

Weight size is not total VRAM. A plain BF16 KV estimate is
`2 * 40 * 8 * 128 * 2 = 163840 bytes/token`; 2 sequences of 4096 tokens need about
1.25 GiB KV, before allocator, activations, compilation and graph overhead. This is an estimate,
not fit evidence. vLLM may reserve additional KV capacity within its utilization target.
Observed device peak includes every process on the selected device; CPU offload is not proposed.
Disk bounds include unpacking and cache overhead; fail acquisition when actual growth exceeds them.
If fewer CPUs, restricted RAM, slow disk or other occupancy prevents this envelope, report it;
do not enlarge limits, use another GPU or relax containment to obtain a pass.

## Predeclared comparison protocol

#3 owns scenario definitions and fixture IDs; #5 proves the default-profile baseline; #10 runs
the complete baseline/custom comparison. This protocol fixes measurement and judgment in advance.

1. Freeze commit, image digest, model/tokenizer revision, kernel/driver/runtime/toolkit versions,
   selected GPU alias, resolved dtype/backend/FA version, all limits, request fixtures/token counts,
   cache state and both profile hashes (hash the actual runtime default too). Use identical pins,
   launches and request sets between arms; the profile is the only intended changed variable.
   Keep prompts and raw traces private. No download time counts as startup.
2. Use three paired trials, alternating baseline/custom order (B/C, C/B, B/C), with one container
   at a time. Each arm starts with its own fresh project compilation cache for cold startup,
   then retains that cache for a warm restart; keep the acquired weights and OS file cache warm
   for both arms and disclose that definition of cold. Never drop host-wide caches.
3. Per startup, time launch to ready and successful first completion; report both. Before timing
   requests, run two warmup requests. Per trial/arm, issue 20 timed requests at concurrency 1 and
   20 at concurrency 2, fixed temperature/seed/output cap and bounded fixture set from #3.
   Record achieved output tokens, errors, TTFT for streaming, end-to-end latency, aggregate output
   tokens/s, peak device memory, cgroup memory peak and cleanup outcome. Report cold/warm timings
   separately; compute nearest-rank p95 per request class, not across mixed classes.
4. Compare per-trial custom/baseline ratios using matched workload/cache classes, then report
   their median and full range across three trials. Proposed pass thresholds: cold/warm startup,
   median and p95 latency/TTFT at most 1.10x baseline; throughput at least 0.90x baseline; GPU and
   RAM peaks at most 1.10x baseline **and** within the absolute envelope. Require all declared
   functional/enforcement cases to pass, no unexpected denials, no unplanned failures or leaks.
5. Stop a trial on a deadline, memory/disk bound, unexpected denial or resource failure; preserve
   a sanitized failure result and clean only project state. A 60-minute session cap or missing
   arm produces an incomplete result, never a passing comparison. Slow/variable baselines,
   inconsistent cache classes or conflicting GPU use make the comparison inconclusive; revise
   and predeclare a new protocol before rerunning, retaining the original failure and rationale.

No measured inference or performance results exist in this record. #4 owns acquisition,
provisioning and rootless/CDI/SELinux feasibility; #5 owns measured fit; #6–9 own tracing and
policy/enforcement; #10–11 own complete regression and operator reproduction. Any change to
pins, kernel, driver, runtime, toolkit, backend, resource envelope or workload requires affected
compatibility and baseline measurements to be repeated. No installed combination is certified.
