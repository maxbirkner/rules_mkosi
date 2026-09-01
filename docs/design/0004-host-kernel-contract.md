# Design: host-kernel contract for unprivileged mkosi actions

- **Status:** Accepted for the spike
- **Date:** 2026-08-29

## Decision

The host boundary can remain kernel-only on a qualifying Linux runner. The
development environment's ordinary (unsandboxed) `bazel run` denied the
namespace mount, but the same probe passed as a Bazel test under the default
Linux sandbox. Therefore the decision is **go for sandboxed Bazel actions** and
**no-go for an unsandboxed image action** on this environment.

The minimum supported kernel is Linux **5.12**. Typed bind mounts use the
descriptor-only mount API: `open_tree(parent_fd, name, OPEN_TREE_CLONE)`,
`fstat` validation, detached-fd recursive `mount_setattr` with
`AT_EMPTY_PATH`, and `move_mount(MOVE_MOUNT_F_EMPTY_PATH)`. Read-only
attributes are applied before the detached mount is attached, so no
post-attach destination lookup can redirect the protection. The first two
APIs were introduced in Linux 5.2; `mount_setattr` was introduced in Linux
5.12, so there is no pathname-based compatibility path on older kernels.

The Bazel Linux sandbox must remain enabled. The preflight itself runs as an
ordinary Bazel test action and checks the exact operations needed by an
unprivileged action. A runner is qualified only when the preflight passes
while the default Linux sandbox remains enabled.

## Probe

`//mkosi:kernel_preflight` is a Bazel-built C executable. It uses Linux system
calls and reads procfs directly; it does not invoke a shell, package manager,
filesystem utility, Python, mkosi, QEMU, or any executable found through
`PATH`.

Run the probe as a Bazel test from the repository with:

```console
bazel test --config=kernel_preflight \
  //mkosi/private:kernel_preflight_host_test
```

Every root CI matrix job enforces the Linux sandbox explicitly with:

```console
bazel shutdown
bazel test --config=kernel_preflight \
  //mkosi/private:kernel_preflight_host_test
```

The checked-in `kernel_preflight` config selects optimized compilation,
exclusive test execution, full test output, and the non-hermetic Linux sandbox.
The explicit shutdown starts a fresh Bazel server before the qualification
test, avoiding a stale or transient Linux-sandbox availability result. The
command intentionally fails if that strategy cannot be registered; falling
back to `processwrapper-sandbox` would not qualify the mount contract.

Every check emits `PASS` or `FAIL` with a remediation, followed by a
`RESULT kernel_contract` line. A non-zero exit status means the host is not
qualified. `--proc-root=PATH` exists only to make sysctl diagnostics testable. The
portable fixture test injects operation results and never performs namespace
or mount syscalls; only the qualified host test exercises those operations on the
running kernel.

`bazel run //mkosi:kernel_preflight` is also available for inspecting a
runner, but `bazel run` is not itself a sandboxed action. Its result is not a
substitute for the test above. The test is tagged `requires_kernel_contract` so portable
repository tests do not accidentally claim that an arbitrary execution
environment is an image runner.

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

No host userspace executable, package cache, network, writable host mount,
or ambient capability is part of the contract. Bazel's normal Linux sandbox
must remain enabled. The probe's bind mounts and root transition occur only in
the child namespace, and the child exits after detaching the old root. A privileged starting namespace is
rejected before any namespace operation; the capability check is repeated
after mapping and root transition. The capability list and mount sequence are
intentionally limited to the operations used by mkosi v27's offline sandbox:
set capability sets, `execve`, tmpfs workspace setup, initial `pivot_root`,
recursive bind, final `pivot_root(".", ".")`, and old-root detach.

## CI requirements and limits

The dedicated Linux image job must run the explicitly sandboxed host test
before any mkosi action and must fail the job on
`RESULT kernel_contract: FAIL`. The runner must permit the namespace,
namespace-scoped capability, bind mount, and `pivot_root` operations under
Bazel's default Linux sandbox. A sandboxed action that reports `EPERM` for any
of these checks is not a valid image runner; changing the action to search
`PATH`, disabling the sandbox, or granting host-wide `CAP_SYS_ADMIN` is not an
acceptable workaround.

This spike deliberately does not test `systemd-repart`, mkosi, package
acquisition, loop devices, or QEMU. Those are Bazel-provided toolchain inputs
and separate execution-platform contracts. In particular, the probe does not
claim that the kernel alone supplies systemd's mount API policy, filesystem
drivers, loop-device policy, or repartitioning behavior. It establishes the
namespace and root-transition substrate on which the offline repartitioning
action can run.
