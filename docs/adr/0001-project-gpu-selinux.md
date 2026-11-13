# 0001: Project-specific GPU access under enforcing SELinux

## Status

Accepted for the exact approved installation on 2026-11-13. Policy linking and a bounded
cached-image CDI diagnostic passed. Pinned-image/model acquisition and inference remain untested.

## Context

On Fedora 44 with container-selinux 2.251.0, the rootless CDI diagnostic fails with
`Failed to initialize NVML: Insufficient Permissions` (exit 4). The host audit records
`container_t` denied `read` and `getattr` on `/dev/nvidiactl`, whose type is
`xserver_misc_device_t`, with `permissive=0`. Unix device access modes allow access.
The default seccomp profile remains enabled; no SELinux exception was applied.

## Decision

Use [granite_server.cil](../../policy/selinux/granite_server.cil), an opt-in
`granite_server.process` domain inheriting the installed container-selinux `container`
and `net_container` templates. Add only character-device `getattr`, `open`, `read`,
`write`, `ioctl` and `map` for `xserver_misc_device_t` from that domain. Read/getattr
are observed denials; the other operations are candidate NVIDIA userspace requirements,
not trace-derived evidence. Keep MCS constraints supplied by the base template.

Select the domain explicitly with `--security-opt label=type:granite_server.process`.
Do not change `container_t`, device labels, SELinux booleans, or enforcement mode.
[Provisioning and bounded validation](../launch.md) record the exact approved installation.
Use the upstream [udica template workflow](https://github.com/containers/udica), without
installing its generator or copying the distribution's container baseline into this repo.

## Consequences

This is scoped by process type, not by GPU identity. The target device type covers other
NVIDIA devices and may cover non-GPU devices. CDI must expose only the selected A6000 and
necessary support nodes; a compromised process can access the injected driver interfaces.
A trusted local operator can deliberately select this domain for another container.
The network template permits networking; network isolation and loopback publication remain
separate launch requirements. This policy supplies no egress restriction or driver protection.
Inherited permissions can change when container-selinux changes; record its version and
hash both templates, then repeat affected verification after upgrades. The bounded diagnostic
verified one selected GPU, MCS, NNP and default seccomp; it performed no inference. A new denial
requires investigation, not automatic grants.

## Considered & rejected

- Keep the unchanged default domain. **verified:** the bounded rootless CDI `nvidia-smi`
  probe on Fedora 44 exits 4 and the enforcing host audit records the denial above.
- Disable container labeling. **judgment:** incompatible with the approved confinement
  requirement even if the host remains enforcing; it is not an authorized fallback.
- Enable the shared device boolean or grant access to `container_t`. **judgment:** changes
  access for unrelated containers; a project-specific domain is a narrower permission change.
- Relabel physical GPU nodes into a project device type. **judgment:** introduces host-device
  labeling and lifecycle maintenance affecting other GPU users, beyond the needed process grant.
