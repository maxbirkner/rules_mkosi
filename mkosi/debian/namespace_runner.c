/* Some toolchains already define _GNU_SOURCE on the command line. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <linux/sched.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include "mkosi/private/mount_api.h"
#include "mkosi/private/write_all.h"

#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
#define NORETURN __attribute__((noreturn))
#define PRINTF_FORMAT(format_index, first_argument)                            \
  __attribute__((format(printf, format_index, first_argument)))

#define OLD_ROOT_NAME ".namespace-oldroot"

enum { PATH_BUFFER_SIZE = 4096 };

/* Each typed mount is OPTION SOURCE DESTINATION DEVICE INODE TYPE. */
enum { FIRST_MOUNT_ARGUMENT = 7, TYPED_MOUNT_ARGUMENTS = 6 };

/*
 * Device and inode a bind source must still have when it is pinned. Without a
 * validated identity the path is inspected immediately before it is pinned.
 */
struct mount_identity {
  bool validated;
  unsigned long long device;
  unsigned long long inode;
};

static const struct mount_identity unknown_identity = {
    .validated = false,
    .device = 0,
    .inode = 0,
};

struct runner_layout {
  const char *root;
  const char *workspace;
  const char *outputs;
  const char *home;
  const char *loader;
  const char *tool;
};

struct runtime_filesystem {
  const char *source;
  const char *directory;
  const char *type;
  unsigned long flags;
  const char *data;
  const char *failure;
};

static const struct runtime_filesystem runtime_filesystems[] = {
    {"proc", "proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL,
     "cannot mount namespace /proc"},
    {"tmpfs", "tmp", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC, "mode=1777",
     "cannot mount namespace /tmp"},
    {"tmpfs", "dev", "tmpfs", MS_NOSUID, "mode=755",
     "cannot mount namespace /dev"},
};

static const char *const runtime_devices[] = {"null",   "zero",    "full",
                                              "random", "urandom", "tty"};

static const struct {
  const char *name;
  const char *value;
} runtime_environment[] = {
    {"PATH", "/usr/bin:/usr/sbin:/bin:/sbin"},
    {"HOME", "/root"},
    {"TMPDIR", "/tmp"},
    {"SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt"},
    {"PWD", "/workspace"},
};

NORETURN PRINTF_FORMAT(1, 2) static void fail(const char *format, ...) {
  va_list arguments;
  va_start(arguments, format);
  vfprintf(stderr, format, arguments);
  va_end(arguments);
  fputc('\n', stderr);
  exit(1);
}

NORETURN static void fail_errno(const char *message) {
  fail("%s: %s", message, strerror(errno));
}

PRINTF_FORMAT(4, 5)
static int format_or_fail(char *buffer, size_t size, const char *too_long,
                          const char *format, ...) {
  va_list arguments;
  va_start(arguments, format);
  int length = vsnprintf(buffer, size, format, arguments);
  va_end(arguments);
  if (length < 0 || (size_t)length >= size) {
    fail("%s", too_long);
  }
  return length;
}

static void reset_inherited_signals(void) {
  sigset_t empty;
  sigemptyset(&empty);
  sigprocmask(SIG_SETMASK, &empty, NULL);
  struct sigaction default_action;
  memset(&default_action, 0, sizeof(default_action));
  default_action.sa_handler = SIG_DFL;
  sigemptyset(&default_action.sa_mask);
  const int signals[] = {SIGHUP,  SIGINT,  SIGQUIT, SIGILL,  SIGABRT,
                         SIGFPE,  SIGSEGV, SIGTERM, SIGCHLD, SIGPIPE,
                         SIGALRM, SIGUSR1, SIGUSR2};
  for (size_t index = 0; index < ARRAY_SIZE(signals); ++index) {
    sigaction(signals[index], &default_action, NULL);
  }
}

static void write_child_mapping(pid_t child, const char *name,
                                unsigned long value) {
  char path[128];
  char mapping[64];
  format_or_fail(path, sizeof(path), "namespace mapping path is too long",
                 "/proc/%ld/%s_map", (long)child, name);
  int length =
      format_or_fail(mapping, sizeof(mapping), "namespace mapping is too long",
                     "0 %lu 1\n", value);
  int result = rules_mkosi_write_file(path, mapping, (size_t)length);
  if (result < 0) {
    fail("cannot write %s: %s", path, strerror(-result));
  }
}

static void deny_child_setgroups(pid_t child) {
  char path[128];
  format_or_fail(path, sizeof(path), "setgroups path is too long",
                 "/proc/%ld/setgroups", (long)child);
  int result = rules_mkosi_write_file(path, "deny\n", strlen("deny\n"));
  if (result < 0) {
    fail("cannot disable supplementary groups: %s", strerror(-result));
  }
}

static void read_byte(int file, char expected) {
  char value;
  ssize_t result;
  do {
    result = read(file, &value, 1);
  } while (result < 0 && errno == EINTR);
  if (result != 1 || value != expected) {
    fail("namespace identity mapping handshake failed");
  }
}

static void write_byte(int file, char value) {
  if (write(file, &value, 1) != 1) {
    fail("namespace identity mapping handshake failed: %s", strerror(errno));
  }
}

