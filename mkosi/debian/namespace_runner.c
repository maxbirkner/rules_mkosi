#define _GNU_SOURCE

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

struct mkosi_mount_attr {
  unsigned long long attr_set;
  unsigned long long attr_clr;
  unsigned long long propagation;
  unsigned long long userns_fd;
};

static void fail(const char *format, ...) {
  va_list arguments;
  va_start(arguments, format);
  vfprintf(stderr, format, arguments);
  va_end(arguments);
  fputc('\n', stderr);
  exit(1);
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
  for (size_t index = 0; index < sizeof(signals) / sizeof(signals[0]); ++index) {
    sigaction(signals[index], &default_action, NULL);
  }
}

static void write_child_mapping(pid_t child, const char *name,
                                unsigned long value) {
  char path[128];
  char mapping[64];
  int length = snprintf(path, sizeof(path), "/proc/%ld/%s_map", (long)child,
                        name);
  if (length < 0 || (size_t)length >= sizeof(path)) {
    fail("namespace mapping path is too long");
  }
  length = snprintf(mapping, sizeof(mapping), "0 %lu 1\n", value);
  if (length < 0 || (size_t)length >= sizeof(mapping)) {
    fail("namespace mapping is too long");
  }
  int file = open(path, O_WRONLY | O_CLOEXEC);
  if (file < 0 || write(file, mapping, (size_t)length) != length) {
    if (file >= 0) {
      close(file);
    }
    fail("cannot write %s: %s", path, strerror(errno));
  }
  close(file);
}

