#define _GNU_SOURCE

#include "kernel_preflight.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/capability.h>
#include <linux/sched.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>

static void report(FILE *output, const char *status, const char *name,
                   const char *format, ...) {
  va_list arguments;

  fprintf(output, "%s %s: ", status, name);
  va_start(arguments, format);
  vfprintf(output, format, arguments);
  va_end(arguments);
  fputc('\n', output);
}

static bool proc_path(char *path, size_t path_size, const char *proc_root,
                      const char *suffix) {
  int length = snprintf(path, path_size, "%s/%s", proc_root, suffix);
  return length >= 0 && (size_t)length < path_size;
}

static int read_integer(const char *path, long *value) {
  char buffer[128];
  char *end;
  ssize_t bytes_read;
  int file;

  file = open(path, O_RDONLY | O_CLOEXEC);
  if (file < 0) {
    return -errno;
  }
  bytes_read = read(file, buffer, sizeof(buffer) - 1);
  if (bytes_read < 0) {
    int error = errno;
    close(file);
    return -error;
  }
  close(file);
  buffer[bytes_read] = '\0';
  errno = 0;
  *value = strtol(buffer, &end, 10);
  if (errno != 0 || end == buffer) {
    return -EINVAL;
  }
  while (*end == ' ' || *end == '\t' || *end == '\r' || *end == '\n') {
    ++end;
  }
  return *end == '\0' ? 0 : -EINVAL;
}

static int read_mapping(const char *path, unsigned long *inside,
                        unsigned long *outside, unsigned long *length) {
  char buffer[128];
  char *cursor;
  char *end;
  ssize_t bytes_read;
  int file;

  file = open(path, O_RDONLY | O_CLOEXEC);
  if (file < 0) {
    return -errno;
  }
  bytes_read = read(file, buffer, sizeof(buffer) - 1);
  if (bytes_read < 0) {
    int error = errno;
    close(file);
    return -error;
  }
  close(file);
  buffer[bytes_read] = '\0';
  cursor = buffer;
  errno = 0;
  *inside = strtoul(cursor, &end, 10);
  if (errno != 0 || end == cursor) {
    return -EINVAL;
  }
  cursor = end;
  *outside = strtoul(cursor, &end, 10);
  if (errno != 0 || end == cursor) {
    return -EINVAL;
  }
  cursor = end;
  *length = strtoul(cursor, &end, 10);
  if (errno != 0 || end == cursor) {
    return -EINVAL;
  }
  return 0;
}

static int read_effective_capabilities(uint64_t *capabilities) {
  char buffer[1024];
  char *line;
  ssize_t bytes_read;
  int file;

  file = open("/proc/self/status", O_RDONLY | O_CLOEXEC);
  if (file < 0) {
    return -errno;
  }
  bytes_read = read(file, buffer, sizeof(buffer) - 1);
  if (bytes_read < 0) {
    int error = errno;
    close(file);
    return -error;
  }
  close(file);
  buffer[bytes_read] = '\0';
  line = strstr(buffer, "CapEff:");
  if (line == NULL) {
    return -EINVAL;
  }
  line += strlen("CapEff:");
  errno = 0;
  *capabilities = strtoull(line, &line, 16);
  return errno == 0 ? 0 : -errno;
}

static int check_initial_privilege(char *detail, size_t detail_size,
                                   void *context) {
  unsigned long inside = 0;
  unsigned long outside = 0;
  unsigned long length = 0;
  uint64_t capabilities = 0;
  int result;
  (void)context;

  result = read_mapping("/proc/self/uid_map", &inside, &outside, &length);
  if (result < 0 || length == 0) {
    snprintf(detail, detail_size,
             "cannot establish the starting UID mapping; refuse to qualify "
             "an unknown privilege state");
    return 0;
  }
  result = read_effective_capabilities(&capabilities);
  if (result < 0) {
    snprintf(detail, detail_size,
             "cannot inspect CapEff; refuse to qualify an unknown privilege "
             "state");
    return 0;
  }
  if (outside == 0 && (geteuid() == 0 || getegid() == 0)) {
    snprintf(detail, detail_size,
             "the action starts as host root (uid=%ld gid=%ld); run it as an "
             "unprivileged identity",
             (long)geteuid(), (long)getegid());
    return 0;
  }
  if ((capabilities & (UINT64_C(1) << CAP_SYS_ADMIN)) != 0) {
    snprintf(detail, detail_size,
             "the action starts with ambient CAP_SYS_ADMIN; remove the "
             "capability before running unprivileged");
    return 0;
  }
  snprintf(detail, detail_size,
           "starting identity is unprivileged (uid=%ld gid=%ld)",
           (long)geteuid(), (long)getegid());
  return 1;
}