/* Returns the child's exit code, or 128 plus the signal that terminated it. */
static int wait_for_exit_status(pid_t child, const char *failure) {
  int status = 0;
  pid_t waited;
  do {
    waited = waitpid(child, &status, 0);
  } while (waited < 0 && errno == EINTR);
  if (waited < 0) {
    fail_errno(failure);
  }
  if (WIFEXITED(status)) {
    return WEXITSTATUS(status);
  }
  if (WIFSIGNALED(status)) {
    return 128 + WTERMSIG(status);
  }
  return 1;
}

/*
 * Drops supplementary groups while the caller may still do so, for example as
 * real root. An unprivileged caller cannot: Bazel's sandbox has already denied
 * setgroups, and no descendant user namespace may allow it again. The groups
 * then stay as unmapped IDs. They cannot own or receive files, and with the
 * host root detached they only apply to the explicitly mounted action paths,
 * which the Bazel server has already read with the same groups.
 */
static void drop_supplementary_groups_if_permitted(void) {
  int group_count = getgroups(0, NULL);
  if (group_count < 0) {
    fail_errno("cannot inspect supplementary groups");
  }
  if (group_count != 0 && setgroups(0, NULL) < 0 && errno != EPERM) {
    fail_errno("cannot drop supplementary groups");
  }
}

/*
 * Only a process outside the new user namespace may write its ID maps, so the
 * original process stays behind, maps the child, and then mirrors the child's
 * exit status.
 */
NORETURN static void map_child_identity_and_exit(pid_t child, int ready[2],
                                                 int acknowledgement[2],
                                                 uid_t uid, gid_t gid) {
  close(ready[1]);
  close(acknowledgement[0]);
  read_byte(ready[0], 'U');
  write_child_mapping(child, "uid", (unsigned long)uid);
  deny_child_setgroups(child);
  write_child_mapping(child, "gid", (unsigned long)gid);
  write_byte(acknowledgement[1], 'U');
  close(ready[0]);
  close(acknowledgement[1]);
  _exit(
      wait_for_exit_status(child, "cannot wait for namespace identity mapper"));
}

static void enter_mapped_user_namespace(int ready[2], int acknowledgement[2]) {
  close(ready[0]);
  close(acknowledgement[1]);
  if (unshare(CLONE_NEWUSER) < 0) {
    fail_errno("cannot establish a private user namespace");
  }
  write_byte(ready[1], 'U');
  read_byte(acknowledgement[0], 'U');
  if (setresgid(0, 0, 0) < 0 || setresuid(0, 0, 0) < 0) {
    fail_errno("cannot become namespace root");
  }
  close(ready[1]);
  close(acknowledgement[0]);
}

static void map_current_identity(uid_t uid, gid_t gid) {
  drop_supplementary_groups_if_permitted();
  int ready[2];
  int acknowledgement[2];
  if (pipe(ready) < 0 || pipe(acknowledgement) < 0) {
    fail_errno("cannot create namespace identity mapping pipes");
  }
  pid_t child = fork();
  if (child < 0) {
    fail_errno("cannot fork namespace identity mapper");
  }
  if (child > 0) {
    map_child_identity_and_exit(child, ready, acknowledgement, uid, gid);
  }
  enter_mapped_user_namespace(ready, acknowledgement);
}

/* A trailing slash makes the final component "." so it names the directory. */
static int split_parent_path(const char *path, char parent[PATH_BUFFER_SIZE],
                             const char **name) {
  const char *slash = strrchr(path, '/');
  if (slash == NULL) {
    errno = EINVAL;
    return -1;
  }
  if (slash == path) {
    memcpy(parent, "/", 2);
  } else {
    size_t length = (size_t)(slash - path);
    if (length >= PATH_BUFFER_SIZE) {
      errno = ENAMETOOLONG;
      return -1;
    }
    memcpy(parent, path, length);
    parent[length] = '\0';
  }
  *name = slash[1] == '\0' ? "." : slash + 1;
  return 0;
}

