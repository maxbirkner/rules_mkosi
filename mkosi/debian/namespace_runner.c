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
#ifndef AT_EMPTY_PATH
#define AT_EMPTY_PATH 0x1000
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

static void write_text(const char *path, const char *format, ...) {
  char contents[128];
  va_list arguments;
  va_start(arguments, format);
  int length = vsnprintf(contents, sizeof(contents), format, arguments);
  va_end(arguments);
  if (length < 0 || (size_t)length >= sizeof(contents)) {
    fail("namespace mapping is too long");
  }
  int file = open(path, O_WRONLY | O_CLOEXEC);
  if (file < 0 || write(file, contents, (size_t)length) != length) {
    if (file >= 0) {
      close(file);
    }
    fail("cannot write %s: %s", path, strerror(errno));
  }
  close(file);
}

static void map_current_identity(uid_t uid, gid_t gid) {
  if (unshare(CLONE_NEWUSER) < 0) {
    fail("cannot establish a private user namespace: %s", strerror(errno));
  }
  write_text("/proc/self/uid_map", "0 %lu 1\n", (unsigned long)uid);
  if (setresuid(0, 0, 0) < 0) {
    fail("cannot become namespace root before clearing groups: %s", strerror(errno));
  }
  if (setgroups(0, NULL) < 0) {
    // Some sandbox kernels deny setgroups even after the UID map is
    // installed. Unmapped inherited groups are represented as overflow
    // 65534 inside this namespace and cannot confer host-group access.
    if (errno != EPERM) {
      fail("cannot clear supplementary groups: %s", strerror(errno));
    }
  }
  if (access("/proc/self/setgroups", F_OK) == 0) {
    int file = open("/proc/self/setgroups", O_WRONLY | O_CLOEXEC);
    if (file < 0 || write(file, "deny\n", 5) != 5) {
      if (file >= 0) {
        close(file);
      }
      fail("cannot disable supplementary groups: %s", strerror(errno));
    }
    close(file);
  }
  write_text("/proc/self/gid_map", "0 %lu 1\n", (unsigned long)gid);
  if (setresgid(0, 0, 0) < 0) {
    fail("cannot become namespace root: %s", strerror(errno));
  }
}

static bool source_has_submounts(const char *source) {
  char resolved_source[4096];
  const char *mount_source = source;
  if (strncmp(source, "/proc/self/fd/", strlen("/proc/self/fd/")) == 0) {
    ssize_t length = readlink(source, resolved_source, sizeof(resolved_source) - 1);
    if (length < 0 || (size_t)length >= sizeof(resolved_source)) {
      fail("cannot resolve pinned bind source %s: %s", source, strerror(errno));
    }
    resolved_source[length] = '\0';
    mount_source = resolved_source;
  }
  FILE *mounts = fopen("/proc/self/mountinfo", "r");
  if (mounts == NULL) {
    fail("cannot inspect mountinfo: %s", strerror(errno));
  }
  char line[8192];
  bool found = false;
  while (fgets(line, sizeof(line), mounts) != NULL) {
    char *separator = strstr(line, " - ");
    if (separator == NULL) {
      continue;
    }
    *separator = '\0';
    char *cursor = line;
    char *field = NULL;
    for (int index = 0; index < 5; ++index) {
      field = strsep(&cursor, " ");
      if (field == NULL) {
        break;
      }
    }
    if (field == NULL) {
      continue;
    }
    size_t source_length = strlen(mount_source);
    size_t field_length = strlen(field);
    if (field_length > source_length &&
        strncmp(field, mount_source, source_length) == 0 &&
        field[source_length] == '/') {
      found = true;
      break;
    }
  }
  fclose(mounts);
  return found;
}

