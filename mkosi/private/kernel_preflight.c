/* Some toolchains already define _GNU_SOURCE on the command line. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

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

#include "mkosi/private/mount_api.h"
#include "mkosi/private/write_all.h"

extern char **environ;

#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
#define PRINTF_FORMAT(format_index, first_argument)                            \
  __attribute__((format(printf, format_index, first_argument)))

typedef struct {
  rules_mkosi_fd_mount_operation operation;
  int error;
} fd_mount_probe_result;

typedef struct {
  unsigned int checks;
  fd_mount_probe_result fd_mount;
} namespace_setup_result;

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
  CHECK_ALL = (1u << 12) - 1,
};

static const int required_capabilities[] = {
    CAP_CHOWN,      CAP_DAC_OVERRIDE, CAP_DAC_READ_SEARCH, CAP_FOWNER,
    CAP_FSETID,     CAP_SETGID,       CAP_SETUID,          CAP_SETPCAP,
    CAP_SYS_CHROOT, CAP_SYS_PTRACE,   CAP_SYS_ADMIN,       CAP_SYS_RESOURCE,
    CAP_SETFCAP,
};

PRINTF_FORMAT(4, 5)
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

/* Reads at most size - 1 bytes and NUL-terminates them. */
static int read_text_file(const char *path, char *buffer, size_t size) {
  ssize_t bytes_read;
  int file;

  file = open(path, O_RDONLY | O_CLOEXEC);
  if (file < 0) {
    return -errno;
  }
  bytes_read = read(file, buffer, size - 1);
  if (bytes_read < 0) {
    int error = errno;
    close(file);
    return -error;
  }
  close(file);
  buffer[bytes_read] = '\0';
  return 0;
}

static int read_integer(const char *path, long *value) {
  char buffer[128];
  char *end;
  int result = read_text_file(path, buffer, sizeof(buffer));

  if (result < 0) {
    return result;
  }
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

static int parse_unsigned(char **cursor, unsigned long *value) {
  char *end;

  *value = strtoul(*cursor, &end, 10);
  if (errno != 0 || end == *cursor) {
    return -EINVAL;
  }
  *cursor = end;
  return 0;
}

/* Parses the first "inside outside length" line of a uid_map or gid_map. */
static int read_mapping(const char *path, unsigned long *inside,
                        unsigned long *outside, unsigned long *length) {
  char buffer[128];
  char *cursor = buffer;
  int result = read_text_file(path, buffer, sizeof(buffer));

  if (result < 0) {
    return result;
  }
  errno = 0;
  if (parse_unsigned(&cursor, inside) < 0 ||
      parse_unsigned(&cursor, outside) < 0 ||
      parse_unsigned(&cursor, length) < 0) {
    return -EINVAL;
  }
  return 0;
}

#define CAPABILITY_FIELD "CapEff:"

static int parse_capability_field(const char *line, uint64_t *capabilities) {
  const char *value = line + strlen(CAPABILITY_FIELD);
  char *end;

  errno = 0;
  *capabilities = strtoull(value, &end, 16);
  if (errno != 0) {
    return -errno;
  }
  return end == value ? -EINVAL : 0;
}

/* Scans whole lines, because long fields such as Groups precede CapEff. */
int rules_mkosi_read_effective_capabilities(const char *status_path,
                                            uint64_t *capabilities) {
  FILE *status = fopen(status_path, "re");
  char *line = NULL;
  size_t line_size = 0;
  int result = -EINVAL;

  if (status == NULL) {
    return -errno;
  }
  while (getline(&line, &line_size, status) >= 0) {
    if (strncmp(line, CAPABILITY_FIELD, strlen(CAPABILITY_FIELD)) == 0) {
      result = parse_capability_field(line, capabilities);
      break;
    }
  }
  if (result == -EINVAL && ferror(status)) {
    result = -EIO;
  }
  free(line);
  fclose(status);
  return result;
}

static bool starts_as_host_root(unsigned long outside_uid) {
  return outside_uid == 0 && (geteuid() == 0 || getegid() == 0);
}

static bool has_host_sys_admin(uint64_t effective_capabilities) {
  int ambient =
      prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_IS_SET, CAP_SYS_ADMIN, 0, 0);

  return (effective_capabilities & (UINT64_C(1) << CAP_SYS_ADMIN)) != 0 ||
         ambient > 0;
}

/*
 * The action must start unprivileged: an unknown privilege state is treated
 * as privileged, so every probe failure refuses to qualify the host.
 */