static int wait_for_child(pid_t child, int *status_out) {
  int status;

  while (waitpid(child, &status, 0) < 0) {
    if (errno != EINTR) {
      return -errno;
    }
  }
  if (status_out != NULL) {
    *status_out = status;
  }
  return 0;
}

static int write_all(int file, const char *buffer, size_t size) {
  while (size > 0) {
    ssize_t bytes = write(file, buffer, size);
    if (bytes < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -errno;
    }
    buffer += bytes;
    size -= (size_t)bytes;
  }
  return 0;
}

static int write_mapping(pid_t child, const char *name, unsigned long value) {
  char path[128];
  char mapping[64];
  int file;
  int length;

  length = snprintf(path, sizeof(path), "/proc/%ld/%s_map", (long)child, name);
  if (length < 0 || (size_t)length >= sizeof(path)) {
    return -ENAMETOOLONG;
  }
  length = snprintf(mapping, sizeof(mapping), "0 %lu 1\n", value);
  if (length < 0 || (size_t)length >= sizeof(mapping)) {
    return -EINVAL;
  }
  file = open(path, O_WRONLY | O_CLOEXEC);
  if (file < 0) {
    return -errno;
  }
  {
    int result = write_all(file, mapping, (size_t)length);
    close(file);
    return result;
  }
}

static int deny_setgroups(pid_t child) {
  char path[128];
  int file;
  int length;

  length = snprintf(path, sizeof(path), "/proc/%ld/setgroups", (long)child);
  if (length < 0 || (size_t)length >= sizeof(path)) {
    return -ENAMETOOLONG;
  }
  file = open(path, O_WRONLY | O_CLOEXEC);
  if (file < 0) {
    return -errno;
  }
  {
    int result = write_all(file, "deny\n", 5);
    close(file);
    return result;
  }
}

static int check_namespace_capability(void) {
  struct __user_cap_header_struct header = {
      .version = _LINUX_CAPABILITY_VERSION_3,
      .pid = 0,
  };
  struct __user_cap_data_struct data[2] = {};

  if (syscall(SYS_capget, &header, data) < 0) {
    return -errno;
  }
  return (data[CAP_SYS_ADMIN / 32].effective &
          (UINT32_C(1) << (CAP_SYS_ADMIN % 32))) != 0
             ? 0
             : -EPERM;
}

