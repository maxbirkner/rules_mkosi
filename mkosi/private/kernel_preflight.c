#include "kernel_preflight.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/sched.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
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
  close(file);
  if (bytes_read < 0) {
    return -errno;
  }
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

static int wait_for_child(pid_t child) {
  int status;

  while (waitpid(child, &status, 0) < 0) {
    if (errno != EINTR) {
      return -errno;
    }
  }
  if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
    return -ECHILD;
  }
  return 0;
}

static int check_namespace(FILE *output, const char *name, int flags,
                           const char *diagnostic) {
  pid_t child = syscall(SYS_clone, flags | SIGCHLD, 0, NULL, NULL, NULL);

  if (child < 0) {
    report(output, "FAIL", name,
           "%s (%s); enable the namespace in the kernel and allow "
           "unprivileged user namespaces",
           diagnostic, strerror(errno));
    return 1;
  }
  if (child == 0) {
    _exit(0);
  }
  if (wait_for_child(child) < 0) {
    report(output, "FAIL", name, "%s; the namespace child did not exit cleanly",
           diagnostic);
    return 1;
  }
  report(output, "PASS", name, "%s", diagnostic);
  return 0;
}

static int check_user_namespace_mount(FILE *output) {
  char directory[128];
  int result = 1;
  pid_t child = syscall(SYS_clone, CLONE_NEWUSER | CLONE_NEWNS | SIGCHLD, 0,
                        NULL, NULL, NULL);

  if (child < 0) {
    report(output, "FAIL", "user_namespace_mount",
           "CLONE_NEWUSER|CLONE_NEWNS failed (%s); mkosi needs a mount "
           "namespace with CAP_SYS_ADMIN scoped to its user namespace",
           strerror(errno));
    return result;
  }
  if (child == 0) {
    snprintf(directory, sizeof(directory), "mkosi-preflight-mount-%ld",
             (long)getpid());
    if (mkdir(directory, 0700) < 0 ||
        mount("tmpfs", directory, "tmpfs",
              MS_NODEV | MS_NOSUID | MS_NOEXEC, "size=4k") < 0) {
      _exit(1);
    }
    if (umount2(directory, MNT_DETACH) < 0 || rmdir(directory) < 0) {
      _exit(1);
    }
    _exit(0);
  }
  if (wait_for_child(child) == 0) {
    report(output, "PASS", "user_namespace_mount",
           "a tmpfs mount succeeded in a private user and mount namespace");
    result = 0;
  } else {
    report(output, "FAIL", "user_namespace_mount",
           "a tmpfs mount was denied; allow unprivileged mounts in a user "
           "namespace (CAP_SYS_ADMIN must be namespace-scoped)");
  }
  return result;
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

int rules_mkosi_kernel_preflight(const char *proc_root, FILE *output) {
  struct stat proc_stat;
  struct utsname kernel;
  char path[256];
  int failures = 0;

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

  failures += check_sysctl(output, proc_root);
  failures += check_namespace(
      output, "user_namespace", CLONE_NEWUSER,
      "CLONE_NEWUSER succeeded for an unprivileged child");
  failures += check_user_namespace_mount(output);

  if (failures == 0) {
    report(output, "RESULT", "kernel_contract", "PASS (all checks passed)");
  } else {
    report(output, "RESULT", "kernel_contract",
           "FAIL (%d check%s failed)", failures, failures == 1 ? "" : "s");
  }
  return failures == 0 ? 0 : 1;
}
