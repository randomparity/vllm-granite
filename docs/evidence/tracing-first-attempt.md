# First traced workload attempt: failed before readiness

The human-invoked issue #6 campaign received separate approval for one traced
baseline trial on 2026-11-14. Executable commit:
`4bd2fa38a148277d4744858fdf9b19097ecdc3c6`.
The invocation exited 1 after 69.823 s (trial report: 69.702265 s).

The fixture-preparation diagnostic passed. Cold serving then failed with
`trace: prestart acknowledgment missing`. No hook observer or raw capture was
created. No readiness, first completion, timed requests, JIT coverage, warm
session or restart was established. W-resource's synthetic refusal passed;
the other W-* cases remained not-run. The trial is failed, not partial success.

Cause: the private hooks directory was configured on `podman create` only.
The separate `podman start` process generates the OCI spec and selects hooks
from its own runtime configuration. Podman 5.8.7's rootless path returns no hooks
when that configuration has no HooksDir. The earlier single-command `podman run`
feasibility probe did not exercise this boundary. The repair carries the same
private hook directory into start; it has a focused split-command regression.
See upstream [start initialization and hook selection](https://github.com/containers/podman/blob/v5.8.7/libpod/container_internal.go).

Cleanup recorded a forced kill (exit 137) after the 30 s graceful-stop bound;
the trial's cleanup verdict remains failed. Independent read-only checks then
verified the exact container/network, cold cgroup/scope and fixture-preparation
cgroup were absent, the endpoint was closed and selected-device processes had
returned to the unchanged approved desktop record. No observer identity existed.
No automatic recovery, second GPU invocation or privilege change occurred.

Tested versions: Fedora 44/x86_64; kernel 7.2.9-200.fc44.x86_64;
Podman 5.8.7; crun 1.28-1.fc44.x86_64; driver 615.71.09; toolkit 1.19.1;
vLLM 0.32.0; host strace 7.2. Container confinement and resource limits were unchanged.
Image digest: `6ee133356d49ed24cee03dd0cda3d3980279a11c107ce3e752c89e76540f41c9`.
Model revision: `a7042144125ce5ae64f89610e8289647fc000b9a`.
Default profile SHA256: `2598b3b98e6970f37f917e210202fa8976aefcd99abf8955803a6e35bba17eb4`.
Fixture-template SHA256: `f0ba43f79b3cabca5e5a7584c77aec92f49feae45cdf7779c87d9fc54cd90258`.
Retained sanitized-result SHA256: `6d5318a3f46ef38b35f7e7ceb47924c13b92c9d68362ae2cc76da8bc6ec4bd50`.
Raw capture hashes do not exist. Private inputs, event identities, logs and failure
details remain local; this report publishes no raw syscall text or machine identity.

At this attempt the repair remained live-unverified and the first grant was consumed.
A separately authorized [second attempt](tracing-second-attempt.md) subsequently passed;
it does not change this failed result.
