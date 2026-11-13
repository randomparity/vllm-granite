# 0002: Bound persistent cache with a finite filesystem

## Status

Accepted by the operator on 2026-11-13. Provisioning and a separate bounded allocation test passed;
pinned-image integration is required before handoff.

## Context

The compromised worker can open, unlink and continue writing a cache file. Directory scans miss
its allocated blocks indefinitely. This is not ordinary sampling overshoot. The observed Btrfs
host has quotas disabled; unrelated frees can mask filesystem free-space deltas.

## Decision

Use a root-owned NOCOW, preallocated exact 8 GiB ext4 backing file, manually loop-mounted
`nosuid,nodev` at the existing empty cache. Retain native security xattrs and private `:Z`
labeling, enforcing SELinux, default seccomp and rootless containers. The worker sees the cache
mount only, never its backing file or block device. No automatic startup or new policy grant.
Metadata reduces usable cache bytes below 8 GiB; the operator explicitly accepts this.

At runtime require the exact ext4 filesystem-root mount and loop device, matching device
identity, exact 8 GiB sysfs device size, filesystem capacity no larger than 8 GiB, private
ownership/mode and required mount options. Account the entire backing allocation once in
the 64 GiB disk budget. Missing observations or an unmounted directory fail closed.
[Provisioning and rollback](../launch.md) accompany the prerequisite.

## Consequences

Open-but-unlinked allocations reach filesystem ENOSPC instead of escaping directory accounting.
Cache persists across serving stops and manual remounts. Admin mounting is required after reboot;
no service or fstab entry is supplied. Root/operator compromise and host-admin image snapshots,
reflinks or resize are outside prevention; prohibit those operations while mounted. Executable
cache mappings remain needed by compilation; nosuid/nodev, NNP and capabilities constrain use.
Other disk/GPU monitors retain their documented sampling overshoot.

A separate 64 MiB image refused unlinked writes at 55,574,528 bytes in 0.154 seconds; backing
size/allocation stayed 67,108,864 bytes. The probe unmounted normally and its loop detached;
only probe-created artifacts were removed. Production backing/cache are retained.

## Considered & rejected

- Directory scans alone. **verified:** open-unlinked allocation is absent from directory accounting.
- Filesystem free-space differences. **judgment:** unrelated frees can mask growth.
- Btrfs qgroups. **verified:** disabled on this host; enabling them affects filesystem-wide accounting,
  and the installed manual states inconsistent qgroups stop enforcing limits.
- Temporary memory-backed cache. **judgment:** fails the persistent-cache contract for #5.