static int open_tree_path(const char *path, bool recursive) {
  char parent[PATH_BUFFER_SIZE];
  const char *name;
  if (split_parent_path(path, parent, &name) < 0) {
    return -1;
  }
  int parent_fd = open(parent, O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
  if (parent_fd < 0) {
    return -1;
  }
  unsigned int flags = OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC;
  if (recursive) {
    flags |= AT_RECURSIVE;
  }
  long tree = syscall(SYS_open_tree, parent_fd, name, flags);
  int error = errno;
  close(parent_fd);
  errno = error;
  /* open_tree returns a file descriptor or -1, both of which fit in int. */
  return (int)tree;
}

static struct mount_identity identity_of(const struct stat *status) {
  struct mount_identity identity = {
      .validated = true,
      .device = (unsigned long long)status->st_dev,
      .inode = (unsigned long long)status->st_ino,
  };
  return identity;
}

static bool has_identity(const struct stat *status,
                         struct mount_identity expected) {
  return (unsigned long long)status->st_dev == expected.device &&
         (unsigned long long)status->st_ino == expected.inode;
}

static int inspect_identity(const char *path, struct mount_identity *identity) {
  struct stat current;
  if (stat(path, &current) < 0) {
    return -1;
  }
  *identity = identity_of(&current);
  return 0;
}

/* Fails with EAGAIN when the pinned tree is not the expected object. */
static int verify_pinned_tree(int mount_tree, bool directory,
                              struct mount_identity expected) {
  struct stat actual;
  if (fstat(mount_tree, &actual) < 0) {
    return -1;
  }
  if (!has_identity(&actual, expected) ||
      S_ISDIR(actual.st_mode) != directory) {
    errno = EAGAIN;
    return -1;
  }
  return 0;
}

/*
 * Clones PATH into a detached mount and verifies that the clone still has the
 * expected identity and type, so a path swapped after validation is rejected.
 */
static int pin_mount_path(const char *path, bool directory,
                          struct mount_identity expected) {
  if (!expected.validated && inspect_identity(path, &expected) < 0) {
    return -1;
  }
  int mount_tree = open_tree_path(path, directory);
  if (mount_tree < 0) {
    return -1;
  }
  if (verify_pinned_tree(mount_tree, directory, expected) < 0) {
    int error = errno;
    close(mount_tree);
    errno = error;
    return -1;
  }
  return mount_tree;
}

static long set_detached_mount_readonly(int source_fd) {
  struct rules_mkosi_mount_attr attributes = {
      .attr_set = MOUNT_ATTR_RDONLY,
  };
  return syscall(SYS_mount_setattr, source_fd, "", AT_EMPTY_PATH | AT_RECURSIVE,
                 &attributes, sizeof(attributes));
}

static long attach_detached_mount(int source_fd, const char *destination) {
  return syscall(SYS_move_mount, source_fd, "", AT_FDCWD, destination,
                 MOVE_MOUNT_F_EMPTY_PATH);
}

static void verify_pinned_source(int source_fd, struct mount_identity expected,
                                 bool directory) {
  struct stat source_stat;
  if (fstat(source_fd, &source_stat) < 0) {
    fail_errno("cannot inspect pinned bind source");
  }
  if ((expected.validated && !has_identity(&source_stat, expected)) ||
      S_ISDIR(source_stat.st_mode) != directory) {
    fail("pinned bind source changed after validation");
  }
}

/*
 * The read-only attribute is applied to the detached tree before it is
 * attached, so the destination is never writable, not even briefly.
 */
static void bind_mount_fd(int source_fd, const char *destination, bool readonly,
                          struct mount_identity expected, bool directory) {
  verify_pinned_source(source_fd, expected, directory);
  if (readonly && set_detached_mount_readonly(source_fd) != 0) {
    fail("recursive read-only detached mount_setattr is required before "
         "attaching %s: %s",
         destination, strerror(errno));
  }
  if (attach_detached_mount(source_fd, destination) < 0) {
    fail("descriptor-only bind move_mount failed at %s: %s", destination,
         strerror(errno));
  }
}

static void pin_and_bind_path(const char *source, const char *destination,
                              bool readonly, struct mount_identity expected,
                              bool directory) {
  int source_fd = pin_mount_path(source, directory, expected);
  if (source_fd < 0) {
    fail("cannot pin bind source %s with open_tree(parent_fd, name, "
         "OPEN_TREE_CLONE): %s",
         source, strerror(errno));
  }
  bind_mount_fd(source_fd, destination, readonly, expected, directory);
  close(source_fd);
}

static void bind_mount_path(const char *source, const char *destination,
                            bool readonly) {
  struct stat source_stat;
  if (stat(source, &source_stat) < 0) {
    fail("cannot inspect bind source %s: %s", source, strerror(errno));
  }
  pin_and_bind_path(source, destination, readonly, unknown_identity,
                    S_ISDIR(source_stat.st_mode));
}

static void close_non_stdio_fds(void) {
  long configured_limit = sysconf(_SC_OPEN_MAX);
  long limit = configured_limit > 0 ? configured_limit : 1048576;
  for (int file = 3; file < limit; ++file) {
    int flags = fcntl(file, F_GETFD);
    if (flags < 0) {
      continue;
    }
    if (fcntl(file, F_SETFD, flags | FD_CLOEXEC) < 0 ||
        (fcntl(file, F_GETFD) & FD_CLOEXEC) == 0) {
      fail("cannot mark inherited descriptor close-on-exec: %d", file);
    }
    close(file);
  }
}

static void remount_bind(const char *target, bool readonly,
                         const char *failure) {
  unsigned long flags = MS_BIND | MS_REMOUNT;
  if (readonly) {
    flags |= MS_RDONLY;
  }
  if (mount(NULL, target, NULL, flags, NULL) < 0) {
    fail_errno(failure);
  }
}

/* Makes the extracted root its own mount point so pivot_root accepts it. */
static void mount_extracted_root(const char *root) {
  int root_tree = pin_mount_path(root, true, unknown_identity);
  if (root_tree < 0) {
    fail_errno("cannot clone extracted root mount");
  }
  if (attach_detached_mount(root_tree, root) < 0) {
    int error = errno;
    close(root_tree);
    fail("cannot mount extracted root: %s", strerror(error));
  }
  close(root_tree);
}

static void make_root_directory(const char *root, const char *name,
                                const char *failure) {
  char path[PATH_BUFFER_SIZE];
  format_or_fail(path, sizeof(path), "extracted root path is too long", "%s/%s",
                 root, name);
  if (mkdir(path, 0700) < 0 && errno != EEXIST) {
    fail_errno(failure);
  }
}

static void prepare_extracted_root(const char *root) {
  if (mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) < 0) {
    fail_errno("cannot make mount propagation private");
  }
  mount_extracted_root(root);
  make_root_directory(root, OLD_ROOT_NAME, "cannot prepare old root");
  remount_bind(root, true, "cannot make extracted root read-only");
}