static int check_initial_privilege(char *detail, size_t detail_size,
                                   void *context) {
  unsigned long inside = 0;
  unsigned long outside = 0;
  unsigned long length = 0;
  uint64_t capabilities = 0;
  (void)context;

  if (read_mapping("/proc/self/uid_map", &inside, &outside, &length) < 0 ||
      length == 0) {
    snprintf(detail, detail_size,
             "cannot establish the starting UID mapping; refuse to qualify "
             "an unknown privilege state");
    return 0;
  }
  if (rules_mkosi_read_effective_capabilities("/proc/self/status",
                                              &capabilities) < 0) {
    snprintf(detail, detail_size,
             "cannot inspect CapEff; refuse to qualify an unknown privilege "
             "state");
    return 0;
  }
  if (starts_as_host_root(outside)) {
    snprintf(detail, detail_size,
             "the action starts as host root (uid=%ld gid=%ld); run it as an "
             "unprivileged identity",
             (long)geteuid(), (long)getegid());
    return 0;
  }
  if (has_host_sys_admin(capabilities)) {
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

static int write_mapping(pid_t child, const char *name, unsigned long value) {
  char path[128];
  char mapping[64];
  int length;

  length = snprintf(path, sizeof(path), "/proc/%ld/%s_map", (long)child, name);
  if (length < 0 || (size_t)length >= sizeof(path)) {
    return -ENAMETOOLONG;
  }
  length = snprintf(mapping, sizeof(mapping), "0 %lu 1\n", value);
  if (length < 0 || (size_t)length >= sizeof(mapping)) {
    return -EINVAL;
  }
  return rules_mkosi_write_file(path, mapping, (size_t)length);
}

static int deny_setgroups(pid_t child) {
  char path[128];
  int length;

  length = snprintf(path, sizeof(path), "/proc/%ld/setgroups", (long)child);
  if (length < 0 || (size_t)length >= sizeof(path)) {
    return -ENAMETOOLONG;
  }
  return rules_mkosi_write_file(path, "deny\n", strlen("deny\n"));
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

  for (index = 0; index < ARRAY_SIZE(required_capabilities); ++index) {
    mask |= UINT64_C(1) << required_capabilities[index];
  }
  return mask;
}

static uint64_t combine_capability_words(uint32_t low, uint32_t high) {
  return (uint64_t)low | ((uint64_t)high << 32);
}

static int capability_is_in_set(uint64_t capabilities, int capability) {
  return (capabilities & (UINT64_C(1) << capability)) != 0;
}

static bool contains_all(uint64_t capabilities, uint64_t required) {
  return (capabilities & required) == required;
}

static int check_required_ambient_and_bounding(void) {
  size_t index;

  for (index = 0; index < ARRAY_SIZE(required_capabilities); ++index) {
    int capability = required_capabilities[index];
    int ambient =
        prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_IS_SET, capability, 0, 0);
    if (ambient <= 0) {
      return ambient < 0 ? -errno : -EPERM;
    }
    if (prctl(PR_CAPBSET_READ, capability, 0, 0, 0) <= 0) {
      return -EPERM;
    }
  }
  return 0;
}

static int check_required_capability_sets(void) {
  struct __user_cap_data_struct data[2] = {};
  uint64_t required = required_capability_mask();

  if (read_capability_sets(data) < 0) {
    return -errno;
  }
  if (!contains_all(
          combine_capability_words(data[0].permitted, data[1].permitted),
          required) ||
      !contains_all(
          combine_capability_words(data[0].effective, data[1].effective),
          required) ||
      !contains_all(
          combine_capability_words(data[0].inheritable, data[1].inheritable),
          required)) {
    return -EPERM;
  }
  return check_required_ambient_and_bounding();
}

static int drop_unrequired_bounding_capabilities(long last_cap,
                                                 uint64_t required) {
  int capability;

  for (capability = 0; capability <= last_cap; ++capability) {
    if (!capability_is_in_set(required, capability) &&
        prctl(PR_CAPBSET_DROP, capability, 0, 0, 0) < 0) {
      return -errno;
    }
  }
  return 0;
}

static int set_capability_sets(uint64_t capabilities) {
  struct __user_cap_header_struct header = {
      .version = _LINUX_CAPABILITY_VERSION_3,
      .pid = 0,
  };
  struct __user_cap_data_struct data[2] = {};
  size_t word;

  for (word = 0; word < ARRAY_SIZE(data); ++word) {
    uint32_t bits = (uint32_t)(capabilities >> (32 * word));
    data[word].effective = bits;
    data[word].permitted = bits;
    data[word].inheritable = bits;
  }
  if (syscall(SYS_capset, &header, data) < 0) {
    return -errno;
  }
  return 0;
}

static int raise_ambient_capabilities(long last_cap, uint64_t required) {
  int capability;

  for (capability = 0; capability <= last_cap; ++capability) {
    if (capability_is_in_set(required, capability) &&
        prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_RAISE, capability, 0, 0) < 0) {
      return -errno;
    }
  }
  return 0;
}

/*
 * Mirrors the capability state mkosi v27 establishes in its namespace: exactly
 * the required capabilities in the bounding, effective, permitted,
 * inheritable, and ambient sets.
 */
