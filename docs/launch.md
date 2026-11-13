# Launch prerequisite: approved SELinux policy

This is the installed prerequisite for #4, **not a completed acquisition/launch package**.
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
