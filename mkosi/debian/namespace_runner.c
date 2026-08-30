#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
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

static void fail(const char *format, ...) {
  va_list arguments;
  va_start(arguments, format);
  vfprintf(stderr, format, arguments);
  va_end(arguments);
  fputc('\n', stderr);
  exit(1);
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
  write_text("/proc/self/uid_map", "0 %lu 1\n", (unsigned long)uid);
  write_text("/proc/self/gid_map", "0 %lu 1\n", (unsigned long)gid);
}

static void bind_mount(const char *source, const char *destination,
                       bool readonly) {
  struct stat source_stat;
  if (stat(source, &source_stat) < 0) {
    fail("cannot inspect bind source %s: %s", source, strerror(errno));
  }
  unsigned long flags = MS_BIND | (S_ISDIR(source_stat.st_mode) ? MS_REC : 0);
  if (mount(source, destination, NULL, flags, NULL) < 0) {
    fail("cannot bind %s to %s: %s", source, destination, strerror(errno));
  }
  if (readonly &&
      mount(NULL, destination, NULL, MS_BIND | MS_REMOUNT | MS_RDONLY, NULL) <
          0) {
    fail("cannot make bind read-only at %s: %s", destination, strerror(errno));
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
    bind_mount(source, path, false);
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
    int status;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {
    }
    if (WIFEXITED(status)) {
      return WEXITSTATUS(status);
    }
    if (WIFSIGNALED(status)) {
      return 128 + WTERMSIG(status);
    }
    return 1;
  }

  mount_runtime(root);
  char destination[4096];
  if (snprintf(destination, sizeof(destination), "%s/workspace", root) >=
      (int)sizeof(destination)) {
    fail("workspace path is too long");
  }
  bind_mount(workspace, destination, false);
  if (snprintf(destination, sizeof(destination), "%s/outputs", root) >=
      (int)sizeof(destination)) {
    fail("outputs path is too long");
  }
  bind_mount(outputs, destination, false);
  if (snprintf(destination, sizeof(destination), "%s/root", root) >=
      (int)sizeof(destination)) {
    fail("home path is too long");
  }
  bind_mount(home, destination, false);
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
    if (index + 2 >= argc || argv[index + 2][0] != '/') {
      fail("namespace mount options require separate source and destination");
    }
    if (snprintf(destination, sizeof(destination), "%s%s", root,
                argv[index + 2]) >= (int)sizeof(destination)) {
      fail("namespace mount destination is too long");
    }
    bind_mount(argv[index + 1], destination, readonly);
    index += 3;
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

int main(int argc, char **argv) {
  if (argc < 8) {
    fprintf(stderr,
            "usage: namespace_runner ROOT WORKSPACE OUTPUTS HOME LOADER TOOL "
            "[mounts...] -- [args...]\n");
    return 2;
  }
  uid_t uid = getuid();
  gid_t gid = getgid();
  return run_child(argc, argv, uid, gid);
}