/* Once the host root is detached, only the extracted root is left. */
static void enter_root(const char *root) {
  if (chdir(root) < 0) {
    fail_errno("cannot enter extracted root");
  }
  if (syscall(SYS_pivot_root, ".", OLD_ROOT_NAME) < 0) {
    fail_errno("cannot pivot into extracted root");
  }
  if (chdir("/") < 0) {
    fail_errno("cannot enter private root");
  }
  if (umount2("/" OLD_ROOT_NAME, MNT_DETACH) < 0) {
    fail_errno("cannot detach host root");
  }
  remount_bind("/", false, "cannot temporarily update private root");
  if (rmdir("/" OLD_ROOT_NAME) < 0) {
    fail_errno("cannot remove old root marker");
  }
  remount_bind("/", true, "cannot make private root read-only");
}

static void mount_runtime_filesystem(const char *root,
                                     const struct runtime_filesystem *fs) {
  char path[PATH_BUFFER_SIZE];
  format_or_fail(path, sizeof(path), "extracted root path is too long", "%s/%s",
                 root, fs->directory);
  if (mount(fs->source, path, fs->type, fs->flags, fs->data) < 0) {
    fail_errno(fs->failure);
  }
}

static void bind_runtime_device(const char *root, const char *device) {
  char path[PATH_BUFFER_SIZE];
  format_or_fail(path, sizeof(path), "extracted root path is too long",
                 "%s/dev/%s", root, device);
  int destination = open(path, O_WRONLY | O_CREAT | O_CLOEXEC, 0666);
  if (destination < 0) {
    fail("cannot prepare namespace device %s: %s", path, strerror(errno));
  }
  close(destination);
  char source[64];
  if (snprintf(source, sizeof(source), "/dev/%s", device) >=
          (int)sizeof(source) ||
      mount(source, path, NULL, MS_BIND, NULL) < 0) {
    fail("cannot bind namespace device %s: %s", source, strerror(errno));
  }
}

static void mount_runtime_filesystems(const char *root) {
  for (size_t index = 0; index < ARRAY_SIZE(runtime_filesystems); ++index) {
    mount_runtime_filesystem(root, &runtime_filesystems[index]);
  }
  for (size_t index = 0; index < ARRAY_SIZE(runtime_devices); ++index) {
    bind_runtime_device(root, runtime_devices[index]);
  }
}

static void bind_runtime_directory(const char *root, const char *source,
                                   const char *directory,
                                   const char *too_long) {
  char destination[PATH_BUFFER_SIZE];
  format_or_fail(destination, sizeof(destination), too_long, "%s/%s", root,
                 directory);
  bind_mount_path(source, destination, false);
}

static void bind_runtime_directories(const struct runner_layout *layout) {
  bind_runtime_directory(layout->root, layout->workspace, "workspace",
                         "workspace path is too long");
  bind_runtime_directory(layout->root, layout->outputs, "outputs",
                         "outputs path is too long");
  bind_runtime_directory(layout->root, layout->home, "root",
                         "home path is too long");
}

static bool parse_mount_mode(const char *option) {
  if (strcmp(option, "--ro-bind") == 0) {
    return true;
  }
  if (strcmp(option, "--rw-bind") == 0) {
    return false;
  }
  fail("unknown namespace mount option: %s", option);
}

static bool is_mount_type(const char *type) {
  return strcmp(type, "dir") == 0 || strcmp(type, "file") == 0;
}

/*
 * Accepts only a positive decimal number that fits the identity field. Signs,
 * whitespace, and zero are rejected: zero is never a valid device or inode.
 */
static bool parse_identity_number(const char *text, unsigned long long *value) {
  if (text[0] < '0' || text[0] > '9') {
    return false;
  }
  char *end;
  errno = 0;
  *value = strtoull(text, &end, 10);
  return errno == 0 && *end == '\0' && *value != 0;
}

/* A typed mount must carry a usable identity; it is never inspected late. */
static struct mount_identity parse_mount_identity(const char *device,
                                                  const char *inode) {
  struct mount_identity identity = {.validated = true};
  if (!parse_identity_number(device, &identity.device) ||
      !parse_identity_number(inode, &identity.inode)) {
    fail("namespace mount identity is invalid: device \"%s\" and inode "
         "\"%s\" must be positive decimal integers",
         device, inode);
  }
  return identity;
}

static void bind_typed_mount(int argc, char **argv, int index,
                             const char *root) {
  bool readonly = parse_mount_mode(argv[index]);
  if (index + 5 >= argc || argv[index + 1][0] != '/' ||
      argv[index + 2][0] != '/' || !is_mount_type(argv[index + 5])) {
    fail("namespace mount options require fd, destination, identity, and type");
  }
  char destination[PATH_BUFFER_SIZE];
  format_or_fail(destination, sizeof(destination),
                 "namespace mount destination is too long", "%s%s", root,
                 argv[index + 2]);
  struct mount_identity identity =
      parse_mount_identity(argv[index + 3], argv[index + 4]);
  bool directory = strcmp(argv[index + 5], "dir") == 0;
  pin_and_bind_path(argv[index + 1], destination, readonly, identity,
                    directory);
}