static int child_namespace_setup(int ready, int acknowledgement) {
  char base[128];
  char source[160];
  char destination[160];
  char newroot[160];
  char oldroot[160];
  char signal = 'R';
  int length;

  if (syscall(SYS_unshare, CLONE_NEWUSER) < 0) {
    return 0;
  }
  if (write_all(ready, &signal, 1) < 0) {
    return 1 << 0;
  }
  if (read(acknowledgement, &signal, 1) != 1 || signal != 'A') {
    return 1 << 0;
  }
  if (setresgid(0, 0, 0) < 0 || setresuid(0, 0, 0) < 0 ||
      geteuid() != 0 || getegid() != 0) {
    return (1 << 0) | (1 << 1);
  }
  if (check_namespace_capability() < 0) {
    return (1 << 0) | (1 << 1) | (1 << 2);
  }
  if (syscall(SYS_unshare, CLONE_NEWNS) < 0) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3);
  }
  if (mount(NULL, "/", NULL, MS_PRIVATE | MS_REC, NULL) < 0) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3);
  }

  length = snprintf(base, sizeof(base), "/tmp/rules-mkosi-preflight-%ld",
                    (long)getpid());
  if (length < 0 || (size_t)length >= sizeof(base)) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4);
  }
  length = snprintf(source, sizeof(source), "%s/source", base);
  if (length < 0 || (size_t)length >= sizeof(source)) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4);
  }
  length = snprintf(destination, sizeof(destination), "%s/destination", base);
  if (length < 0 || (size_t)length >= sizeof(destination)) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4);
  }
  length = snprintf(newroot, sizeof(newroot), "%s/newroot", base);
  if (length < 0 || (size_t)length >= sizeof(newroot)) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5);
  }
  length = snprintf(oldroot, sizeof(oldroot), "%s/newroot/oldroot", base);
  if (length < 0 || (size_t)length >= sizeof(oldroot)) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5);
  }
  if (mkdir(base, 0700) < 0 || mkdir(source, 0700) < 0 ||
      mkdir(destination, 0700) < 0 || mkdir(newroot, 0700) < 0 ||
      mkdir(oldroot, 0700) < 0) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4);
  }
  if (mount(source, destination, NULL, MS_BIND | MS_REC, NULL) < 0) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4);
  }
  if (umount2(destination, MNT_DETACH) < 0) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4);
  }
  if (mount(newroot, newroot, NULL, MS_BIND | MS_REC, NULL) < 0) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) |
           (1 << 5);
  }
  if (chdir(newroot) < 0 ||
      syscall(SYS_pivot_root, ".", "oldroot") < 0 ||
      umount2("oldroot", MNT_DETACH) < 0) {
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) |
           (1 << 5);
  }
  return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) |
         (1 << 6);
}

static int actual_namespace_setup(rules_mkosi_namespace_checks *checks,
                                void *context) {
  int acknowledgement[2];
  int ready[2];
  int result_pipe[2];
  int child_result = 0;
  pid_t child;
  char signal;
  unsigned long uid;
  unsigned long gid;
  (void)context;

  if (prctl(PR_SET_DUMPABLE, 1) < 0) {
    return 0;
  }
  if (pipe(ready) < 0) {
    return 0;
  }
  if (pipe(acknowledgement) < 0) {
    close(ready[0]);
    close(ready[1]);
    return 0;
  }
  if (pipe(result_pipe) < 0) {
    close(ready[0]);
    close(ready[1]);
    close(acknowledgement[0]);
    close(acknowledgement[1]);
    return 0;
  }
  child = fork();
  if (child < 0) {
    close(ready[0]);
    close(ready[1]);
    close(acknowledgement[0]);
    close(acknowledgement[1]);
    close(result_pipe[0]);
    close(result_pipe[1]);
    return 0;
  }
  if (child == 0) {
    close(ready[0]);
    close(acknowledgement[1]);
    close(result_pipe[0]);
    child_result = child_namespace_setup(ready[1], acknowledgement[0]);
    (void)write_all(result_pipe[1], (const char *)&child_result,
                    sizeof(child_result));
    _exit(child_result == ((1 << 7) - 1) ? 0 : 1);
  }
  close(ready[1]);
  close(acknowledgement[0]);
  close(result_pipe[1]);
  if (read(ready[0], &signal, 1) == 1 && signal == 'R') {
    checks->user_namespace = 1;
    uid = (unsigned long)getuid();
    gid = (unsigned long)getgid();
    if (deny_setgroups(child) == 0 && write_mapping(child, "gid", gid) == 0 &&
        write_mapping(child, "uid", uid) == 0) {
      checks->id_mapping = 1;
      signal = 'A';
    } else {
      signal = 'F';
    }
    (void)write_all(acknowledgement[1], &signal, 1);
  }
  close(ready[0]);
  close(acknowledgement[1]);
  if (read(result_pipe[0], &child_result, sizeof(child_result)) !=
      (ssize_t)sizeof(child_result)) {
    child_result = 0;
  }
  close(result_pipe[0]);
  (void)wait_for_child(child, NULL);
  checks->user_namespace = (child_result & (1 << 0)) != 0;
  checks->id_mapping = (child_result & (1 << 1)) != 0;
  checks->root_transition = (child_result & (1 << 2)) != 0;
  checks->namespace_capabilities = (child_result & (1 << 3)) != 0;
  checks->mount_namespace = (child_result & (1 << 4)) != 0;
  checks->bind_mount = (child_result & (1 << 5)) != 0;
  checks->pivot_root = (child_result & (1 << 6)) != 0;
  return 1;
}

