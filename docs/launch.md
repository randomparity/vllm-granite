# Pinned acquisition and confined GPU launch

The stdlib `scripts/granite.py` command separates online acquisition from offline diagnostics
and foreground serving. Full inference/fit and workload measurements belong to #5.

On 2026-11-13 the operator approved the exact three hashed CIL inputs below; installation
and the bounded no-network diagnostic succeeded. These commands document that prerequisite;
another installation requires its own host-admin decision and module reconciliation. #2's
image/model pins and resource limits remain unchanged. Full inference/fit belongs to #5.

## Approved permission change

[granite_server.cil](../policy/selinux/granite_server.cil) adds an opt-in process domain,
`granite_server.process`, using the distribution's container and networking templates.
Its only explicit device grant is `getattr open read write ioctl map` on character devices
with type `xserver_misc_device_t`. Existing `container_t` is unchanged. The base template
includes MCS constraints; the network template is not an egress firewall. Device identity
and reachability still need actual launch validation. See [ADR 0001](adr/0001-project-gpu-selinux.md).

Prerequisites already observed on the target: Fedora 44/x86_64, container-selinux
2.251.0-1.fc44, SELinux policy 44.11-1.fc44, policycoreutils 3.11, Podman 5.8.7,
crun 1.28, NVIDIA toolkit 1.19.1 and enforcing SELinux. The templates are supplied by
container-selinux; udica installation is unnecessary. Verify them before an authorized installation:

```bash
getenforce
rpm -q container-selinux selinux-policy-targeted policycoreutils
sha256sum policy/selinux/granite_server.cil \
  /usr/share/udica/templates/base_container.cil \
  /usr/share/udica/templates/net_container.cil
```

Candidate validation performed before installation: the installed libsepol 3.11 parser
accepted the candidate and both templates and rejected a deliberately malformed CIL input.
Referenced types, attributes and character-device permissions resolve in the loaded policy;
`granite_server.process` was absent at that checkpoint. The later authorized installation
linked successfully; the runtime evidence below remains narrower than full inference proof.

Reviewed input SHA-256 values (recheck before installation):

| Input | SHA-256 |
| --- | --- |
| `granite_server.cil` | `603de717bf2ae6506a8a140eceef3f3d1345a1b37d11b8fd3038670222fabdb3` |
| `base_container.cil` | `c95d8badacc674ace0d2fed4fbee4d28d2a92799b23fd5cc30cfb444ee8896b7` |
| `net_container.cil` | `9af286e5e19e15cffaaf7b29c745c800ef94c03d90ee90e0e8e18edc2ebf8f01` |

The administrator must first inspect the module inventory. An existing module with one of
these names requires reconciliation; do not overwrite another project's modules or templates:

```bash
sudo semodule -lfull
```

After the exact-input approval and module reconciliation, this installation succeeded:

```bash
sudo semodule -i policy/selinux/granite_server.cil \
  /usr/share/udica/templates/base_container.cil \
  /usr/share/udica/templates/net_container.cil
```

This installs the project module and template modules, links the host policy and reloads it.
The administrator should record which modules were already present and their versions before
installation. No boolean, physical-device label, permissive domain or global enforcement change
is part of this request. A link failure is a blocker; do not disable policy checks to proceed.

## Bounded validation result and repetition

The approved no-network CDI diagnostic passed. To repeat after an authorized change, use
the project process label, default seccomp,
read-only root, dropped capabilities, no-new-privileges, one CPU, 256 MiB RAM/no additional
swap and 64 PIDs. Use the exact selected A6000 CDI UUID privately and compare the returned
identity privately; publish only the stable device alias. The earlier diagnostic used an
already-local vLLM image, not the #2 pin, so it established only the host access blocker.
Pinned-image acquisition and the full launch still require their own verification. The successful
diagnostic verified exactly the selected A6000, its supporting control/UVM/capability nodes,
`granite_server.process` with MCS, `Seccomp: 2`, `NoNewPrivs: 1`, and zero effective capabilities.
SELinux remained enforcing, both shared device booleans remained off, no fresh project AVC
appeared, and the owned container was removed. No additional policy grant was needed.

A separate cached-image internal-network HTTP diagnostic also passed: loopback publication
worked, non-loopback publication failed, and external/mapped-host/host-address TCP attempts
failed. The owned internal network had DNS disabled and no gateway; cleanup passed. This
is sampled reachability evidence, not a claim about the unacquired pinned image or inference.