static void bind_mount(const char *source, const char *destination,
                       bool readonly, unsigned long long expected_device,
                       unsigned long long expected_inode) {
  struct stat source_stat;
  if (stat(source, &source_stat) < 0) {
    fail("cannot inspect bind source %s: %s", source, strerror(errno));
  }
  if (expected_device != 0 &&
      ((unsigned long long)source_stat.st_dev != expected_device ||
       (unsigned long long)source_stat.st_ino != expected_inode)) {
    fail("bind source changed after validation: %s", source);
  }
  int mount_tree = -1;
  if (strncmp(source, "/proc/self/fd/", strlen("/proc/self/fd/")) == 0) {
    char *end;
    int source_fd = (int)strtol(source + strlen("/proc/self/fd/"), &end, 10);
    if (*end == '\0') {
      mount_tree = syscall(SYS_open_tree, source_fd, "",
                           OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC | AT_EMPTY_PATH);
    }
  } else {
    mount_tree = syscall(SYS_open_tree, AT_FDCWD, source,
                         OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC);
  }
  if (mount_tree >= 0) {
    if (syscall(SYS_move_mount, mount_tree, "", AT_FDCWD, destination,
                MOVE_MOUNT_F_EMPTY_PATH) < 0) {
      int error = errno;
      close(mount_tree);
      fail("cannot move pinned bind %s to %s: %s", source, destination,
           strerror(error));
    }
    close(mount_tree);
  } else {
    int tree_error = errno;
    unsigned long flags = MS_BIND | (S_ISDIR(source_stat.st_mode) ? MS_REC : 0);
    if (mount(source, destination, NULL, flags, NULL) < 0) {
      int error = errno;
      fail("cannot bind %s to %s: %s (open_tree: %s)", source, destination,
           strerror(error), strerror(tree_error));
    }
  }
  if (readonly) {
    struct mkosi_mount_attr attributes = {
        .attr_set = MOUNT_ATTR_RDONLY,
    };
    if (syscall(SYS_mount_setattr, AT_FDCWD, destination, AT_RECURSIVE,
                &attributes, sizeof(attributes)) == 0) {
      return;
    }
    if (errno != ENOSYS && errno != EINVAL && errno != EOPNOTSUPP) {
      fail("cannot recursively make bind read-only at %s: %s", destination,
           strerror(errno));
    }
    if (source_has_submounts(source)) {
      fail("kernel lacks recursive read-only mounts for source with submounts: %s",
           source);
    }
    if (mount(NULL, destination, NULL, MS_BIND | MS_REMOUNT | MS_RDONLY, NULL) <
        0) {
      fail("cannot make bind read-only at %s: %s", destination, strerror(errno));
    }
  }
  if (expected_device != 0) {
    struct stat mounted_stat;
    if (stat(destination, &mounted_stat) < 0 ||
        (unsigned long long)mounted_stat.st_dev != expected_device ||
        (unsigned long long)mounted_stat.st_ino != expected_inode) {
      umount2(destination, MNT_DETACH);
      fail("bind source changed during mount: %s", source);
    }
  }
}

static void mount_runtime(const char *root) {
  if (mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) < 0) {
    fail("cannot make mount propagation private: %s", strerror(errno));
  }
  if (mount(root, root, NULL, MS_BIND | MS_REC, NULL) < 0) {
    fail("cannot bind extracted root: %s", strerror(errno));
  }
  char oldroot[4096];
  if (snprintf(oldroot, sizeof(oldroot), "%s/.namespace-oldroot", root) >=
      (int)sizeof(oldroot)) {
    fail("extracted root path is too long");
  }
  if (mkdir(oldroot, 0700) < 0 && errno != EEXIST) {
    fail("cannot prepare old root: %s", strerror(errno));
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
    snprintf(source, sizeof(source), "/dev/%s", devices[index]);
    bind_mount(source, path, false, 0, 0);
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
  char destination[4096];
  if (snprintf(destination, sizeof(destination), "%s/workspace", root) >=
      (int)sizeof(destination)) {
    fail("workspace path is too long");
  }
  bind_mount(workspace, destination, false, 0, 0);
  if (snprintf(destination, sizeof(destination), "%s/outputs", root) >=
      (int)sizeof(destination)) {
    fail("outputs path is too long");
  }
  bind_mount(outputs, destination, false, 0, 0);
  if (snprintf(destination, sizeof(destination), "%s/root", root) >=
      (int)sizeof(destination)) {
    fail("home path is too long");
  }
  bind_mount(home, destination, false, 0, 0);
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
    if (index + 4 >= argc || argv[index + 2][0] != '/') {
      fail("namespace mount options require separate source and destination");
    }
    if (snprintf(destination, sizeof(destination), "%s%s", root,
                argv[index + 2]) >= (int)sizeof(destination)) {
      fail("namespace mount destination is too long");
    }
    char *device_end;
    char *inode_end;
    unsigned long long expected_device = strtoull(argv[index + 3], &device_end, 10);
    unsigned long long expected_inode = strtoull(argv[index + 4], &inode_end, 10);
    if (*device_end != '\0' || *inode_end != '\0') {
      fail("namespace mount identity is invalid");
    }
    bind_mount(argv[index + 1], destination, readonly, expected_device,
               expected_inode);
    index += 5;
  }
  if (index >= argc || strcmp(argv[index], "--") != 0) {
    fail("namespace runner command separator is missing");
  }

  enter_root(root);
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
  bind_mount(source, destination, true, 0, 0);
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

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--self-test-recursive-ro") == 0) {
    return recursive_readonly_self_test();
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