static int check_sysctl(FILE *output, const char *proc_root) {
  char path[256];
  long value;
  int result;

  if (!proc_path(path, sizeof(path), proc_root,
                 "sys/user/max_user_namespaces")) {
    report(output, "FAIL", "user.max_user_namespaces",
           "the procfs path is too long");
    return 1;
  }
  result = read_integer(path, &value);
  if (result < 0) {
    report(output, "FAIL", "user.max_user_namespaces",
           "cannot read %s (%s); mount procfs and set the value above zero",
           path, strerror(-result));
    result = 1;
  } else if (value <= 0) {
    report(output, "FAIL", "user.max_user_namespaces",
           "%ld; set /proc/sys/user/max_user_namespaces above zero", value);
    result = 1;
  } else {
    report(output, "PASS", "user.max_user_namespaces", "%ld (> 0)", value);
    result = 0;
  }

  if (!proc_path(path, sizeof(path), proc_root,
                 "sys/kernel/unprivileged_userns_clone")) {
    report(output, "FAIL", "kernel.unprivileged_userns_clone",
           "the procfs path is too long");
    return result + 1;
  }
  {
    int sysctl_result = read_integer(path, &value);
    if (sysctl_result == -ENOENT) {
      report(output, "PASS", "kernel.unprivileged_userns_clone",
             "not exposed by this kernel; the clone probe is authoritative");
    } else if (sysctl_result < 0) {
      report(output, "FAIL", "kernel.unprivileged_userns_clone",
             "cannot read %s (%s); allow unprivileged user namespaces", path,
             strerror(-sysctl_result));
      ++result;
    } else if (value <= 0) {
      report(output, "FAIL", "kernel.unprivileged_userns_clone",
             "%ld; set /proc/sys/kernel/unprivileged_userns_clone to 1",
             value);
      ++result;
    } else {
      report(output, "PASS", "kernel.unprivileged_userns_clone", "%ld", value);
    }
  }
  return result;
}