Observe the process label and MCS categories externally and verify `Seccomp: 2` and
`NoNewPrivs: 1`. Check the host audit for fresh denials. Require exactly the selected GPU;
enumerate actual injected device nodes. Remove only the disposable project container and
verify it is absent. Stop on failure and investigate; do not extend policy automatically.
This diagnostic performs no inference and downloads no model weights.

## Rollback after an authorized installation

Stop project containers using the domain before removing its module:

```bash
sudo semodule -r granite_server
```

Do not remove `base_container` or `net_container` if they predated this change or are used by
another policy. If this installation introduced them, the administrator may separately remove
unused template modules after checking dependents. Recheck enforcing mode and the module
inventory. Rollback removes the project grant; it does not make the unchanged launch feasible.

## Approved desktop baseline for #4 verification

The operator separately approved retaining the specific observed terminal process at 38 MiB.
This is not a name-based exception for desktop applications. The launcher accepts an optional
operator-supplied private JSON record containing `gpu`, `pid`, `starttime`, `exe` and `max_mib: 38`.
It checks that exact identity and ceiling before launch and while serving; additional compute
processes must belong to the owned container. Without that record, other compute processes refuse
launch. No automatic baseline capture or unrelated-process stop is authorized. Keep concrete
identifiers private and publish only sanitized occupancy.

## Acquire, check, serve

Use the observed Fedora 44/x86_64 toolchain above, Python 3, coreutils, iproute, NVIDIA driver
615.71.09 and a rootless Podman store. CDI configuration must expose the selected A6000 UUID.
Keep 80 GiB free on each filesystem holding state or the Podman store; runtime preflight requires
48 GiB available RAM, eight CPUs and GPU free memory for the 0.80 allocation plus 6 GiB.
Do not concurrently pull, prune or otherwise mutate the shared Podman store during acquisition
or a run: growth since the recorded baseline is conservatively charged to this experiment.

From the repository root, select the A6000 UUID privately, then acquire the immutable pins:

```bash
export GRANITE_STATE="$HOME/.local/share/granite-4"
nvidia-smi --query-gpu=uuid,name --format=csv,noheader
export GRANITE_GPU='<A6000-UUID>'
python3 scripts/granite.py acquire --state "$GRANITE_STATE"
python3 scripts/granite.py check --state "$GRANITE_STATE" --gpu "$GRANITE_GPU"
python3 scripts/granite.py serve --state "$GRANITE_STATE" --gpu "$GRANITE_GPU"
```

Acquisition verifies the image platform/digest and the model's 13 selected data files against
revision metadata, sizes and content hashes. It excludes model repository Python code. Serving
uses only those local files with network access restricted; it never pulls missing artifacts.
`check` runs HTTP/device/resource diagnostics without loading weights. `serve` repeats that
check, then starts the local model and reports readiness at `http://127.0.0.1:8000` with model alias
`granite`. Ctrl-C stops/removes owned containers/networks; cache and logs remain for inspection.
A ready endpoint is not an inference quality or fit result. Run #5's workload separately.

Default preflight rejects other compute processes. Only for the separately approved desktop
baseline, append `--desktop-baseline "$GRANITE_DESKTOP_BASELINE"` to check/serve; this variable
must name the private, operator-reviewed record described above. Its values must come from the
approved observation, not an automatic snapshot of whatever processes currently happen to run.
Process restart, identity mismatch or usage above 38 MiB requires inspection, not a fresh exemption.

The launcher creates private state, locks it, mounts model data read-only and preserves a bounded
cache. Hard limits include 32 GiB RAM/no swap, eight CPUs, 1024 PIDs, private 4 GiB shared memory,
1 GiB temporary space and 64 MiB runtime space. Disk scans monitor image/scratch 32 GiB, model
20 GiB, cache 8 GiB, logs/state 4 GiB, total 64 GiB; these are stop conditions, not disk quotas.
GPU memory is monitored against 40 GiB; sampling can overshoot. Startup is bounded to 600 seconds,
session to 3600 seconds, graceful stop to 30 seconds. Breaches, forced kill and cleanup failures
are failures; no security/resource fallback occurs.

Raw logs, process/device identities and refusal details stay under private state. Inspect the
reported error path before retrying. `logs/resources.json` records the exact owned container/network
names; after SIGKILL/power loss, inspect those names and stop/remove only verified owned resources.
Never use a broad prune or stop unrelated processes. No automatic restart/recovery is provided.
The optional desktop record is outside the container; model/cache are the only host data mounts.

Run the focused static checks without GPU or network use:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Pinned-image live acquisition/check evidence is recorded after executing these commands against
committed source; cached-image prerequisite evidence above does not substitute for that result.