/* Returns the index of the "--" that separates mounts from tool arguments. */
static int bind_typed_mounts(int argc, char **argv, const char *root) {
  int index = FIRST_MOUNT_ARGUMENT;
  while (index < argc && strcmp(argv[index], "--") != 0) {
    bind_typed_mount(argc, argv, index, root);
    index += TYPED_MOUNT_ARGUMENTS;
  }
  if (index >= argc || strcmp(argv[index], "--") != 0) {
    fail("namespace runner command separator is missing");
  }
  return index;
}

static void set_runtime_environment(void) {
  for (size_t index = 0; index < ARRAY_SIZE(runtime_environment); ++index) {
    setenv(runtime_environment[index].name, runtime_environment[index].value,
           1);
  }
}

/*
 * The packaged loader is executed directly with an explicit library path, so
 * the tool resolves libraries only from the extracted tree.
 */
NORETURN static void exec_packaged_tool(const struct runner_layout *layout,
                                        size_t argument_count,
                                        char **arguments) {
  char **command = calloc(argument_count + 5, sizeof(char *));
  if (command == NULL) {
    fail("cannot allocate namespace command");
  }
  command[0] = (char *)layout->loader;
  command[1] = "--library-path";
  command[2] = "/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:"
               "/usr/lib/x86_64-linux-gnu/systemd:/usr/lib/systemd:/usr/lib64";
  command[3] = (char *)layout->tool;
  for (size_t argument = 0; argument < argument_count; ++argument) {
    command[argument + 4] = arguments[argument];
  }
  command[argument_count + 4] = NULL;
  execv(layout->loader, command);
  fail("cannot execute packaged loader %s: %s", layout->loader,
       strerror(errno));
}

/* Runs as PID 1 of the new PID namespace and never returns. */
NORETURN static void run_namespace_init(int argc, char **argv,
                                        const struct runner_layout *layout) {
  if (sethostname("mkosi-debian-tools", strlen("mkosi-debian-tools")) < 0 ||
      setdomainname("localdomain", strlen("localdomain")) < 0) {
    fail_errno("cannot set deterministic UTS identity");
  }
  prepare_extracted_root(layout->root);
  remount_bind(layout->root, false,
               "cannot prepare extracted root for typed mounts");
  bind_runtime_directories(layout);
  mount_runtime_filesystems(layout->root);
  int separator = bind_typed_mounts(argc, argv, layout->root);
  remount_bind(layout->root, true,
               "cannot make extracted root read-only after typed mounts");
  enter_root(layout->root);
  close_non_stdio_fds();
  if (chdir("/workspace") < 0) {
    fail_errno("cannot set namespace working directory");
  }
  set_runtime_environment();
  exec_packaged_tool(layout, (size_t)(argc - separator - 1),
                     argv + separator + 1);
}

static int run_child(int argc, char **argv, uid_t uid, gid_t gid) {
  const struct runner_layout layout = {
      .root = argv[1],
      .workspace = argv[2],
      .outputs = argv[3],
      .home = argv[4],
      .loader = argv[5],
      .tool = argv[6],
  };
  map_current_identity(uid, gid);
  if (unshare(CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWIPC | CLONE_NEWUTS) < 0) {
    fail_errno("cannot establish private execution namespaces");
  }
  pid_t child = fork();
  if (child < 0) {
    fail_errno("cannot enter PID namespace");
  }
  if (child > 0) {
    return wait_for_exit_status(
        child, "cannot synchronously wait for namespace child");
  }
  run_namespace_init(argc, argv, &layout);
}

