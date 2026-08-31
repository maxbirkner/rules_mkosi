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

extern char **environ;

#ifndef SYS_mount_setattr
#define SYS_mount_setattr 442
#endif
#ifndef SYS_open_tree
#define SYS_open_tree 428
#endif
#ifndef SYS_move_mount
#define SYS_move_mount 429
#endif
#ifndef AT_RECURSIVE
#define AT_RECURSIVE 0x8000
#endif
#ifndef MOUNT_ATTR_RDONLY
#define MOUNT_ATTR_RDONLY 0x00000001ULL
#endif
#ifndef OPEN_TREE_CLONE
#define OPEN_TREE_CLONE 1
#endif
#ifndef OPEN_TREE_CLOEXEC
#define OPEN_TREE_CLOEXEC 0x80000
#endif
#ifndef MOVE_MOUNT_F_EMPTY_PATH
#define MOVE_MOUNT_F_EMPTY_PATH 0x00000004
#endif

struct rules_mkosi_mount_attr {
  unsigned long long attr_set;
  unsigned long long attr_clr;
  unsigned long long propagation;
  unsigned long long userns_fd;
};

enum {
  CHECK_USER_NAMESPACE = 1u << 0,
  CHECK_ID_MAPPING = 1u << 1,
  CHECK_ROOT_TRANSITION = 1u << 2,
  CHECK_NAMESPACE_CAPABILITIES = 1u << 3,
  CHECK_CAPABILITY_EXEC = 1u << 4,
  CHECK_MOUNT_NAMESPACE = 1u << 5,
  CHECK_TMPFS_WORKSPACE = 1u << 6,
  CHECK_PIVOT_ROOT_WORKSPACE = 1u << 7,
  CHECK_BIND_MOUNT = 1u << 8,
  CHECK_FD_MOUNT_API = 1u << 9,
  CHECK_PIVOT_ROOT = 1u << 10,
  CHECK_OLD_ROOT_DETACH = 1u << 11,
};

static const int required_capabilities[] = {
    CAP_CHOWN,       CAP_DAC_OVERRIDE, CAP_DAC_READ_SEARCH, CAP_FOWNER,
    CAP_FSETID,      CAP_SETGID,       CAP_SETUID,          CAP_SETPCAP,
    CAP_SYS_CHROOT,  CAP_SYS_PTRACE,   CAP_SYS_ADMIN,       CAP_SYS_RESOURCE,
    CAP_SETFCAP,
};

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
  int ambient;
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
  ambient = prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_IS_SET, CAP_SYS_ADMIN, 0,
                  0);
  if ((capabilities & (UINT64_C(1) << CAP_SYS_ADMIN)) != 0 ||
      ambient > 0) {
    snprintf(detail, detail_size,
             "the action starts with host CAP_SYS_ADMIN (effective or "
             "ambient); remove the capability before running unprivileged");
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

static int read_capability_sets(struct __user_cap_data_struct data[2]) {
  struct __user_cap_header_struct header = {
      .version = _LINUX_CAPABILITY_VERSION_3,
      .pid = 0,
  };

  if (syscall(SYS_capget, &header, data) < 0) {
    return -errno;
  }
  return 0;
}

static uint64_t required_capability_mask(void) {
  uint64_t mask = 0;
  size_t index;

  for (index = 0;
       index < sizeof(required_capabilities) / sizeof(required_capabilities[0]);
       ++index) {
    mask |= UINT64_C(1) << required_capabilities[index];
  }
  return mask;
}

static uint64_t capability_effective(
    const struct __user_cap_data_struct data[2]) {
  return (uint64_t)data[0].effective |
         ((uint64_t)data[1].effective << 32);
}

static uint64_t capability_permitted(
    const struct __user_cap_data_struct data[2]) {
  return (uint64_t)data[0].permitted |
         ((uint64_t)data[1].permitted << 32);
}

static uint64_t capability_inheritable(
    const struct __user_cap_data_struct data[2]) {
  return (uint64_t)data[0].inheritable |
         ((uint64_t)data[1].inheritable << 32);
}

static int capability_is_in_set(uint64_t capabilities, int capability) {
  return (capabilities & (UINT64_C(1) << capability)) != 0;
}

static int check_required_capability_sets(void) {
  struct __user_cap_data_struct data[2] = {};
  uint64_t required = required_capability_mask();
  uint64_t permitted;
  uint64_t effective;
  uint64_t inheritable;
  size_t index;

  if (read_capability_sets(data) < 0) {
    return -errno;
  }
  permitted = capability_permitted(data);
  effective = capability_effective(data);
  inheritable = capability_inheritable(data);
  if ((permitted & required) != required ||
      (effective & required) != required ||
      (inheritable & required) != required) {
    return -EPERM;
  }
  for (index = 0;
       index < sizeof(required_capabilities) / sizeof(required_capabilities[0]);
       ++index) {
    int capability = required_capabilities[index];
    int ambient = prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_IS_SET, capability, 0,
                        0);
    if (ambient <= 0) {
      return ambient < 0 ? -errno : -EPERM;
    }
    if (prctl(PR_CAPBSET_READ, capability, 0, 0, 0) <= 0) {
      return -EPERM;
    }
  }
  return 0;
}