int rules_mkosi_kernel_preflight_with_ops(
    const char *proc_root, FILE *output,
    const rules_mkosi_kernel_preflight_ops *ops) {
  rules_mkosi_kernel_preflight_ops actual_ops = {
      .check_initial_privilege = check_initial_privilege,
      .run_namespace_setup = actual_namespace_setup,
      .context = NULL,
  };
  rules_mkosi_namespace_checks namespace_checks = {};
  char detail[256];
  struct stat proc_stat;
  struct utsname kernel;
  char path[256];
  int failures = 0;

  if (ops == NULL) {
    ops = &actual_ops;
  }
  if (uname(&kernel) < 0 || strcmp(kernel.sysname, "Linux") != 0) {
    report(output, "FAIL", "linux_kernel",
           "mkosi actions require a Linux kernel (%s)",
           uname(&kernel) < 0 ? strerror(errno) : kernel.sysname);
    ++failures;
  } else {
    report(output, "PASS", "linux_kernel", "%s %s", kernel.sysname,
           kernel.release);
  }

  if (!proc_path(path, sizeof(path), proc_root, "self/ns/user")) {
    report(output, "FAIL", "procfs_namespaces",
           "the procfs path is too long");
    ++failures;
  } else if (stat(path, &proc_stat) < 0) {
    report(output, "FAIL", "procfs_namespaces",
           "cannot inspect %s (%s); mount procfs in the action environment",
           path, strerror(errno));
    ++failures;
  } else if (!proc_path(path, sizeof(path), proc_root, "self/ns/mnt")) {
    report(output, "FAIL", "procfs_namespaces",
           "the procfs path is too long");
    ++failures;
  } else if (stat(path, &proc_stat) < 0) {
    report(output, "FAIL", "procfs_namespaces",
           "cannot inspect %s (%s); mount procfs in the action environment",
           path, strerror(errno));
    ++failures;
  } else {
    report(output, "PASS", "procfs_namespaces",
           "user and mount namespace handles are available");
  }

  if (ops->check_initial_privilege == NULL ||
      !ops->check_initial_privilege(detail, sizeof(detail), ops->context)) {
    report(output, "FAIL", "initial_privilege", "%s",
           detail[0] == '\0' ? "privilege check failed" : detail);
    ++failures;
  } else {
    report(output, "PASS", "initial_privilege", "%s", detail);
  }
  failures += check_sysctl(output, proc_root);
  if (ops->run_namespace_setup == NULL ||
      !ops->run_namespace_setup(&namespace_checks, ops->context)) {
    report(output, "FAIL", "namespace_setup",
           "the namespace setup operation could not be started");
    ++failures;
  }
  if (namespace_checks.user_namespace) {
    report(output, "PASS", "user_namespace",
           "CLONE_NEWUSER succeeded for an unprivileged child");
  } else {
    report(output, "FAIL", "user_namespace",
           "CLONE_NEWUSER failed; enable unprivileged user namespaces");
    ++failures;
  }
  if (namespace_checks.id_mapping) {
    report(output, "PASS", "id_mapping",
           "setgroups=deny, uid_map, and gid_map completed");
  } else {
    report(output, "FAIL", "id_mapping",
           "setgroups=deny and UID/GID maps failed; allow the parent to write "
           "/proc/<pid>/{setgroups,uid_map,gid_map}");
    ++failures;
  }
  if (namespace_checks.root_transition) {
    report(output, "PASS", "root_transition",
           "mapped identity became uid=0,gid=0 inside the user namespace");
  } else {
    report(output, "FAIL", "root_transition",
           "could not transition to mapped root inside the user namespace");
    ++failures;
  }
  if (namespace_checks.namespace_capabilities) {
    report(output, "PASS", "namespace_capabilities",
           "CAP_SYS_ADMIN is effective only in the new user namespace");
  } else {
    report(output, "FAIL", "namespace_capabilities",
           "new user namespace lacks CAP_SYS_ADMIN; do not grant host "
           "CAP_SYS_ADMIN");
    ++failures;
  }
  if (namespace_checks.mount_namespace) {
    report(output, "PASS", "mount_namespace",
           "CLONE_NEWNS succeeded after the user namespace transition");
  } else {
    report(output, "FAIL", "mount_namespace",
           "CLONE_NEWNS failed after the user namespace transition");
    ++failures;
  }
  if (namespace_checks.bind_mount) {
    report(output, "PASS", "bind_mount",
           "a recursive bind mount succeeded in the private mount namespace");
  } else {
    report(output, "FAIL", "bind_mount",
           "a recursive bind mount failed in the private mount namespace");
    ++failures;
  }
  if (namespace_checks.pivot_root) {
    report(output, "PASS", "pivot_root",
           "pivot_root detached the old root in the private namespace");
  } else {
    report(output, "FAIL", "pivot_root",
           "pivot_root or old-root detachment failed; a private root is "
           "required");
    ++failures;
  }

  if (failures == 0) {
    report(output, "RESULT", "kernel_contract", "PASS (all checks passed)");
  } else {
    report(output, "RESULT", "kernel_contract",
           "FAIL (%d check%s failed)", failures, failures == 1 ? "" : "s");
  }
  return failures == 0 ? 0 : 1;
}

int rules_mkosi_kernel_preflight(const char *proc_root, FILE *output) {
  return rules_mkosi_kernel_preflight_with_ops(proc_root, output, NULL);
}