static bool create_file_with_contents(const char *path, const char *contents) {
  int file = open(path, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (file < 0) {
    return false;
  }
  int result = rules_mkosi_write_all(file, contents, strlen(contents));
  close(file);
  return result == 0;
}

static bool create_empty_file(const char *path) {
  int file = open(path, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (file < 0) {
    return false;
  }
  close(file);
  return true;
}

static ssize_t read_file_prefix(const char *path, char *buffer, size_t size) {
  int file = open(path, O_RDONLY | O_CLOEXEC);
  ssize_t length = file < 0 ? -1 : read(file, buffer, size - 1);
  if (file >= 0) {
    close(file);
  }
  return length;
}

static bool has_contents(const char *buffer, ssize_t length,
                         const char *expected) {
  return length == (ssize_t)strlen(expected) &&
         memcmp(buffer, expected, (size_t)length) == 0;
}

static bool is_readonly_error(int error) {
  return error == EROFS || error == EPERM;
}

#define RO_TEST_BASE "namespace-runner-ro-test"
#define RO_TEST_SOURCE RO_TEST_BASE "/source"
#define RO_TEST_NESTED RO_TEST_SOURCE "/nested"
#define RO_TEST_DESTINATION RO_TEST_BASE "/destination"
#define RO_TEST_DESTINATION_NESTED RO_TEST_DESTINATION "/nested"
#define RO_TEST_SOURCE_MARKER RO_TEST_NESTED "/marker"
#define RO_TEST_DESTINATION_MARKER RO_TEST_DESTINATION_NESTED "/created"

/* The nested tmpfs checks that read-only applies to submounts as well. */
static bool prepare_recursive_readonly_fixture(void) {
  if (mkdir(RO_TEST_BASE, 0700) < 0 || mkdir(RO_TEST_SOURCE, 0700) < 0 ||
      mkdir(RO_TEST_NESTED, 0700) < 0 || mkdir(RO_TEST_DESTINATION, 0700) < 0) {
    return false;
  }
  if (unshare(CLONE_NEWNS) < 0 ||
      mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) < 0 ||
      mount("tmpfs", RO_TEST_NESTED, "tmpfs", 0, "mode=755") < 0) {
    return false;
  }
  return create_file_with_contents(RO_TEST_SOURCE_MARKER, "source\n");
}

static bool nested_bind_is_readonly(void) {
  int created =
      open(RO_TEST_DESTINATION_MARKER, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (created >= 0) {
    close(created);
    return false;
  }
  return is_readonly_error(errno) && access(RO_TEST_SOURCE_MARKER, R_OK) == 0;
}

static void remove_recursive_readonly_fixture(void) {
  umount2(RO_TEST_DESTINATION, MNT_DETACH);
  umount2(RO_TEST_NESTED, MNT_DETACH);
  unlink(RO_TEST_SOURCE_MARKER);
  rmdir(RO_TEST_DESTINATION_NESTED);
  rmdir(RO_TEST_DESTINATION);
  rmdir(RO_TEST_NESTED);
  rmdir(RO_TEST_SOURCE);
  rmdir(RO_TEST_BASE);
}

static int recursive_readonly_self_test(void) {
  uid_t uid = getuid();
  gid_t gid = getgid();
  map_current_identity(uid, gid);
  if (!prepare_recursive_readonly_fixture()) {
    return 1;
  }
  bind_mount_path(RO_TEST_SOURCE, RO_TEST_DESTINATION, true);
  if (!nested_bind_is_readonly()) {
    return 1;
  }
  remove_recursive_readonly_fixture();
  return 0;
}

#define SWAP_TEST_BASE "namespace-runner-fd-swap"
#define SWAP_TEST_DESTINATIONS SWAP_TEST_BASE "/destination"

/*
 * A scenario aborts on fixture errors; content mismatches are only recorded,
 * so the remaining scenarios still run and clean up before the test fails.
 */
enum scenario_result { SCENARIO_ABORTED, SCENARIO_FAILED, SCENARIO_PASSED };

static enum scenario_result scenario_result_of(bool passed) {
  return passed ? SCENARIO_PASSED : SCENARIO_FAILED;
}

/* Runs bind_mount_fd in a child because its failure path exits the process. */
static int bind_mount_fd_in_child(int source_fd, const char *destination,
                                  struct mount_identity identity,
                                  bool directory, int *status) {
  pid_t child = fork();
  if (child < 0) {
    return -1;
  }
  if (child == 0) {
    bind_mount_fd(source_fd, destination, false, identity, directory);
    _exit(0);
  }
  return waitpid(child, status, 0) < 0 ? -1 : 0;
}

static int pinned_identity(int pinned_fd, struct mount_identity *identity) {
  struct stat status;
  if (fstat(pinned_fd, &status) < 0) {
    return -1;
  }
  *identity = identity_of(&status);
  return 0;
}

#define SWAP_READONLY_SOURCE SWAP_TEST_BASE "/readonly-source"
#define SWAP_READONLY_DESTINATION SWAP_TEST_DESTINATIONS "/readonly"
#define SWAP_READONLY_REPLACEMENT SWAP_TEST_DESTINATIONS "/readonly-replacement"
#define SWAP_REPLACEMENT_CONTENTS "replacement\n"

/* Swaps the destination between mount_setattr and move_mount. */
static bool attach_readonly_after_destination_swap(int readonly_fd) {
  if (set_detached_mount_readonly(readonly_fd) < 0 ||
      rename(SWAP_READONLY_DESTINATION, SWAP_READONLY_REPLACEMENT) < 0 ||
      !create_empty_file(SWAP_READONLY_DESTINATION) ||
      attach_detached_mount(readonly_fd, SWAP_READONLY_DESTINATION) < 0) {
    close(readonly_fd);
    return false;
  }
  close(readonly_fd);
  return true;
}

static bool destination_is_readonly(const char *path) {
  int file = open(path, O_WRONLY | O_CLOEXEC);
  if (file >= 0) {
    close(file);
    return false;
  }
  return is_readonly_error(errno);
}

/* The renamed-away destination must still accept and keep a complete write. */
static bool replacement_stays_writable(void) {
  int file = open(SWAP_READONLY_REPLACEMENT, O_WRONLY | O_CLOEXEC);
  if (file < 0) {
    return false;
  }
  int result = rules_mkosi_write_all(file, SWAP_REPLACEMENT_CONTENTS,
                                     strlen(SWAP_REPLACEMENT_CONTENTS));
  close(file);
  char contents[16] = {0};
  ssize_t length =
      read_file_prefix(SWAP_READONLY_REPLACEMENT, contents, sizeof(contents));
  return result == 0 &&
         has_contents(contents, length, SWAP_REPLACEMENT_CONTENTS);
}

static bool readonly_bind_reached_only_new_destination(void) {
  return destination_is_readonly(SWAP_READONLY_DESTINATION) &&
         replacement_stays_writable();
}

static bool readonly_swap_scenario(void) {
  if (!create_file_with_contents(SWAP_READONLY_SOURCE, "readonly\n") ||
      !create_empty_file(SWAP_READONLY_DESTINATION)) {
    return false;
  }
  int readonly_fd =
      pin_mount_path(SWAP_READONLY_SOURCE, false, unknown_identity);
  if (readonly_fd < 0 || !attach_readonly_after_destination_swap(readonly_fd) ||
      !readonly_bind_reached_only_new_destination()) {
    return false;
  }
  umount2(SWAP_READONLY_DESTINATION, MNT_DETACH);
  unlink(SWAP_READONLY_DESTINATION);
  unlink(SWAP_READONLY_REPLACEMENT);
  unlink(SWAP_READONLY_SOURCE);
  return true;
}

#define SWAP_FILE_SOURCE SWAP_TEST_BASE "/source"
#define SWAP_FILE_REPLACEMENT SWAP_TEST_BASE "/replacement"
#define SWAP_FILE_DESTINATION SWAP_TEST_DESTINATIONS "/file"

static bool replace_file_source_after_pin(void) {
  return create_empty_file(SWAP_FILE_DESTINATION) &&
         rename(SWAP_FILE_SOURCE, SWAP_FILE_REPLACEMENT) == 0 &&
         create_file_with_contents(SWAP_FILE_SOURCE, "changed\n");
}

/* A file renamed away after pinning must still be the one that is mounted. */
static enum scenario_result file_swap_scenario(void) {
  if (!create_file_with_contents(SWAP_FILE_SOURCE, "original\n")) {
    return SCENARIO_ABORTED;
  }
  int source_fd = pin_mount_path(SWAP_FILE_SOURCE, false, unknown_identity);
  if (source_fd < 0) {
    return SCENARIO_ABORTED;
  }
  struct mount_identity identity;
  if (pinned_identity(source_fd, &identity) < 0) {
    close(source_fd);
    return SCENARIO_ABORTED;
  }
  int status = 0;
  if (!replace_file_source_after_pin() ||
      bind_mount_fd_in_child(source_fd, SWAP_FILE_DESTINATION, identity, false,
                             &status) < 0) {
    return SCENARIO_ABORTED;
  }
  bool mounted = WIFEXITED(status) && WEXITSTATUS(status) == 0;
  char contents[16] = {0};
  ssize_t length = mounted ? read_file_prefix(SWAP_FILE_DESTINATION, contents,
                                              sizeof(contents))
                           : -1;
  if (mounted) {
    umount2(SWAP_FILE_DESTINATION, MNT_DETACH);
  }
  close(source_fd);
  unlink(SWAP_FILE_DESTINATION);
  unlink(SWAP_FILE_SOURCE);
  unlink(SWAP_FILE_REPLACEMENT);
  return scenario_result_of(mounted &&
                            has_contents(contents, length, "original\n"));
}

#define SWAP_DIRECTORY_SOURCE SWAP_TEST_BASE "/directory-source"
#define SWAP_DIRECTORY_REPLACEMENT SWAP_TEST_BASE "/directory-replacement"
#define SWAP_DIRECTORY_MARKER SWAP_DIRECTORY_SOURCE "/marker"
#define SWAP_DIRECTORY_REPLACEMENT_MARKER SWAP_DIRECTORY_REPLACEMENT "/marker"
#define SWAP_DIRECTORY_DESTINATION SWAP_TEST_DESTINATIONS "/directory"
#define SWAP_DIRECTORY_DESTINATION_MARKER SWAP_DIRECTORY_DESTINATION "/marker"

static bool directory_bind_onto_file_is_rejected(
    int directory_fd, struct mount_identity identity) {
  if (mkdir(SWAP_DIRECTORY_DESTINATION, 0700) < 0 ||
      !create_empty_file(SWAP_FILE_DESTINATION)) {
    return false;
  }
  int status = 0;
  if (bind_mount_fd_in_child(directory_fd, SWAP_FILE_DESTINATION, identity,
                             true, &status) < 0 ||
      !WIFEXITED(status) || WEXITSTATUS(status) == 0) {
    return false;
  }
  unlink(SWAP_FILE_DESTINATION);
  return true;
}

static void remove_directory_swap_fixture(int directory_fd) {
  umount2(SWAP_DIRECTORY_DESTINATION, MNT_DETACH);
  close(directory_fd);
  rmdir(SWAP_DIRECTORY_DESTINATION);
  rmdir(SWAP_DIRECTORY_SOURCE);
  unlink(SWAP_DIRECTORY_REPLACEMENT_MARKER);
  rmdir(SWAP_DIRECTORY_REPLACEMENT);
}

/*
 * A pinned directory must be rejected as a file bind, and must stay mounted
 * after its source path is replaced.
 */
static enum scenario_result directory_swap_scenario(void) {
  if (mkdir(SWAP_DIRECTORY_SOURCE, 0700) < 0 ||
      !create_file_with_contents(SWAP_DIRECTORY_MARKER, "directory\n")) {
    return SCENARIO_ABORTED;
  }
  int directory_fd =
      pin_mount_path(SWAP_DIRECTORY_SOURCE, true, unknown_identity);
  struct mount_identity identity;
  if (directory_fd < 0 || pinned_identity(directory_fd, &identity) < 0 ||
      !directory_bind_onto_file_is_rejected(directory_fd, identity)) {
    return SCENARIO_ABORTED;
  }
  bind_mount_fd(directory_fd, SWAP_DIRECTORY_DESTINATION, false, identity,
                true);
  if (rename(SWAP_DIRECTORY_SOURCE, SWAP_DIRECTORY_REPLACEMENT) < 0 ||
      mkdir(SWAP_DIRECTORY_SOURCE, 0700) < 0) {
    return SCENARIO_ABORTED;
  }
  char contents[20] = {0};
  ssize_t length = read_file_prefix(SWAP_DIRECTORY_DESTINATION_MARKER, contents,
                                    sizeof(contents));
  remove_directory_swap_fixture(directory_fd);
  return scenario_result_of(has_contents(contents, length, "directory\n"));
}

#define SWAP_ANCESTOR SWAP_TEST_BASE "/ancestor"
#define SWAP_ANCESTOR_SOURCE SWAP_ANCESTOR "/source"
#define SWAP_ANCESTOR_REPLACEMENT SWAP_TEST_BASE "/ancestor-replacement"
#define SWAP_ANCESTOR_REPLACEMENT_SOURCE SWAP_ANCESTOR_REPLACEMENT "/source"
#define SWAP_ANCESTOR_DESTINATION SWAP_TEST_DESTINATIONS "/ancestor"

/* Replacing an ancestor directory after pinning must not redirect the bind. */
static enum scenario_result ancestor_swap_scenario(void) {
  if (mkdir(SWAP_ANCESTOR, 0700) < 0 ||
      !create_file_with_contents(SWAP_ANCESTOR_SOURCE, "ancestor\n")) {
    return SCENARIO_ABORTED;
  }
  int ancestor_fd =
      pin_mount_path(SWAP_ANCESTOR_SOURCE, false, unknown_identity);
  struct mount_identity identity;
  if (ancestor_fd < 0 || pinned_identity(ancestor_fd, &identity) < 0 ||
      !create_empty_file(SWAP_ANCESTOR_DESTINATION) ||
      rename(SWAP_ANCESTOR, SWAP_ANCESTOR_REPLACEMENT) < 0 ||
      mkdir(SWAP_ANCESTOR, 0700) < 0) {
    return SCENARIO_ABORTED;
  }
  bind_mount_fd(ancestor_fd, SWAP_ANCESTOR_DESTINATION, false, identity, false);
  char contents[16] = {0};
  ssize_t length =
      read_file_prefix(SWAP_ANCESTOR_DESTINATION, contents, sizeof(contents));
  umount2(SWAP_ANCESTOR_DESTINATION, MNT_DETACH);
  close(ancestor_fd);
  unlink(SWAP_ANCESTOR_DESTINATION);
  rmdir(SWAP_ANCESTOR);
  unlink(SWAP_ANCESTOR_REPLACEMENT_SOURCE);
  rmdir(SWAP_ANCESTOR_REPLACEMENT);
  return scenario_result_of(has_contents(contents, length, "ancestor\n"));
}

static bool prepare_fd_swap_fixture(void) {
  if (unshare(CLONE_NEWNS) < 0 ||
      mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) < 0) {
    return false;
  }
  return mkdir(SWAP_TEST_BASE, 0700) == 0 &&
         mkdir(SWAP_TEST_DESTINATIONS, 0700) == 0 &&
         mount("tmpfs", SWAP_TEST_DESTINATIONS, "tmpfs", 0, "mode=755") == 0;
}

/* Fails unless every scenario removed everything it created. */
static bool remove_fd_swap_fixture(void) {
  umount2(SWAP_TEST_DESTINATIONS, MNT_DETACH);
  rmdir(SWAP_TEST_DESTINATIONS);
  return rmdir(SWAP_TEST_BASE) == 0;
}

static int fd_swap_self_test(void) {
  map_current_identity(getuid(), getgid());
  if (!prepare_fd_swap_fixture() || !readonly_swap_scenario()) {
    return 1;
  }
  enum scenario_result file = file_swap_scenario();
  if (file == SCENARIO_ABORTED) {
    return 1;
  }
  enum scenario_result directory = directory_swap_scenario();
  if (directory == SCENARIO_ABORTED) {
    return 1;
  }
  enum scenario_result ancestor = ancestor_swap_scenario();
  if (ancestor == SCENARIO_ABORTED) {
    return 1;
  }
  return remove_fd_swap_fixture() && file == SCENARIO_PASSED &&
                 directory == SCENARIO_PASSED && ancestor == SCENARIO_PASSED
             ? 0
             : 1;
}

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--self-test-recursive-ro") == 0) {
    return recursive_readonly_self_test();
  }
  if (argc == 2 && strcmp(argv[1], "--self-test-fd-swap") == 0) {
    return fd_swap_self_test();
  }
  if (argc < 8) {
    fprintf(stderr,
            "usage: namespace_runner ROOT WORKSPACE OUTPUTS HOME LOADER TOOL "
            "[mounts...] -- [args...]\n");
    return 2;
  }
  uid_t uid = getuid();
  gid_t gid = getgid();
  reset_inherited_signals();
  return run_child(argc, argv, uid, gid);
}