static int configure_namespace_capabilities(void) {
  struct __user_cap_header_struct header = {
      .version = _LINUX_CAPABILITY_VERSION_3,
      .pid = 0,
  };
  struct __user_cap_data_struct data[2] = {};
  uint64_t required = required_capability_mask();
  long last_cap;
  int result;
  int capability;

  if (read_integer("/proc/sys/kernel/cap_last_cap", &last_cap) < 0 ||
      last_cap < CAP_SETFCAP) {
    return -EINVAL;
  }
  result = read_capability_sets(data);
  if (result < 0) {
    return result;
  }
  if ((capability_permitted(data) & required) != required) {
    return -EPERM;
  }
  for (capability = 0; capability <= last_cap; ++capability) {
    if (!capability_is_in_set(required, capability) &&
        prctl(PR_CAPBSET_DROP, capability, 0, 0, 0) < 0) {
      return -errno;
    }
  }
  data[0].effective = (uint32_t)required;
  data[1].effective = (uint32_t)(required >> 32);
  data[0].permitted = (uint32_t)required;
  data[1].permitted = (uint32_t)(required >> 32);
  data[0].inheritable = (uint32_t)required;
  data[1].inheritable = (uint32_t)(required >> 32);
  if (syscall(SYS_capset, &header, data) < 0) {
    return -errno;
  }
  for (capability = 0; capability <= last_cap; ++capability) {
    if (capability_is_in_set(required, capability) &&
        prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_RAISE, capability, 0, 0) < 0) {
      return -errno;
    }
  }
  return check_required_capability_sets();
}

static int check_capabilities_after_exec(void) {
  return check_required_capability_sets() == 0 ? 0 : 1;
}

static int check_capability_exec(void) {
  char *arguments[] = {"kernel-preflight", "--capability-check", NULL};
  pid_t child = fork();
  int status = 0;

  if (child < 0) {
    return -errno;
  }
  if (child == 0) {
    execve("/proc/self/exe", arguments, environ);
    _exit(127);
  }
  if (wait_for_child(child, &status) < 0) {
    return -errno;
  }
  return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : -EPERM;
}

