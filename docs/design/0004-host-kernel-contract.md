# Design: host-kernel contract for unprivileged mkosi actions

- **Status:** Accepted for the spike
- **Date:** 2026-08-29

## Decision

Image actions need only kernel features, not host userspace, on a qualifying Linux runner.
On the evaluated environment, an unsandboxed `bazel run` of the probe was denied the namespace mount, while the same probe passed as a test under Bazel's default Linux sandbox.
The decision is therefore **go for sandboxed Bazel actions** and **no-go for unsandboxed image actions**.

- The minimum kernel is Linux **5.12**, the first with `mount_setattr`.
  Typed bind mounts use only the descriptor-based mount API (`open_tree`, `mount_setattr`, `move_mount`), applying read-only attributes before the mount is attached, so no later path lookup can redirect them.
  There is no pathname-based fallback for older kernels.
- Bazel's Linux sandbox must stay enabled.
  A runner is qualified only when the preflight passes inside it.

## Probe

`//mkosi:kernel_preflight` is a Bazel-built C program that uses only system calls and procfs; it runs no shell, package manager, or `PATH` lookup.
Qualify a runner with:

```console
bazel shutdown
bazel test --config=kernel_preflight \
  //mkosi/private:kernel_preflight_host_test
```

The shutdown starts a fresh server so the Linux sandbox is registered anew.
The `kernel_preflight` config forces the Linux sandbox and fails rather than falling back to a weaker sandbox, which would not qualify the mount contract.
Every check prints `PASS` or `FAIL` with a remediation, followed by `RESULT kernel_contract`; a non-zero exit means the host is not qualified.
`bazel run //mkosi:kernel_preflight` is useful for inspection but is not sandboxed and does not qualify a runner.
The host test is tagged `requires_kernel_contract`, so portable test runs never claim that an arbitrary environment can build images.

## Required contract

| Check | Requirement | Remediation |
| --- | --- | --- |
| Linux kernel | The action executes on Linux. | Select a Linux execution platform. |
| procfs namespace handles | `/proc/self/ns/user` and `/proc/self/ns/mnt` are visible. | Mount procfs in the action environment. |
| `user.max_user_namespaces` | The value is greater than zero. | Set `/proc/sys/user/max_user_namespaces` above zero. |
| `kernel.unprivileged_userns_clone` | If exposed by the kernel, the value is `1`. | Set the sysctl to `1`; kernels without this distro-specific sysctl use the clone check. |
| User namespace creation | An unprivileged `CLONE_NEWUSER` child can be created. | Enable user namespaces and the corresponding unprivileged-user policy. |
| UID/GID mapping | The parent writes `setgroups=deny`, `uid_map`, and `gid_map` for the child. | Permit procfs map writes by the unprivileged parent. |
| Root transition and capability scope | The mapped child becomes uid/gid 0, drops unwanted bounding capabilities, and establishes mkosi v27's bounding, permitted, inheritable, and ambient capability sets. | Do not start as root or with ambient `CAP_SYS_ADMIN`; enable user-namespace capabilities. |
| Capability exec transition | The required mkosi v27 capabilities remain effective, permitted, inheritable, and ambient after an `execve` transition. | Preserve the capability sets across exec; do not apply a host-wide capability grant. |
| Mount namespace and tmpfs workspace | After the user transition, `CLONE_NEWNS` succeeds and a tmpfs workspace can be mounted and entered. | Allow namespace-scoped `CAP_SYS_ADMIN` and tmpfs mounts; do not grant host `CAP_SYS_ADMIN`. |
| Initial root transition | The workspace is bind-mounted and entered with `pivot_root(".", "oldroot")`. | Permit bind mounts and `pivot_root` in the private namespace. |
| Recursive bind | A representative recursive bind from the old root into the new root succeeds. | Permit recursive namespace-local bind mounts. |
| Descriptor-only typed binds | `open_tree(parent_fd, name, OPEN_TREE_CLONE)`, `fstat`, detached-fd recursive `mount_setattr(AT_EMPTY_PATH)` for read-only mounts, and `move_mount(MOVE_MOUNT_F_EMPTY_PATH)` succeed for file and directory mounts. | Use Linux 5.12 or newer and permit the descriptor-based mount API in the action namespace. |
| Final root transition and detach | `pivot_root(".", ".")` succeeds and the old root is detached with `MNT_DETACH`. | Permit the final `pivot_root` and old-root detach in the private namespace. |

No host userspace executable, package cache, network, writable host mount, or ambient capability is part of the contract.
A privileged starting namespace is rejected, and the capability check is repeated after mapping and the root transition.
The checks are limited to the operations of mkosi v27's offline sandbox.

## Limits

A runner that reports `EPERM` for any check is not a valid image runner.
Searching `PATH`, disabling the sandbox, or granting host-wide `CAP_SYS_ADMIN` are not acceptable workarounds.

The probe does not test `systemd-repart`, mkosi, package acquisition, loop devices, or QEMU; those come from Bazel toolchains.
It establishes only the namespace and root-transition substrate that the offline image action runs on.