static int configure_namespace_capabilities(void) {
  struct __user_cap_data_struct data[2] = {};
  uint64_t required = required_capability_mask();
  long last_cap;
  int result;

  if (read_integer("/proc/sys/kernel/cap_last_cap", &last_cap) < 0 ||
      last_cap < CAP_SETFCAP) {
    return -EINVAL;
  }
  result = read_capability_sets(data);
  if (result < 0) {
    return result;
  }
  if (!contains_all(
          combine_capability_words(data[0].permitted, data[1].permitted),
          required)) {
    return -EPERM;
  }
  result = drop_unrequired_bounding_capabilities(last_cap, required);
  if (result < 0) {
    return result;
  }
  result = set_capability_sets(required);
  if (result < 0) {
    return result;
  }
  result = raise_ambient_capabilities(last_cap, required);
  if (result < 0) {
    return result;
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

/* A trailing slash makes the final component "." so it names the directory. */
static int split_parent_path(const char *path, char *parent, size_t parent_size,
                             const char **name) {
  const char *slash = strrchr(path, '/');

  if (slash == NULL) {
    memcpy(parent, ".", 2);
    *name = path;
    return 0;
  }
  if (slash == path) {
    memcpy(parent, "/", 2);
  } else {
    size_t length = (size_t)(slash - path);
    if (length >= parent_size) {
      return -ENAMETOOLONG;
    }
    memcpy(parent, path, length);
    parent[length] = '\0';
  }
  *name = slash[1] == '\0' ? "." : slash + 1;
  return 0;
}

static int open_tree_path(const char *path, bool recursive) {
  char parent[256];
  const char *name;
  int result = split_parent_path(path, parent, sizeof(parent), &name);

  if (result < 0) {
    return result;
  }
  int parent_fd = open(parent, O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
  if (parent_fd < 0) {
    return -errno;
  }
  unsigned int flags = OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC;
  if (recursive) {
    flags |= AT_RECURSIVE;
  }
  long tree = syscall(SYS_open_tree, parent_fd, name, flags);
  int error = errno;
  close(parent_fd);
  /* open_tree returns a file descriptor or -1, both of which fit in int. */
  return tree < 0 ? -error : (int)tree;
}

static void record_fd_mount_failure(fd_mount_probe_result *probe,
                                    rules_mkosi_fd_mount_operation operation,
                                    int error) {
  probe->operation = operation;
  probe->error = error > 0 ? error : EIO;
}

#define FD_MOUNT_SOURCE_DIRECTORY "fd-mount-api-source"
#define FD_MOUNT_SOURCE_NESTED FD_MOUNT_SOURCE_DIRECTORY "/nested"
#define FD_MOUNT_SOURCE_FILE FD_MOUNT_SOURCE_DIRECTORY "/file"
#define FD_MOUNT_DESTINATION_DIRECTORY "fd-mount-api-destination"
#define FD_MOUNT_DESTINATION_FILE FD_MOUNT_DESTINATION_DIRECTORY "/file"

/* One detached-fd bind as performed by the namespace runner. */
typedef struct {
  const char *source;
  const char *destination;
  bool directory;
  bool readonly;
  rules_mkosi_fd_mount_operation open_tree_operation;
  rules_mkosi_fd_mount_operation fstat_operation;
  rules_mkosi_fd_mount_operation move_mount_operation;
} fd_mount_step;

static const fd_mount_step fd_mount_steps[] = {
    {FD_MOUNT_SOURCE_DIRECTORY, FD_MOUNT_DESTINATION_DIRECTORY, true, true,
     RULES_MKOSI_FD_MOUNT_OP_OPEN_TREE_DIRECTORY,
     RULES_MKOSI_FD_MOUNT_OP_FSTAT_DIRECTORY,
     RULES_MKOSI_FD_MOUNT_OP_MOVE_MOUNT_DIRECTORY},
    {FD_MOUNT_SOURCE_FILE, FD_MOUNT_DESTINATION_FILE, false, false,
     RULES_MKOSI_FD_MOUNT_OP_OPEN_TREE_FILE, RULES_MKOSI_FD_MOUNT_OP_FSTAT_FILE,
     RULES_MKOSI_FD_MOUNT_OP_MOVE_MOUNT_FILE},
};

static int create_empty_file(const char *path) {
  int file = open(path, O_CREAT | O_WRONLY | O_CLOEXEC, 0600);

  return file < 0 || close(file) < 0 ? -1 : 0;
}

/* The nested tmpfs makes the directory bind exercise a recursive clone. */
static int create_fd_mount_fixture(struct stat expected[]) {
  size_t index;

  if (mkdir(FD_MOUNT_SOURCE_DIRECTORY, 0700) < 0 ||
      mkdir(FD_MOUNT_SOURCE_NESTED, 0700) < 0 ||
      mkdir(FD_MOUNT_DESTINATION_DIRECTORY, 0700) < 0) {
    return -1;
  }
  if (mount("tmpfs", FD_MOUNT_SOURCE_NESTED, "tmpfs", 0, "mode=755") < 0) {
    return -1;
  }
  if (create_empty_file(FD_MOUNT_SOURCE_FILE) < 0 ||
      create_empty_file(FD_MOUNT_DESTINATION_FILE) < 0) {
    return -1;
  }
  for (index = 0; index < ARRAY_SIZE(fd_mount_steps); ++index) {
    if (stat(fd_mount_steps[index].source, &expected[index]) < 0) {
      return -1;
    }
  }
  return 0;
}

static void remove_fd_mount_fixture(void) {
  umount2(FD_MOUNT_DESTINATION_FILE, MNT_DETACH);
  umount2(FD_MOUNT_DESTINATION_DIRECTORY, MNT_DETACH);
  umount2(FD_MOUNT_SOURCE_NESTED, MNT_DETACH);
  unlink(FD_MOUNT_SOURCE_FILE);
  unlink(FD_MOUNT_DESTINATION_FILE);
  rmdir(FD_MOUNT_SOURCE_NESTED);
  rmdir(FD_MOUNT_SOURCE_DIRECTORY);
  rmdir(FD_MOUNT_DESTINATION_DIRECTORY);
}

static int attach_validated_tree(int tree, const fd_mount_step *step,
                                 const struct stat *expected,
                                 fd_mount_probe_result *probe) {
  struct rules_mkosi_mount_attr attributes = {
      .attr_set = MOUNT_ATTR_RDONLY,
  };
  struct stat actual;

  if (fstat(tree, &actual) < 0) {
    record_fd_mount_failure(probe, step->fstat_operation, errno);
    return -1;
  }
  if (actual.st_dev != expected->st_dev || actual.st_ino != expected->st_ino ||
      S_ISDIR(actual.st_mode) != step->directory) {
    record_fd_mount_failure(probe, step->fstat_operation, EAGAIN);
    return -1;
  }
  if (step->readonly &&
      syscall(SYS_mount_setattr, tree, "", AT_EMPTY_PATH | AT_RECURSIVE,
              &attributes, sizeof(attributes)) < 0) {
    record_fd_mount_failure(probe, RULES_MKOSI_FD_MOUNT_OP_MOUNT_SETATTR,
                            errno);
    return -1;
  }
  if (syscall(SYS_move_mount, tree, "", AT_FDCWD, step->destination,
              MOVE_MOUNT_F_EMPTY_PATH) < 0) {
    record_fd_mount_failure(probe, step->move_mount_operation, errno);
    return -1;
  }
  return 0;
}

static int probe_fd_mount_step(const fd_mount_step *step,
                               const struct stat *expected,
                               fd_mount_probe_result *probe) {
  int tree = open_tree_path(step->source, step->directory);
  int result;

  if (tree < 0) {
    record_fd_mount_failure(probe, step->open_tree_operation, -tree);
    return -1;
  }
  result = attach_validated_tree(tree, step, expected, probe);
  close(tree);
  return result;
}

/* Exercises the exact detached-fd mount sequence the namespace runner uses. */
static int check_fd_mount_api(fd_mount_probe_result *probe) {
  struct stat expected[ARRAY_SIZE(fd_mount_steps)];
  int result = -1;
  size_t index;

  probe->operation = RULES_MKOSI_FD_MOUNT_OP_NONE;
  probe->error = 0;
  if (create_fd_mount_fixture(expected) < 0) {
    record_fd_mount_failure(probe, RULES_MKOSI_FD_MOUNT_OP_SETUP, errno);
  } else {
    for (index = 0; index < ARRAY_SIZE(fd_mount_steps); ++index) {
      if (probe_fd_mount_step(&fd_mount_steps[index], &expected[index], probe) <
          0) {
        break;
      }
    }
    result = index == ARRAY_SIZE(fd_mount_steps) ? 0 : -1;
  }
  remove_fd_mount_fixture();
  return result;
}

typedef struct {
  int ready;
  int acknowledgement;
  fd_mount_probe_result *fd_mount;
} child_setup_context;

typedef struct {
  int (*run)(const child_setup_context *context);
  unsigned int passed_checks;
} child_setup_step;

static int unshare_user_namespace(const child_setup_context *context) {
  (void)context;
  return syscall(SYS_unshare, CLONE_NEWUSER) < 0 ? -1 : 0;
}

static int await_identity_mapping(const child_setup_context *context) {
  char signal = 'R';

  if (rules_mkosi_write_all(context->ready, &signal, 1) < 0) {
    return -1;
  }
  return read(context->acknowledgement, &signal, 1) != 1 || signal != 'A' ? -1
                                                                          : 0;
}

static int become_namespace_root(const child_setup_context *context) {
  (void)context;
  return setresgid(0, 0, 0) < 0 || setresuid(0, 0, 0) < 0 || geteuid() != 0 ||
                 getegid() != 0
             ? -1
             : 0;
}

static int establish_namespace_capabilities(
    const child_setup_context *context) {
  (void)context;
  return configure_namespace_capabilities() < 0 ? -1 : 0;
}

static int verify_capabilities_survive_exec(
    const child_setup_context *context) {
  (void)context;
  return check_capability_exec() < 0 ? -1 : 0;
}

static int unshare_mount_namespace(const child_setup_context *context) {
  (void)context;
  return syscall(SYS_unshare, CLONE_NEWNS) < 0 ? -1 : 0;
}

static int mount_scratch_tmpfs(const child_setup_context *context) {
  (void)context;
  return mount("tmpfs", "/tmp", "tmpfs", 0, NULL) < 0 ? -1 : 0;
}

static int probe_fd_mount_api(const child_setup_context *context) {
  return check_fd_mount_api(context->fd_mount);
}

static int pivot_into_tmpfs_workspace(const child_setup_context *context) {
  (void)context;
  if (chdir("/tmp") < 0) {
    return -1;
  }
  if (mkdir("newroot", 0700) < 0 || mkdir("oldroot", 0700) < 0) {
    return -1;
  }
  if (mount("newroot", "newroot", NULL, MS_BIND | MS_REC, NULL) < 0) {
    return -1;
  }
  return syscall(SYS_pivot_root, ".", "oldroot") < 0 ? -1 : 0;
}

static int bind_from_old_root(const child_setup_context *context) {
  (void)context;
  if (mkdir("newroot/etc", 0755) < 0) {
    return -1;
  }
  return mount("/oldroot/etc", "newroot/etc", NULL, MS_BIND | MS_REC, NULL) < 0
             ? -1
             : 0;
}

static int pivot_into_new_root(const child_setup_context *context) {
  (void)context;
  if (chdir("newroot") < 0) {
    return -1;
  }
  return syscall(SYS_pivot_root, ".", ".") < 0 ? -1 : 0;
}

static int detach_old_root(const child_setup_context *context) {
  (void)context;
  return umount2(".", MNT_DETACH) < 0 ? -1 : 0;
}

/* Ordered like mkosi v27's sandbox setup; each step depends on the previous. */
static const child_setup_step child_setup_steps[] = {
    {unshare_user_namespace, CHECK_USER_NAMESPACE},
    {await_identity_mapping, CHECK_ID_MAPPING},
    {become_namespace_root, CHECK_ROOT_TRANSITION},
    {establish_namespace_capabilities, CHECK_NAMESPACE_CAPABILITIES},
    {verify_capabilities_survive_exec, CHECK_CAPABILITY_EXEC},
    {unshare_mount_namespace, CHECK_MOUNT_NAMESPACE},
    {mount_scratch_tmpfs, 0},
    {probe_fd_mount_api, CHECK_FD_MOUNT_API},
    {pivot_into_tmpfs_workspace,
     CHECK_TMPFS_WORKSPACE | CHECK_PIVOT_ROOT_WORKSPACE},
    {bind_from_old_root, CHECK_BIND_MOUNT},
    {pivot_into_new_root, CHECK_PIVOT_ROOT},
    {detach_old_root, CHECK_OLD_ROOT_DETACH},
};

static unsigned int child_namespace_setup(const child_setup_context *context) {
  unsigned int checks = 0;
  size_t index;

  for (index = 0; index < ARRAY_SIZE(child_setup_steps); ++index) {
    if (child_setup_steps[index].run(context) < 0) {
      break;
    }
    checks |= child_setup_steps[index].passed_checks;
  }
  return checks;
}

static void run_setup_child_and_exit(int ready, int acknowledgement,
                                     int result_file) {
  namespace_setup_result result = {};
  child_setup_context context = {
      .ready = ready,
      .acknowledgement = acknowledgement,
      .fd_mount = &result.fd_mount,
  };

  result.checks = child_namespace_setup(&context);
  (void)rules_mkosi_write_all(result_file, &result, sizeof(result));
  _exit(result.checks == CHECK_ALL ? 0 : 1);
}

/*
 * Only a process outside the child's new user namespace may write its maps;
 * the child learns through the acknowledgement byte whether they were written.
 */
static void map_setup_child_identity(pid_t child, int ready,
                                     int acknowledgement) {
  char signal;
  unsigned long uid;
  unsigned long gid;

  if (read(ready, &signal, 1) != 1 || signal != 'R') {
    return;
  }
  uid = (unsigned long)getuid();
  gid = (unsigned long)getgid();
  if (deny_setgroups(child) == 0 && write_mapping(child, "gid", gid) == 0 &&
      write_mapping(child, "uid", uid) == 0) {
    signal = 'A';
  } else {
    signal = 'F';
  }
  (void)rules_mkosi_write_all(acknowledgement, &signal, 1);
}

static void receive_setup_result(int result_file,
                                 namespace_setup_result *result) {
  if (read(result_file, result, sizeof(*result)) != (ssize_t)sizeof(*result)) {
    memset(result, 0, sizeof(*result));
  }
  close(result_file);
}

static int has_check(const namespace_setup_result *result, unsigned int check) {
  return (result->checks & check) != 0;
}

static void copy_namespace_checks(rules_mkosi_namespace_checks *checks,
                                  const namespace_setup_result *result) {
  checks->user_namespace = has_check(result, CHECK_USER_NAMESPACE);
  checks->id_mapping = has_check(result, CHECK_ID_MAPPING);
  checks->root_transition = has_check(result, CHECK_ROOT_TRANSITION);
  checks->namespace_capabilities =
      has_check(result, CHECK_NAMESPACE_CAPABILITIES);
  checks->capability_exec = has_check(result, CHECK_CAPABILITY_EXEC);
  checks->mount_namespace = has_check(result, CHECK_MOUNT_NAMESPACE);
  checks->tmpfs_workspace = has_check(result, CHECK_TMPFS_WORKSPACE);
  checks->pivot_root_workspace = has_check(result, CHECK_PIVOT_ROOT_WORKSPACE);
  checks->bind_mount = has_check(result, CHECK_BIND_MOUNT);
  checks->fd_mount_api = has_check(result, CHECK_FD_MOUNT_API);
  checks->fd_mount_operation = result->fd_mount.operation;
  checks->fd_mount_errno = result->fd_mount.error;
  checks->pivot_root = has_check(result, CHECK_PIVOT_ROOT);
  checks->old_root_detach = has_check(result, CHECK_OLD_ROOT_DETACH);
}

enum { READY_PIPE, ACKNOWLEDGEMENT_PIPE, RESULT_PIPE, SETUP_PIPE_COUNT };

static void close_pipes(int pipes[][2], size_t count) {
  size_t index;

  for (index = 0; index < count; ++index) {
    close(pipes[index][0]);
    close(pipes[index][1]);
  }
}

static int open_pipes(int pipes[][2], size_t count) {
  size_t index;

  for (index = 0; index < count; ++index) {
    if (pipe(pipes[index]) < 0) {
      close_pipes(pipes, index);
      return -1;
    }
  }
  return 0;
}

/*
 * The process is made dumpable first: a non-dumpable child's /proc entries are
 * owned by root, so the parent could not write the child's ID maps.
 */
static int actual_namespace_setup(rules_mkosi_namespace_checks *checks,
                                  void *context) {
  int pipes[SETUP_PIPE_COUNT][2];
  namespace_setup_result child_result = {};
  pid_t child;
  (void)context;

  if (prctl(PR_SET_DUMPABLE, 1) < 0 ||
      open_pipes(pipes, SETUP_PIPE_COUNT) < 0) {
    return 0;
  }
  child = fork();
  if (child < 0) {
    close_pipes(pipes, SETUP_PIPE_COUNT);
    return 0;
  }
  if (child == 0) {
    close(pipes[READY_PIPE][0]);
    close(pipes[ACKNOWLEDGEMENT_PIPE][1]);
    close(pipes[RESULT_PIPE][0]);
    run_setup_child_and_exit(pipes[READY_PIPE][1],
                             pipes[ACKNOWLEDGEMENT_PIPE][0],
                             pipes[RESULT_PIPE][1]);
  }
  close(pipes[READY_PIPE][1]);
  close(pipes[ACKNOWLEDGEMENT_PIPE][0]);
  close(pipes[RESULT_PIPE][1]);
  map_setup_child_identity(child, pipes[READY_PIPE][0],
                           pipes[ACKNOWLEDGEMENT_PIPE][1]);
  close(pipes[READY_PIPE][0]);
  close(pipes[ACKNOWLEDGEMENT_PIPE][1]);
  receive_setup_result(pipes[RESULT_PIPE][0], &child_result);
  (void)wait_for_child(child, NULL);
  copy_namespace_checks(checks, &child_result);
  return 1;
}

static int check_max_user_namespaces(FILE *output, const char *path) {
  long value;
  int result = read_integer(path, &value);

  if (result < 0) {
    report(output, "FAIL", "user.max_user_namespaces",
           "cannot read %s (%s); mount procfs and set the value above zero",
           path, strerror(-result));
    return 1;
  }
  if (value <= 0) {
    report(output, "FAIL", "user.max_user_namespaces",
           "%ld; set /proc/sys/user/max_user_namespaces above zero", value);
    return 1;
  }
  report(output, "PASS", "user.max_user_namespaces", "%ld (> 0)", value);
  return 0;
}

static int check_unprivileged_userns_clone(FILE *output, const char *path) {
  long value;
  int result = read_integer(path, &value);

  if (result == -ENOENT) {
    report(output, "PASS", "kernel.unprivileged_userns_clone",
           "not exposed by this kernel; the clone probe is authoritative");
    return 0;
  }
  if (result < 0) {
    report(output, "FAIL", "kernel.unprivileged_userns_clone",
           "cannot read %s (%s); allow unprivileged user namespaces", path,
           strerror(-result));
    return 1;
  }
  if (value <= 0) {
    report(output, "FAIL", "kernel.unprivileged_userns_clone",
           "%ld; set /proc/sys/kernel/unprivileged_userns_clone to 1", value);
    return 1;
  }
  report(output, "PASS", "kernel.unprivileged_userns_clone", "%ld", value);
  return 0;
}

static int check_sysctl(FILE *output, const char *proc_root) {
  char path[256];
  int failures;

  if (!proc_path(path, sizeof(path), proc_root,
                 "sys/user/max_user_namespaces")) {
    report(output, "FAIL", "user.max_user_namespaces",
           "the procfs path is too long");
    return 1;
  }
  failures = check_max_user_namespaces(output, path);
  if (!proc_path(path, sizeof(path), proc_root,
                 "sys/kernel/unprivileged_userns_clone")) {
    report(output, "FAIL", "kernel.unprivileged_userns_clone",
           "the procfs path is too long");
    return failures + 1;
  }
  return failures + check_unprivileged_userns_clone(output, path);
}

static const char *fd_mount_operation_name(
    rules_mkosi_fd_mount_operation operation) {
  switch (operation) {
    case RULES_MKOSI_FD_MOUNT_OP_SETUP:
      return "fixture/setup";
    case RULES_MKOSI_FD_MOUNT_OP_OPEN_TREE_DIRECTORY:
      return "open_tree(directory)";
    case RULES_MKOSI_FD_MOUNT_OP_FSTAT_DIRECTORY:
      return "fstat(directory)";
    case RULES_MKOSI_FD_MOUNT_OP_MOUNT_SETATTR:
      return "mount_setattr(detached_fd)";
    case RULES_MKOSI_FD_MOUNT_OP_MOVE_MOUNT_DIRECTORY:
      return "move_mount(directory)";
    case RULES_MKOSI_FD_MOUNT_OP_OPEN_TREE_FILE:
      return "open_tree(file)";
    case RULES_MKOSI_FD_MOUNT_OP_FSTAT_FILE:
      return "fstat(file)";
    case RULES_MKOSI_FD_MOUNT_OP_MOVE_MOUNT_FILE:
      return "move_mount(file)";
    case RULES_MKOSI_FD_MOUNT_OP_NONE:
    default:
      return "unknown";
  }
}

static void report_fd_mount_failure(
    FILE *output, const rules_mkosi_namespace_checks *checks) {
  const char *operation = fd_mount_operation_name(checks->fd_mount_operation);
  int error = checks->fd_mount_errno;

  if (checks->fd_mount_operation == RULES_MKOSI_FD_MOUNT_OP_NONE ||
      error <= 0) {
    report(output, "FAIL", "fd_mount_api",
           "unexpected probe/setup failure did not preserve an operation and "
           "errno from the detached-fd sequence");
  } else if (checks->fd_mount_operation == RULES_MKOSI_FD_MOUNT_OP_SETUP) {
    report(output, "FAIL", "fd_mount_api",
           "fixture/setup error: %s failed with errno %d (%s)", operation,
           error, strerror(error));
  } else if (error == ENOSYS || error == EINVAL) {
    report(output, "FAIL", "fd_mount_api",
           "kernel compatibility: %s failed with errno %d (%s); required "
           "API or flags are unavailable; upgrade the kernel or select a "
           "supported Linux runner",
           operation, error, strerror(error));
  } else if (error == EPERM || error == EACCES) {
    report(output, "FAIL", "fd_mount_api",
           "seccomp/LSM/policy restriction: %s failed with errno %d (%s); "
           "permit the detached-fd mount API in the action environment",
           operation, error, strerror(error));
  } else {
    report(output, "FAIL", "fd_mount_api",
           "unexpected fd-mount probe error: %s failed with errno %d (%s)",
           operation, error, strerror(error));
  }
}

typedef struct {
  size_t offset;
  const char *name;
  const char *pass_detail;
  /* NULL selects the classified fd-mount failure report. */
  const char *fail_detail;
} namespace_check_report;

#define NAMESPACE_CHECK(field)                                                 \
  offsetof(rules_mkosi_namespace_checks, field), #field

static const namespace_check_report namespace_check_reports[] = {
    {NAMESPACE_CHECK(user_namespace),
     "CLONE_NEWUSER succeeded for an unprivileged child",
     "CLONE_NEWUSER failed; enable unprivileged user namespaces"},
    {NAMESPACE_CHECK(id_mapping),
     "setgroups=deny, uid_map, and gid_map completed",
     "setgroups=deny and UID/GID maps failed; allow the parent to write "
     "/proc/<pid>/{setgroups,uid_map,gid_map}"},
    {NAMESPACE_CHECK(root_transition),
     "mapped identity became uid=0,gid=0 inside the user namespace",
     "could not transition to mapped root inside the user namespace"},
    {NAMESPACE_CHECK(namespace_capabilities),
     "mkosi v27 capability bounding, permitted, inheritable, and ambient sets "
     "were established",
     "could not establish mkosi v27 capability bounding, permitted, "
     "inheritable, and ambient sets"},
    {NAMESPACE_CHECK(capability_exec),
     "required capabilities survived an execve transition",
     "required capabilities were lost across execve"},
    {NAMESPACE_CHECK(mount_namespace),
     "CLONE_NEWNS succeeded after the user namespace transition",
     "CLONE_NEWNS failed after the user namespace transition"},
    {NAMESPACE_CHECK(tmpfs_workspace),
     "mkosi v27 mounted a tmpfs workspace and entered it",
     "tmpfs workspace setup failed; permit tmpfs mounts in the namespace"},
    {NAMESPACE_CHECK(pivot_root_workspace),
     "mkosi v27 pivot_root entered the temporary workspace",
     "the temporary workspace could not become the namespace root"},
    {NAMESPACE_CHECK(bind_mount),
     "a representative recursive bind from old root into new root succeeded",
     "a representative recursive bind from old root into new root failed"},
    {NAMESPACE_CHECK(fd_mount_api),
     "open_tree(parent_fd, name, OPEN_TREE_CLONE), fstat validation, "
     "detached-fd recursive mount_setattr(AT_EMPTY_PATH), and "
     "move_mount(MOVE_MOUNT_F_EMPTY_PATH) succeeded",
     NULL},
    {NAMESPACE_CHECK(pivot_root), "final pivot_root(\".\", \".\") succeeded",
     "final pivot_root(\".\", \".\") failed; a private root is required"},
    {NAMESPACE_CHECK(old_root_detach),
     "final old-root mount was detached with MNT_DETACH",
     "final old-root mount could not be detached"},
};

#undef NAMESPACE_CHECK

static int namespace_check_passed(const rules_mkosi_namespace_checks *checks,
                                  size_t offset) {
  int passed;

  memcpy(&passed, (const char *)checks + offset, sizeof(passed));
  return passed;
}

static int report_namespace_checks(FILE *output,
                                   const rules_mkosi_namespace_checks *checks) {
  int failures = 0;
  size_t index;

  for (index = 0; index < ARRAY_SIZE(namespace_check_reports); ++index) {
    const namespace_check_report *check = &namespace_check_reports[index];
    if (namespace_check_passed(checks, check->offset)) {
      report(output, "PASS", check->name, "%s", check->pass_detail);
      continue;
    }
    if (check->fail_detail == NULL) {
      report_fd_mount_failure(output, checks);
    } else {
      report(output, "FAIL", check->name, "%s", check->fail_detail);
    }
    ++failures;
  }
  return failures;
}

static int read_kernel_identity(const rules_mkosi_kernel_preflight_ops *ops,
                                struct utsname *kernel) {
  if (ops->read_kernel_identity != NULL) {
    return ops->read_kernel_identity(kernel, ops->context);
  }
  return uname(kernel);
}

static int check_linux_kernel(FILE *output,
                              const rules_mkosi_kernel_preflight_ops *ops) {
  struct utsname kernel;

  if (read_kernel_identity(ops, &kernel) < 0) {
    report(output, "FAIL", "linux_kernel",
           "mkosi actions require a Linux kernel (%s)", strerror(errno));
    return 1;
  }
  if (strcmp(kernel.sysname, "Linux") != 0) {
    report(output, "FAIL", "linux_kernel",
           "mkosi actions require a Linux kernel (%s)", kernel.sysname);
    return 1;
  }
  report(output, "PASS", "linux_kernel", "%s %s", kernel.sysname,
         kernel.release);
  return 0;
}

static int check_procfs_namespaces(FILE *output, const char *proc_root) {
  static const char *const handles[] = {"self/ns/user", "self/ns/mnt"};
  struct stat proc_stat;
  char path[256];
  size_t index;

  for (index = 0; index < ARRAY_SIZE(handles); ++index) {
    if (!proc_path(path, sizeof(path), proc_root, handles[index])) {
      report(output, "FAIL", "procfs_namespaces",
             "the procfs path is too long");
      return 1;
    }
    if (stat(path, &proc_stat) < 0) {
      report(output, "FAIL", "procfs_namespaces",
             "cannot inspect %s (%s); mount procfs in the action environment",
             path, strerror(errno));
      return 1;
    }
  }
  report(output, "PASS", "procfs_namespaces",
         "user and mount namespace handles are available");
  return 0;
}

/* An injected check may leave DETAIL unwritten or unterminated. */
static int check_privilege(FILE *output,
                           const rules_mkosi_kernel_preflight_ops *ops) {
  char detail[256] = "";
  int passed =
      ops->check_initial_privilege != NULL &&
      ops->check_initial_privilege(detail, sizeof(detail), ops->context);

  detail[sizeof(detail) - 1] = '\0';
  if (!passed) {
    report(output, "FAIL", "initial_privilege", "%s",
           detail[0] == '\0' ? "privilege check failed" : detail);
    return 1;
  }
  report(output, "PASS", "initial_privilege", "%s", detail);
  return 0;
}

static int check_namespace_setup(FILE *output,
                                 const rules_mkosi_kernel_preflight_ops *ops) {
  rules_mkosi_namespace_checks namespace_checks = {};
  int failures = 0;

  if (ops->run_namespace_setup == NULL ||
      !ops->run_namespace_setup(&namespace_checks, ops->context)) {
    report(output, "FAIL", "namespace_setup",
           "the namespace setup operation could not be started");
    ++failures;
  }
  return failures + report_namespace_checks(output, &namespace_checks);
}

int rules_mkosi_kernel_preflight_with_ops(
    const char *proc_root, FILE *output,
    const rules_mkosi_kernel_preflight_ops *ops) {
  rules_mkosi_kernel_preflight_ops actual_ops = {
      .check_initial_privilege = check_initial_privilege,
      .run_namespace_setup = actual_namespace_setup,
      .context = NULL,
  };
  int failures = 0;

  if (ops == NULL) {
    ops = &actual_ops;
  }
  failures += check_linux_kernel(output, ops);
  failures += check_procfs_namespaces(output, proc_root);
  failures += check_privilege(output, ops);
  failures += check_sysctl(output, proc_root);
  failures += check_namespace_setup(output, ops);
  if (failures == 0) {
    report(output, "RESULT", "kernel_contract", "PASS (all checks passed)");
  } else {
    report(output, "RESULT", "kernel_contract", "FAIL (%d check%s failed)",
           failures, failures == 1 ? "" : "s");
  }
  return failures == 0 ? 0 : 1;
}

int rules_mkosi_kernel_preflight(const char *proc_root, FILE *output) {
  return rules_mkosi_kernel_preflight_with_ops(proc_root, output, NULL);
}

int rules_mkosi_verify_namespace_capabilities(void) {
  return check_capabilities_after_exec();
}