static int open_tree_path(const char *path, bool recursive) {
  char parent[256];
  const char *name;
  const char *slash = strrchr(path, '/');
  if (slash == NULL) {
    return -EINVAL;
  }
  if (slash == path) {
    memcpy(parent, "/", 2);
  } else {
    size_t length = (size_t)(slash - path);
    if (length >= sizeof(parent)) {
      return -ENAMETOOLONG;
    }
    memcpy(parent, path, length);
    parent[length] = '\0';
  }
  name = slash[1] == '\0' ? "." : slash + 1;
  int parent_fd = open(parent, O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
  if (parent_fd < 0) {
    return -errno;
  }
  unsigned int flags = OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC;
  if (recursive) {
    flags |= AT_RECURSIVE;
  }
  int tree = syscall(SYS_open_tree, parent_fd, name, flags);
  int error = errno;
  close(parent_fd);
  return tree < 0 ? -error : tree;
}

static int check_fd_mount_api(void) {
  const char *source_directory = "fd-mount-api-source";
  const char *source_nested = "fd-mount-api-source/nested";
  const char *source_file = "fd-mount-api-source/file";
  const char *destination_directory = "fd-mount-api-destination";
  const char *destination_file = "fd-mount-api-destination/file";
  int source_tree = -1;
  int file_tree = -1;
  struct rules_mkosi_mount_attr attributes = {
      .attr_set = MOUNT_ATTR_RDONLY,
  };
  int result = -1;

  if (mkdir(source_directory, 0700) < 0 ||
      mkdir(source_nested, 0700) < 0 ||
      mkdir(destination_directory, 0700) < 0) {
    goto cleanup;
  }
  if (mount("tmpfs", source_nested, "tmpfs", 0, "mode=755") < 0) {
    goto cleanup;
  }
  int file = open(source_file, O_CREAT | O_WRONLY | O_CLOEXEC, 0600);
  if (file < 0 || close(file) < 0) {
    goto cleanup;
  }
  file = open(destination_file, O_CREAT | O_WRONLY | O_CLOEXEC, 0600);
  if (file < 0 || close(file) < 0) {
    goto cleanup;
  }

  source_tree = open_tree_path(source_directory, true);
  if (source_tree < 0 ||
      syscall(SYS_move_mount, source_tree, "", AT_FDCWD,
              destination_directory, MOVE_MOUNT_F_EMPTY_PATH) < 0) {
    goto cleanup;
  }
  close(source_tree);
  source_tree = -1;
  if (syscall(SYS_mount_setattr, AT_FDCWD, destination_directory, AT_RECURSIVE,
              &attributes, sizeof(attributes)) < 0) {
    goto cleanup;
  }

  file_tree = open_tree_path(source_file, false);
  if (file_tree < 0 ||
      syscall(SYS_move_mount, file_tree, "", AT_FDCWD, destination_file,
              MOVE_MOUNT_F_EMPTY_PATH) < 0) {
    goto cleanup;
  }
  close(file_tree);
  file_tree = -1;
  result = 0;

cleanup:
  if (file_tree >= 0) {
    close(file_tree);
  }
  if (source_tree >= 0) {
    close(source_tree);
  }
  umount2(destination_file, MNT_DETACH);
  umount2(destination_directory, MNT_DETACH);
  umount2(source_nested, MNT_DETACH);
  unlink(source_file);
  unlink(destination_file);
  rmdir(source_nested);
  rmdir(source_directory);
  rmdir(destination_directory);
  return result;
}

static int child_namespace_setup(int ready, int acknowledgement) {
  unsigned int result = 0;
  char signal = 'R';

  if (syscall(SYS_unshare, CLONE_NEWUSER) < 0) {
    return result;
  }
  result |= CHECK_USER_NAMESPACE;
  if (write_all(ready, &signal, 1) < 0) {
    return (int)result;
  }
  if (read(acknowledgement, &signal, 1) != 1 || signal != 'A') {
    return (int)result;
  }
  result |= CHECK_ID_MAPPING;
  if (setresgid(0, 0, 0) < 0 || setresuid(0, 0, 0) < 0 ||
      geteuid() != 0 || getegid() != 0) {
    return (int)result;
  }
  result |= CHECK_ROOT_TRANSITION;
  if (configure_namespace_capabilities() < 0) {
    return (int)result;
  }
  result |= CHECK_NAMESPACE_CAPABILITIES;
  if (check_capability_exec() < 0) {
    return (int)result;
  }
  result |= CHECK_CAPABILITY_EXEC;
  if (syscall(SYS_unshare, CLONE_NEWNS) < 0) {
    return (int)result;
  }
  result |= CHECK_MOUNT_NAMESPACE;
  if (mount("tmpfs", "/tmp", "tmpfs", 0, NULL) < 0) {
    return (int)result;
  }
  if (check_fd_mount_api() < 0) {
    return (int)result;
  }
  result |= CHECK_FD_MOUNT_API;
  if (chdir("/tmp") < 0) {
    return (int)result;
  }
  if (mkdir("newroot", 0700) < 0 || mkdir("oldroot", 0700) < 0) {
    return (int)result;
  }
  if (mount("newroot", "newroot", NULL, MS_BIND | MS_REC, NULL) < 0) {
    return (int)result;
  }
  if (syscall(SYS_pivot_root, ".", "oldroot") < 0) {
    return (int)result;
  }
  result |= CHECK_TMPFS_WORKSPACE;
  result |= CHECK_PIVOT_ROOT_WORKSPACE;
  if (mkdir("newroot/etc", 0755) < 0) {
    return (int)result;
  }
  if (mount("/oldroot/etc", "newroot/etc", NULL, MS_BIND | MS_REC, NULL) <
      0) {
    return (int)result;
  }
  result |= CHECK_BIND_MOUNT;
  if (chdir("newroot") < 0) {
    return (int)result;
  }
  if (syscall(SYS_pivot_root, ".", ".") < 0) {
    return (int)result;
  }
  result |= CHECK_PIVOT_ROOT;
  if (umount2(".", MNT_DETACH) < 0) {
    return (int)result;
  }
  result |= CHECK_OLD_ROOT_DETACH;
  return (int)result;
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
    _exit(child_result == (int)((1u << 12) - 1) ? 0 : 1);
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
  checks->user_namespace = (child_result & CHECK_USER_NAMESPACE) != 0;
  checks->id_mapping = (child_result & CHECK_ID_MAPPING) != 0;
  checks->root_transition = (child_result & CHECK_ROOT_TRANSITION) != 0;
  checks->namespace_capabilities =
      (child_result & CHECK_NAMESPACE_CAPABILITIES) != 0;
  checks->capability_exec = (child_result & CHECK_CAPABILITY_EXEC) != 0;
  checks->mount_namespace = (child_result & CHECK_MOUNT_NAMESPACE) != 0;
  checks->tmpfs_workspace = (child_result & CHECK_TMPFS_WORKSPACE) != 0;
  checks->pivot_root_workspace =
      (child_result & CHECK_PIVOT_ROOT_WORKSPACE) != 0;
  checks->bind_mount = (child_result & CHECK_BIND_MOUNT) != 0;
  checks->fd_mount_api = (child_result & CHECK_FD_MOUNT_API) != 0;
  checks->pivot_root = (child_result & CHECK_PIVOT_ROOT) != 0;
  checks->old_root_detach = (child_result & CHECK_OLD_ROOT_DETACH) != 0;
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
           "mkosi v27 capability bounding, permitted, inheritable, and "
           "ambient sets were established");
  } else {
    report(output, "FAIL", "namespace_capabilities",
           "could not establish mkosi v27 capability bounding, permitted, "
           "inheritable, and ambient sets");
    ++failures;
  }
  if (namespace_checks.capability_exec) {
    report(output, "PASS", "capability_exec",
           "required capabilities survived an execve transition");
  } else {
    report(output, "FAIL", "capability_exec",
           "required capabilities were lost across execve");
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
  if (namespace_checks.tmpfs_workspace) {
    report(output, "PASS", "tmpfs_workspace",
           "mkosi v27 mounted a tmpfs workspace and entered it");
  } else {
    report(output, "FAIL", "tmpfs_workspace",
           "tmpfs workspace setup failed; permit tmpfs mounts in the "
           "namespace");
    ++failures;
  }
  if (namespace_checks.pivot_root_workspace) {
    report(output, "PASS", "pivot_root_workspace",
           "mkosi v27 pivot_root entered the temporary workspace");
  } else {
    report(output, "FAIL", "pivot_root_workspace",
           "the temporary workspace could not become the namespace root");
    ++failures;
  }
  if (namespace_checks.bind_mount) {
    report(output, "PASS", "bind_mount",
           "a representative recursive bind from old root into new root "
           "succeeded");
  } else {
    report(output, "FAIL", "bind_mount",
           "a representative recursive bind from old root into new root "
           "failed");
    ++failures;
  }
  if (namespace_checks.fd_mount_api) {
    report(output, "PASS", "fd_mount_api",
           "open_tree(parent_fd, name), move_mount(MOVE_MOUNT_F_EMPTY_PATH), "
           "and recursive mount_setattr succeeded");
  } else {
    report(output, "FAIL", "fd_mount_api",
           "descriptor-only typed binds require Linux open_tree(parent_fd, "
           "name, OPEN_TREE_CLONE), move_mount(MOVE_MOUNT_F_EMPTY_PATH), and "
           "mount_setattr; upgrade the kernel or select a supported Linux "
           "runner");
    ++failures;
  }
  if (namespace_checks.pivot_root) {
    report(output, "PASS", "pivot_root",
           "final pivot_root(\".\", \".\") succeeded");
  } else {
    report(output, "FAIL", "pivot_root",
           "final pivot_root(\".\", \".\") failed; a private root is "
           "required");
    ++failures;
  }
  if (namespace_checks.old_root_detach) {
    report(output, "PASS", "old_root_detach",
           "final old-root mount was detached with MNT_DETACH");
  } else {
    report(output, "FAIL", "old_root_detach",
           "final old-root mount could not be detached");
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

int rules_mkosi_verify_namespace_capabilities(void) {
  return check_capabilities_after_exec();
}
