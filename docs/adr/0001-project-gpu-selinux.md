# 0001: Project-specific GPU access under enforcing SELinux

## Status

Accepted for the exact approved installation on 2026-11-13. Linking and a bounded cached-image
CDI diagnostic passed; pinned acquisition/access later passed, while inference remains untested.

## Context

On Fedora 44/container-selinux 2.251.0, rootless CDI `nvidia-smi` exits 4 with
`Failed to initialize NVML: Insufficient Permissions`. The enforcing audit records `container_t`
denied read/getattr on `/dev/nvidiactl` (`xserver_misc_device_t`); Unix modes allow access.

## Decision

Use [granite_server.cil](../../policy/selinux/granite_server.cil): opt-in `granite_server.process`
inherits distribution `container`/`net_container` templates and grants character-device
`getattr open read write ioctl map` for `xserver_misc_device_t`. Read/getattr were observed;
the remaining operations are candidate requirements, not trace-derived evidence. Retain MCS.
Select `--security-opt label=type:granite_server.process`; leave existing domains, device labels,
booleans and enforcement unchanged. [Provisioning](../launch.md) records the exact installation
using the [udica template workflow](https://github.com/containers/udica), without its generator.

## Consequences

The grant is process-type scoped, not GPU-specific; its device type can include unrelated devices.
CDI must restrict GPU exposure. Trusted operators can select this domain for other containers.
The network template is not an egress firewall; driver interfaces remain attack surfaces.
Record template hashes/versions and repeat verification after upgrades. The cached-image proof
establishes selected-GPU access, MCS/NNP/default seccomp only. Denials require investigation.

## Considered & rejected

- Default domain. **verified:** the Fedora 44 rootless CDI `nvidia-smi` probe exits 4 with the audit denial above.
- Disable labeling. **judgment:** violates approved confinement even if the host remains enforcing.
- Shared boolean/`container_t` grant. **judgment:** widens access for unrelated containers.
- Relabel physical GPU nodes. **judgment:** adds host-device lifecycle/label maintenance beyond this grant.
