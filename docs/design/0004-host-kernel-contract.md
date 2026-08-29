# Design: host-kernel contract for unprivileged mkosi actions

- **Status:** Accepted for the spike
- **Date:** 2026-08-29

## Decision

The host boundary can remain kernel-only on a qualifying Linux runner. The
development environment's ordinary (unsandboxed) `bazel run` denied the
namespace mount, but the same probe passed as a Bazel test under the default
Linux sandbox. Therefore the decision is **go for sandboxed Bazel actions** and
**no-go for an unsandboxed image action** on this environment.

The Bazel Linux sandbox must remain enabled. The preflight itself runs as an
ordinary Bazel test action and checks the exact operations needed by an
unprivileged action. A runner is qualified only when the preflight passes
while the default Linux sandbox remains enabled.

## Probe

`//mkosi:kernel_preflight` is a Bazel-built C executable. It uses Linux system
calls and reads procfs directly; it does not invoke a shell, package manager,
filesystem utility, Python, mkosi, QEMU, or any executable found through
`PATH`.

Run the probe as a Bazel action from the repository with:

```console
bazel test //mkosi/private:kernel_preflight_host_test --test_output=all
```

Every check emits `PASS` or `FAIL` with a remediation, followed by a
`RESULT kernel_contract` line. A non-zero exit status means the host is not
qualified. `--proc-root=PATH` exists only to make sysctl diagnostics testable;
namespace and mount checks always exercise the running kernel and cannot be
faked by a fixture.

`bazel run //mkosi:kernel_preflight` is also available for inspecting a
runner, but `bazel run` is not itself a sandboxed action. Its result is not a
substitute for the test above. The test is tagged `manual` so portable
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
| Mount namespace and mount capability | An unprivileged child can create `CLONE_NEWUSER \| CLONE_NEWNS` and mount a small tmpfs inside it. | Allow namespace-scoped `CAP_SYS_ADMIN` and unprivileged mounts; do not grant host `CAP_SYS_ADMIN`. |

No host userspace executable, package cache, network, writable host mount,
or ambient capability is part of the contract. Bazel's normal Linux sandbox
must remain enabled. The probe's tmpfs is mounted only in the child namespace
and is detached before the child exits.

## CI requirements and limits

The dedicated Linux image job must run the probe before any mkosi action and
must fail the job on `RESULT kernel_contract: FAIL`. The runner must permit
the two namespace operations and the namespace-scoped tmpfs mount under
Bazel's default Linux sandbox. A sandboxed action that reports `EPERM` for the
mount check is not a valid image runner; changing the action to search `PATH`,
disabling the sandbox, or granting host-wide `CAP_SYS_ADMIN` is not an
acceptable workaround.

This spike deliberately does not test `systemd-repart`, mkosi, package
acquisition, loop devices, or QEMU. Those are Bazel-provided toolchain
inputs and separate execution-platform contracts. The probe establishes only
the kernel substrate on which the offline repartitioning action can run.