static void deny_child_setgroups(pid_t child) {
  char path[128];
  int length = snprintf(path, sizeof(path), "/proc/%ld/setgroups", (long)child);
  if (length < 0 || (size_t)length >= sizeof(path)) {
    fail("setgroups path is too long");
  }
  int file = open(path, O_WRONLY | O_CLOEXEC);
  if (file < 0 || write(file, "deny\n", 5) != 5) {
    if (file >= 0) {
      close(file);
    }
    fail("cannot disable supplementary groups: %s", strerror(errno));
  }
  close(file);
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

static void map_current_identity(uid_t uid, gid_t gid) {
  int group_count = getgroups(0, NULL);
  if (group_count < 0) {
    fail("cannot inspect supplementary groups: %s", strerror(errno));
  }
  if (group_count != 0) {
    if (setgroups(0, NULL) < 0 || getgroups(0, NULL) != 0) {
      fail("cannot clear supplementary groups before user namespace setup: %s",
           strerror(errno));
    }
  }
  int ready[2];
  int acknowledgement[2];
  if (pipe(ready) < 0 || pipe(acknowledgement) < 0) {
    fail("cannot create namespace identity mapping pipes: %s", strerror(errno));
  }
  pid_t child = fork();
  if (child < 0) {
    fail("cannot fork namespace identity mapper: %s", strerror(errno));
  }
  if (child > 0) {
    close(ready[1]);
    close(acknowledgement[0]);
    read_byte(ready[0], 'U');
    write_child_mapping(child, "uid", (unsigned long)uid);
    write_byte(acknowledgement[1], 'U');
    read_byte(ready[0], 'G');
    deny_child_setgroups(child);
    write_child_mapping(child, "gid", (unsigned long)gid);
    write_byte(acknowledgement[1], 'G');
    close(ready[0]);
    close(acknowledgement[1]);
    int status = 0;
    pid_t waited;
    do {
      waited = waitpid(child, &status, 0);
    } while (waited < 0 && errno == EINTR);
    if (waited < 0) {
      fail("cannot wait for namespace identity mapper: %s", strerror(errno));
    }
    if (WIFEXITED(status)) {
      _exit(WEXITSTATUS(status));
    }
    if (WIFSIGNALED(status)) {
      _exit(128 + WTERMSIG(status));
    }
    _exit(1);
  }
  close(ready[0]);
  close(acknowledgement[1]);
  if (unshare(CLONE_NEWUSER) < 0) {
    fail("cannot establish a private user namespace: %s", strerror(errno));
  }
  write_byte(ready[1], 'U');
  read_byte(acknowledgement[0], 'U');
  if (getgroups(0, NULL) != 0) {
    fail("supplementary groups were inherited into the user namespace");
  }
  write_byte(ready[1], 'G');
  read_byte(acknowledgement[0], 'G');
  if (setresgid(0, 0, 0) < 0 || setresuid(0, 0, 0) < 0) {
    fail("cannot become namespace root: %s", strerror(errno));
  }
  close(ready[1]);
  close(acknowledgement[0]);
}

static int open_tree_path(const char *path, bool recursive) {
  char parent[4096];
  const char *name;
  const char *slash = strrchr(path, '/');
  if (slash == NULL) {
    errno = EINVAL;
    return -1;
  }
  if (slash == path) {
    memcpy(parent, "/", 2);
  } else {
    size_t length = (size_t)(slash - path);
    if (length >= sizeof(parent)) {
      errno = ENAMETOOLONG;
      return -1;
    }
    memcpy(parent, path, length);
    parent[length] = '\0';
  }
  name = slash[1] == '\0' ? "." : slash + 1;
  int parent_fd = open(parent, O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
  if (parent_fd < 0) {
    return -1;
  }
  unsigned int flags = OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC;
  if (recursive) {
    flags |= AT_RECURSIVE;
  }
  int tree = syscall(SYS_open_tree, parent_fd, name, flags);
  int error = errno;
  close(parent_fd);
  errno = error;
  return tree;
}

static int pin_mount_path(const char *path, bool directory,
                          unsigned long long expected_device,
                          unsigned long long expected_inode) {
  struct stat expected;
  if (expected_device == 0) {
    if (stat(path, &expected) < 0) {
      return -1;
    }
    expected_device = (unsigned long long)expected.st_dev;
    expected_inode = (unsigned long long)expected.st_ino;
  }
  int mount_tree = open_tree_path(path, directory);
  if (mount_tree < 0) {
    return -1;
  }
  struct stat actual;
  if (fstat(mount_tree, &actual) < 0 ||
      (unsigned long long)actual.st_dev != expected_device ||
      (unsigned long long)actual.st_ino != expected_inode ||
      S_ISDIR(actual.st_mode) != directory) {
    int error = errno == 0 ? EAGAIN : errno;
    close(mount_tree);
    errno = error;
    return -1;
  }
  return mount_tree;
}

static void bind_mount_fd(int source_fd, const char *destination,
                          bool readonly, unsigned long long expected_device,
                          unsigned long long expected_inode, bool directory) {
  struct stat source_stat;
  if (fstat(source_fd, &source_stat) < 0) {
    fail("cannot inspect pinned bind source: %s", strerror(errno));
  }
  if ((expected_device != 0 &&
       ((unsigned long long)source_stat.st_dev != expected_device ||
        (unsigned long long)source_stat.st_ino != expected_inode)) ||
      S_ISDIR(source_stat.st_mode) != directory) {
    fail("pinned bind source changed after validation");
  }
  if (expected_device == 0) {
    expected_device = (unsigned long long)source_stat.st_dev;
    expected_inode = (unsigned long long)source_stat.st_ino;
  }
  if (syscall(SYS_move_mount, source_fd, "", AT_FDCWD, destination,
              MOVE_MOUNT_F_EMPTY_PATH) < 0) {
    int error = errno;
    fail("descriptor-only bind move_mount failed at %s: %s", destination,
         strerror(error));
  }
  if (readonly) {
    struct mkosi_mount_attr attributes = {
        .attr_set = MOUNT_ATTR_RDONLY,
    };
    if (syscall(SYS_mount_setattr, AT_FDCWD, destination, AT_RECURSIVE,
                &attributes, sizeof(attributes)) != 0) {
      fail("recursive read-only mount_setattr is required at %s: %s",
           destination, strerror(errno));
    }
  }
  struct stat mounted_stat;
  if (expected_device != 0 &&
      (stat(destination, &mounted_stat) < 0 ||
       (unsigned long long)mounted_stat.st_dev != expected_device ||
       (unsigned long long)mounted_stat.st_ino != expected_inode)) {
    umount2(destination, MNT_DETACH);
    fail("bind source changed during mount");
  }
}

static void bind_mount_path(const char *source, const char *destination,
                            bool readonly) {
  struct stat source_stat;
  if (stat(source, &source_stat) < 0) {
    fail("cannot inspect bind source %s: %s", source, strerror(errno));
  }
  bool directory = S_ISDIR(source_stat.st_mode);
  int source_fd = pin_mount_path(source, directory, 0, 0);
  if (source_fd < 0) {
    fail("cannot pin bind source %s with open_tree(parent_fd, name, "
         "OPEN_TREE_CLONE): %s",
         source, strerror(errno));
  }
  bind_mount_fd(source_fd, destination, readonly, 0, 0,
                directory);
  close(source_fd);
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

static void mount_runtime(const char *root) {
  if (mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) < 0) {
    fail("cannot make mount propagation private: %s", strerror(errno));
  }
  int root_tree = pin_mount_path(root, true, 0, 0);
  if (root_tree < 0) {
    int error = errno;
    fail("cannot clone extracted root mount: %s", strerror(error));
  }
  if (syscall(SYS_move_mount, root_tree, "", AT_FDCWD, root,
              MOVE_MOUNT_F_EMPTY_PATH) < 0) {
    int error = errno;
    close(root_tree);
    fail("cannot mount extracted root: %s", strerror(error));
  }
  close(root_tree);
  char oldroot[4096];
  if (snprintf(oldroot, sizeof(oldroot), "%s/.namespace-oldroot", root) >=
      (int)sizeof(oldroot)) {
    fail("extracted root path is too long");
  }
  if (mkdir(oldroot, 0700) < 0 && errno != EEXIST) {
    fail("cannot prepare old root: %s", strerror(errno));
  }
  char bind_files[4096];
  if (snprintf(bind_files, sizeof(bind_files), "%s/.namespace-bind-files",
               root) >= (int)sizeof(bind_files)) {
    fail("extracted root path is too long");
  }
  if (mkdir(bind_files, 0700) < 0 && errno != EEXIST) {
    fail("cannot prepare pinned bind directory: %s", strerror(errno));
  }
  if (mount(NULL, root, NULL, MS_BIND | MS_REMOUNT | MS_RDONLY, NULL) < 0) {
    fail("cannot make extracted root read-only: %s", strerror(errno));
  }
}

static void enter_root(const char *root) {
  if (chdir(root) < 0) {
    fail("cannot enter extracted root: %s", strerror(errno));
  }
  if (syscall(SYS_pivot_root, ".", ".namespace-oldroot") < 0) {
    fail("cannot pivot into extracted root: %s", strerror(errno));
  }
  if (chdir("/") < 0) {
    fail("cannot enter private root: %s", strerror(errno));
  }
  if (umount2("/.namespace-oldroot", MNT_DETACH) < 0) {
    fail("cannot detach host root: %s", strerror(errno));
  }
  if (mount(NULL, "/", NULL, MS_BIND | MS_REMOUNT, NULL) < 0) {
    fail("cannot temporarily update private root: %s", strerror(errno));
  }
  if (rmdir("/.namespace-oldroot") < 0) {
    fail("cannot remove old root marker: %s", strerror(errno));
  }
  if (rmdir("/.namespace-bind-files") < 0) {
    fail("cannot remove pinned bind directory: %s", strerror(errno));
  }
  if (mount(NULL, "/", NULL, MS_BIND | MS_REMOUNT | MS_RDONLY, NULL) < 0) {
    fail("cannot make private root read-only: %s", strerror(errno));
  }
}

static void mount_runtime_fs(const char *root) {
  char path[4096];
  if (snprintf(path, sizeof(path), "%s/proc", root) >= (int)sizeof(path)) {
    fail("extracted root path is too long");
  }
  if (mount("proc", path, "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL) <
      0) {
    fail("cannot mount namespace /proc: %s", strerror(errno));
  }
  if (snprintf(path, sizeof(path), "%s/tmp", root) >= (int)sizeof(path)) {
    fail("extracted root path is too long");
  }
  if (mount("tmpfs", path, "tmpfs",
            MS_NOSUID | MS_NODEV | MS_NOEXEC, "mode=1777") < 0) {
    fail("cannot mount namespace /tmp: %s", strerror(errno));
  }
  if (snprintf(path, sizeof(path), "%s/dev", root) >= (int)sizeof(path)) {
    fail("extracted root path is too long");
  }
  if (mount("tmpfs", path, "tmpfs", MS_NOSUID, "mode=755") < 0) {
    fail("cannot mount namespace /dev: %s", strerror(errno));
  }
  const char *devices[] = {"null", "zero", "full", "random", "urandom", "tty"};
  for (size_t index = 0; index < sizeof(devices) / sizeof(devices[0]); ++index) {
    if (snprintf(path, sizeof(path), "%s/dev/%s", root, devices[index]) >=
        (int)sizeof(path)) {
      fail("extracted root path is too long");
    }
    int destination = open(path, O_WRONLY | O_CREAT | O_CLOEXEC, 0666);
    if (destination < 0) {
      fail("cannot prepare namespace device %s: %s", path, strerror(errno));
    }
    close(destination);
    char source[64];
    if (snprintf(source, sizeof(source), "/dev/%s", devices[index]) >=
        (int)sizeof(source) ||
        mount(source, path, NULL, MS_BIND, NULL) < 0) {
      fail("cannot bind namespace device %s: %s", source, strerror(errno));
    }
  }
}

static int run_child(int argc, char **argv, uid_t uid, gid_t gid) {
  const char *root = argv[1];
  const char *workspace = argv[2];
  const char *outputs = argv[3];
  const char *home = argv[4];
  const char *loader = argv[5];
  const char *tool = argv[6];
  int index = 7;

  map_current_identity(uid, gid);
  if (unshare(CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWIPC | CLONE_NEWUTS) < 0) {
    fail("cannot establish private execution namespaces: %s", strerror(errno));
  }
  pid_t child = fork();
  if (child < 0) {
    fail("cannot enter PID namespace: %s", strerror(errno));
  }
  if (child > 0) {
    int status = 0;
    pid_t waited;
    do {
      waited = waitpid(child, &status, 0);
    } while (waited < 0 && errno == EINTR);
    if (waited < 0) {
      fail("cannot synchronously wait for namespace child: %s", strerror(errno));
    }
    if (WIFEXITED(status)) {
      return WEXITSTATUS(status);
    }
    if (WIFSIGNALED(status)) {
      return 128 + WTERMSIG(status);
    }
    return 1;
  }

  if (sethostname("mkosi-debian-tools", strlen("mkosi-debian-tools")) < 0 ||
      setdomainname("localdomain", strlen("localdomain")) < 0) {
    fail("cannot set deterministic UTS identity: %s", strerror(errno));
  }
  mount_runtime(root);
  if (mount(NULL, root, NULL, MS_BIND | MS_REMOUNT, NULL) < 0) {
    fail("cannot prepare extracted root for typed mounts: %s", strerror(errno));
  }
  char destination[4096];
  if (snprintf(destination, sizeof(destination), "%s/workspace", root) >=
      (int)sizeof(destination)) {
    fail("workspace path is too long");
  }
  bind_mount_path(workspace, destination, false);
  if (snprintf(destination, sizeof(destination), "%s/outputs", root) >=
      (int)sizeof(destination)) {
    fail("outputs path is too long");
  }
  bind_mount_path(outputs, destination, false);
  if (snprintf(destination, sizeof(destination), "%s/root", root) >=
      (int)sizeof(destination)) {
    fail("home path is too long");
  }
  bind_mount_path(home, destination, false);
  mount_runtime_fs(root);

  while (index < argc && strcmp(argv[index], "--") != 0) {
    bool readonly;
    if (strcmp(argv[index], "--ro-bind") == 0) {
      readonly = true;
    } else if (strcmp(argv[index], "--rw-bind") == 0) {
      readonly = false;
    } else {
      fail("unknown namespace mount option: %s", argv[index]);
    }
    if (index + 5 >= argc || argv[index + 1][0] != '/' ||
        argv[index + 2][0] != '/' ||
        (strcmp(argv[index + 5], "dir") != 0 &&
         strcmp(argv[index + 5], "file") != 0)) {
      fail("namespace mount options require fd, destination, identity, and type");
    }
    if (snprintf(destination, sizeof(destination), "%s%s", root,
                argv[index + 2]) >= (int)sizeof(destination)) {
      fail("namespace mount destination is too long");
    }
    char *device_end;
    char *inode_end;
    unsigned long long expected_device =
        strtoull(argv[index + 3], &device_end, 10);
    unsigned long long expected_inode =
        strtoull(argv[index + 4], &inode_end, 10);
    if (*device_end != '\0' || *inode_end != '\0') {
      fail("namespace mount identity is invalid");
    }
    bool directory = strcmp(argv[index + 5], "dir") == 0;
    int source_fd = pin_mount_path(argv[index + 1], directory,
                                   expected_device, expected_inode);
    if (source_fd < 0) {
      fail("cannot pin bind source %s with open_tree(parent_fd, name, "
           "OPEN_TREE_CLONE): %s",
           argv[index + 1], strerror(errno));
    }
    bind_mount_fd(source_fd, destination, readonly, expected_device,
                  expected_inode, directory);
    close(source_fd);
    index += 6;
  }
  if (index >= argc || strcmp(argv[index], "--") != 0) {
    fail("namespace runner command separator is missing");
  }

  if (mount(NULL, root, NULL, MS_BIND | MS_REMOUNT | MS_RDONLY, NULL) < 0) {
    fail("cannot make extracted root read-only after typed mounts: %s",
         strerror(errno));
  }
  enter_root(root);
  close_non_stdio_fds();
  if (chdir("/workspace") < 0) {
    fail("cannot set namespace working directory: %s", strerror(errno));
  }
  setenv("PATH", "/usr/bin:/usr/sbin:/bin:/sbin", 1);
  setenv("HOME", "/root", 1);
  setenv("TMPDIR", "/tmp", 1);
  setenv("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt", 1);
  setenv("PWD", "/workspace", 1);

  size_t argument_count = (size_t)(argc - index - 1);
  char **command = calloc(argument_count + 5, sizeof(char *));
  if (command == NULL) {
    fail("cannot allocate namespace command");
  }
  command[0] = (char *)loader;
  command[1] = "--library-path";
  command[2] =
      "/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:"
      "/usr/lib/x86_64-linux-gnu/systemd:/usr/lib/systemd:/usr/lib64";
  command[3] = (char *)tool;
  for (size_t argument = 0; argument < argument_count; ++argument) {
    command[argument + 4] = argv[index + 1 + argument];
  }
  command[argument_count + 4] = NULL;
  execv(loader, command);
  fail("cannot execute packaged loader %s: %s", loader, strerror(errno));
  return 1;
}

static int recursive_readonly_self_test(void) {
  const char *base = "namespace-runner-ro-test";
  const char *source = "namespace-runner-ro-test/source";
  const char *nested = "namespace-runner-ro-test/source/nested";
  const char *destination = "namespace-runner-ro-test/destination";
  const char *destination_nested = "namespace-runner-ro-test/destination/nested";
  const char *source_marker = "namespace-runner-ro-test/source/nested/marker";
  const char *destination_marker = "namespace-runner-ro-test/destination/nested/created";
  uid_t uid = getuid();
  gid_t gid = getgid();
  if (map_current_identity(uid, gid), mkdir(base, 0700) < 0 ||
      mkdir(source, 0700) < 0 || mkdir(nested, 0700) < 0 ||
      mkdir(destination, 0700) < 0) {
    return 1;
  }
  if (unshare(CLONE_NEWNS) < 0 ||
      mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) < 0 ||
      mount("tmpfs", nested, "tmpfs", 0, "mode=755") < 0) {
    return 1;
  }
  int marker = open(source_marker, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (marker < 0 || write(marker, "source\n", 7) != 7) {
    return 1;
  }
  close(marker);
  bind_mount_path(source, destination, true);
  int created = open(destination_marker, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (created >= 0) {
    close(created);
    return 1;
  }
  if (errno != EROFS && errno != EPERM) {
    return 1;
  }
  if (access(source_marker, R_OK) != 0) {
    return 1;
  }
  umount2(destination, MNT_DETACH);
  umount2(nested, MNT_DETACH);
  unlink(source_marker);
  rmdir(destination_nested);
  rmdir(destination);
  rmdir(nested);
  rmdir(source);
  rmdir(base);
  return 0;
}

static int fd_swap_self_test(void) {
  const char *base = "namespace-runner-fd-swap";
  const char *source = "namespace-runner-fd-swap/source";
  const char *replacement = "namespace-runner-fd-swap/replacement";
  const char *directory_source = "namespace-runner-fd-swap/directory-source";
  const char *directory_replacement =
      "namespace-runner-fd-swap/directory-replacement";
  const char *destination_directory = "namespace-runner-fd-swap/destination";
  const char *destination = "namespace-runner-fd-swap/destination/file";
  const char *directory_destination =
      "namespace-runner-fd-swap/destination/directory";
  const char *directory_marker = "namespace-runner-fd-swap/directory-source/marker";
  const char *directory_destination_marker =
      "namespace-runner-fd-swap/destination/directory/marker";
  const char *ancestor = "namespace-runner-fd-swap/ancestor";
  const char *ancestor_source = "namespace-runner-fd-swap/ancestor/source";
  const char *ancestor_replacement =
      "namespace-runner-fd-swap/ancestor-replacement";
  const char *ancestor_destination =
      "namespace-runner-fd-swap/destination/ancestor";
  map_current_identity(getuid(), getgid());
  if (unshare(CLONE_NEWNS) < 0 ||
      mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) < 0) {
    return 1;
  }
  if (mkdir(base, 0700) < 0 || mkdir(destination_directory, 0700) < 0 ||
      mount("tmpfs", destination_directory, "tmpfs", 0, "mode=755") < 0) {
    return 1;
  }
  int original = open(source, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (original < 0 || write(original, "original\n", 9) != 9) {
    return 1;
  }
  close(original);
  int source_fd = pin_mount_path(source, false, 0, 0);
  if (source_fd < 0) {
    return 1;
  }
  struct stat source_stat;
  if (fstat(source_fd, &source_stat) < 0) {
    close(source_fd);
    return 1;
  }
  int destination_file = open(destination, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (destination_file < 0) {
    return 1;
  }
  close(destination_file);
  if (rename(source, replacement) < 0) {
    return 1;
  }
  int changed = open(source, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (changed < 0 || write(changed, "changed\n", 8) != 8) {
    return 1;
  }
  close(changed);
  pid_t file_mount_child = fork();
  if (file_mount_child < 0) {
    return 1;
  }
  if (file_mount_child == 0) {
    bind_mount_fd(source_fd, destination, false,
                  (unsigned long long)source_stat.st_dev,
                  (unsigned long long)source_stat.st_ino, false);
    _exit(0);
  }
  int file_mount_status = 0;
  if (waitpid(file_mount_child, &file_mount_status, 0) < 0) {
    return 1;
  }
  bool file_mount_ok =
      WIFEXITED(file_mount_status) && WEXITSTATUS(file_mount_status) == 0;
  int mounted = file_mount_ok ? open(destination, O_RDONLY | O_CLOEXEC) : -1;
  char contents[16] = {0};
  ssize_t length = mounted < 0 ? -1 : read(mounted, contents, sizeof(contents) - 1);
  if (mounted >= 0) {
    close(mounted);
  }
  if (file_mount_ok) {
    umount2(destination, MNT_DETACH);
  }
  close(source_fd);
  unlink(destination);
  unlink(source);
  unlink(replacement);
  if (mkdir(directory_source, 0700) < 0) {
    return 1;
  }
  int directory_file =
      open(directory_marker, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (directory_file < 0 || write(directory_file, "directory\n", 10) != 10) {
    return 1;
  }
  close(directory_file);
  int directory_fd = pin_mount_path(directory_source, true, 0, 0);
  if (directory_fd < 0) {
    return 1;
  }
  struct stat directory_stat;
  if (fstat(directory_fd, &directory_stat) < 0 ||
      mkdir(directory_destination, 0700) < 0) {
    return 1;
  }
  destination_file = open(destination, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (destination_file < 0) {
    return 1;
  }
  close(destination_file);
  pid_t wrong_type_child = fork();
  if (wrong_type_child < 0) {
    return 1;
  }
  if (wrong_type_child == 0) {
    bind_mount_fd(directory_fd, destination, false,
                  (unsigned long long)directory_stat.st_dev,
                  (unsigned long long)directory_stat.st_ino, true);
    _exit(0);
  }
  int wrong_type_status = 0;
  if (waitpid(wrong_type_child, &wrong_type_status, 0) < 0 ||
      !WIFEXITED(wrong_type_status) || WEXITSTATUS(wrong_type_status) == 0) {
    return 1;
  }
  unlink(destination);
  bind_mount_fd(directory_fd, directory_destination, false,
                (unsigned long long)directory_stat.st_dev,
                (unsigned long long)directory_stat.st_ino, true);
  if (rename(directory_source, directory_replacement) < 0 ||
      mkdir(directory_source, 0700) < 0) {
    return 1;
  }
  int directory_mounted = open(directory_destination_marker, O_RDONLY | O_CLOEXEC);
  char directory_contents[20] = {0};
  ssize_t directory_length =
      directory_mounted < 0
          ? -1
          : read(directory_mounted, directory_contents,
                 sizeof(directory_contents) - 1);
  if (directory_mounted >= 0) {
    close(directory_mounted);
  }
  umount2(directory_destination, MNT_DETACH);
  close(directory_fd);
  unlink(directory_destination_marker);
  rmdir(directory_destination);
  unlink(directory_marker);
  rmdir(directory_source);
  rmdir(directory_replacement);
  if (mkdir(ancestor, 0700) < 0) {
    return 1;
  }
  int ancestor_file = open(ancestor_source, O_WRONLY | O_CREAT | O_CLOEXEC,
                           0644);
  if (ancestor_file < 0 || write(ancestor_file, "ancestor\n", 9) != 9) {
    return 1;
  }
  close(ancestor_file);
  int ancestor_fd = pin_mount_path(ancestor_source, false, 0, 0);
  if (ancestor_fd < 0) {
    return 1;
  }
  struct stat ancestor_stat;
  if (fstat(ancestor_fd, &ancestor_stat) < 0) {
    return 1;
  }
  ancestor_file =
      open(ancestor_destination, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (ancestor_file < 0) {
    return 1;
  }
  close(ancestor_file);
  if (rename(ancestor, ancestor_replacement) < 0 ||
      mkdir(ancestor, 0700) < 0) {
    return 1;
  }
  bind_mount_fd(ancestor_fd, ancestor_destination, false,
                (unsigned long long)ancestor_stat.st_dev,
                (unsigned long long)ancestor_stat.st_ino, false);
  ancestor_file = open(ancestor_destination, O_RDONLY | O_CLOEXEC);
  char ancestor_contents[16] = {0};
  ssize_t ancestor_length =
      ancestor_file < 0
          ? -1
          : read(ancestor_file, ancestor_contents,
                 sizeof(ancestor_contents) - 1);
  if (ancestor_file >= 0) {
    close(ancestor_file);
  }
  umount2(ancestor_destination, MNT_DETACH);
  close(ancestor_fd);
  unlink(ancestor_destination);
  unlink(ancestor_source);
  rmdir(ancestor);
  rmdir(ancestor_replacement);
  umount2(destination_directory, MNT_DETACH);
  rmdir(destination_directory);
  rmdir(base);
  bool file_ok =
      file_mount_ok && length == 9 && memcmp(contents, "original\n", 9) == 0;
  return file_ok &&
                 directory_length == 10 &&
                 memcmp(directory_contents, "directory\n", 10) == 0 &&
                 ancestor_length == 9 &&
                 memcmp(ancestor_contents, "ancestor\n", 9) == 0
             ? 0
             : 1;
}

static int empty_path_regression_self_test(void) {
  char base[128];
  char source[160];
  int source_fd = -1;
  int tree_fd = -1;
  int result = 1;

  if (snprintf(base, sizeof(base), "/dev/shm/namespace-runner-empty-path-%ld",
               (long)getpid()) >= (int)sizeof(base) ||
      snprintf(source, sizeof(source), "%s/source", base) >=
          (int)sizeof(source) ||
      mkdir(base, 0700) < 0 || mkdir(source, 0700) < 0) {
    fprintf(stderr, "empty-path fixture setup failed: %s\n", strerror(errno));
    goto cleanup;
  }
  source_fd = open(source, O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
  if (source_fd < 0) {
    fprintf(stderr, "empty-path fixture open failed: %s\n", strerror(errno));
    goto cleanup;
  }
  map_current_identity(getuid(), getgid());
  if (unshare(CLONE_NEWNS) < 0 ||
      mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) < 0) {
    fprintf(stderr, "empty-path namespace setup failed: %s\n",
            strerror(errno));
    goto cleanup;
  }
  tree_fd = syscall(SYS_open_tree, source_fd, "",
                    OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC | AT_EMPTY_PATH |
                        AT_RECURSIVE);
  if (tree_fd >= 0 || errno != EINVAL) {
    fprintf(stderr, "empty-path fixture expected EINVAL, got %s\n",
            tree_fd >= 0 ? "success" : strerror(errno));
    goto cleanup;
  }
  result = 0;

cleanup:
  if (tree_fd >= 0) {
    close(tree_fd);
  }
  if (source_fd >= 0) {
    close(source_fd);
  }
  rmdir(source);
  rmdir(base);
  return result;
}

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--self-test-recursive-ro") == 0) {
    return recursive_readonly_self_test();
  }
  if (argc == 2 && strcmp(argv[1], "--self-test-fd-swap") == 0) {
    return fd_swap_self_test();
  }
  if (argc == 2 && strcmp(argv[1], "--self-test-empty-path") == 0) {
    return empty_path_regression_self_test();
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
