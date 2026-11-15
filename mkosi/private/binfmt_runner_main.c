/* Some toolchains already define _GNU_SOURCE on the command line. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>

#include "mkosi/private/binfmt_registration.h"
#include "mkosi/private/write_all.h"

/* Exit status of a setup failure before the command runs, as env(1) uses. */
enum { SETUP_FAILURE = 125, USAGE_FAILURE = 2, PROBE_BUFFER_SIZE = 512 };

static volatile pid_t forwarded_child = 0;

static void forward_signal(int signal_number) {
  if (forwarded_child > 0) {
    kill(forwarded_child, signal_number);
  }
}

static void install_signal_forwarding(void) {
  static const int forwarded[] = {SIGHUP, SIGINT, SIGQUIT, SIGTERM};
  struct sigaction action;
  size_t index;

  memset(&action, 0, sizeof(action));
  action.sa_handler = forward_signal;
  sigemptyset(&action.sa_mask);
  for (index = 0; index < sizeof(forwarded) / sizeof(forwarded[0]); ++index) {
    sigaction(forwarded[index], &action, NULL);
  }
}

static int usage(const char *program) {
  fprintf(stderr,
          "usage: %s --architecture ARCH --emulator PATH "
          "(--check | -- COMMAND [ARGUMENT...])\n",
          program);
  return USAGE_FAILURE;
}

/* Returns the exit status of a waited-for child as a shell would report it. */
static int wait_for(pid_t child) {
  int status;

  while (waitpid(child, &status, 0) < 0) {
    if (errno != EINTR) {
      perror("binfmt_runner: waitpid");
      return SETUP_FAILURE;
    }
  }
  if (WIFEXITED(status)) {
    return WEXITSTATUS(status);
  }
  return WIFSIGNALED(status) ? 128 + WTERMSIG(status) : SETUP_FAILURE;
}

static void restore_identity_or_exit(uid_t uid, gid_t gid,
                                     const char *kernel_release) {
  int result = rules_mkosi_restore_identity(uid, gid);

  if (result < 0) {
    rules_mkosi_report_binfmt_failure(stderr,
                                      RULES_MKOSI_BINFMT_STEP_RESTORE_IDENTITY,
                                      -result, kernel_release);
    _exit(SETUP_FAILURE);
  }
}

static int run_command(char **command, uid_t uid, gid_t gid,
                       const char *kernel_release) {
  pid_t child;

  install_signal_forwarding();
  child = fork();
  if (child < 0) {
    perror("binfmt_runner: fork");
    return SETUP_FAILURE;
  }
  if (child == 0) {
    restore_identity_or_exit(uid, gid, kernel_release);
    execvp(command[0], command);
    fprintf(stderr, "binfmt_runner: cannot execute %s: %s\n", command[0],
            strerror(errno));
    _exit(127);
  }
  forwarded_child = child;
  return wait_for(child);
}

/* Executes the probe program in the child, with standard output on OUTPUT. */
static void execute_probe(const rules_mkosi_foreign_architecture *architecture,
                          int output, uid_t uid, gid_t gid,
                          const char *kernel_release) {
  unsigned char probe[PROBE_BUFFER_SIZE];
  char *const arguments[] = {"probe", NULL};
  char *const environment[] = {NULL};
  long size;
  long file;

  restore_identity_or_exit(uid, gid, kernel_release);
  size = rules_mkosi_write_binfmt_probe(probe, sizeof(probe), architecture);
  file = syscall(SYS_memfd_create, "rules_mkosi_binfmt_probe", 0U);
  if (size < 0 || file < 0 ||
      rules_mkosi_write_all((int)file, probe, (size_t)size) < 0 ||
      dup2(output, STDOUT_FILENO) < 0) {
    _exit(SETUP_FAILURE);
  }
  syscall(SYS_execveat, (int)file, "", arguments, environment, AT_EMPTY_PATH);
  fprintf(stderr, "binfmt_runner: cannot execute the %s probe: %s\n",
          architecture->debian_architecture, strerror(errno));
  _exit(127);
}

static int check(const rules_mkosi_foreign_architecture *architecture,
                 uid_t uid, gid_t gid, const char *kernel_release) {
  static const char expected[] = RULES_MKOSI_BINFMT_PROBE_OUTPUT;
  char output[sizeof(expected)];
  size_t received = 0;
  ssize_t count;
  int pipe_files[2];
  pid_t child;
  int status;

  if (pipe(pipe_files) < 0) {
    perror("binfmt_runner: pipe");
    return SETUP_FAILURE;
  }
  child = fork();
  if (child < 0) {
    perror("binfmt_runner: fork");
    return SETUP_FAILURE;
  }
  if (child == 0) {
    close(pipe_files[0]);
    execute_probe(architecture, pipe_files[1], uid, gid, kernel_release);
  }
  close(pipe_files[1]);
  while (received < sizeof(output) - 1 &&
         (count = read(pipe_files[0], output + received,
                       sizeof(output) - 1 - received)) != 0) {
    if (count < 0 && errno != EINTR) {
      break;
    }
    received += count > 0 ? (size_t)count : 0;
  }
  output[received] = '\0';
  close(pipe_files[0]);
  status = wait_for(child);
  if (status != 0 || strcmp(output, expected) != 0) {
    printf("FAIL binfmt_misc: the registered emulator did not run an %s "
           "program (exit status %d)\n",
           architecture->debian_architecture, status);
    printf("Remediation: check that the Bazel-provided emulator runs on this "
           "host\n");
    printf("RESULT binfmt_misc FAIL\n");
    return 1;
  }
  printf("PASS binfmt_misc: a private instance runs %s programs on Linux %s\n",
         architecture->debian_architecture, kernel_release);
  printf("RESULT binfmt_misc PASS\n");
  return 0;
}

int main(int argc, char **argv) {
  const rules_mkosi_foreign_architecture *architecture = NULL;
  const char *emulator = NULL;
  char interpreter[PATH_MAX];
  rules_mkosi_binfmt_step step;
  struct utsname kernel;
  uid_t uid = getuid();
  gid_t gid = getgid();
  int check_only = 0;
  int index = 1;
  int instance;

  for (; index < argc; ++index) {
    if (strcmp(argv[index], "--check") == 0) {
      check_only = 1;
    } else if (strcmp(argv[index], "--") == 0) {
      ++index;
      break;
    } else if (index + 1 < argc && strcmp(argv[index], "--architecture") == 0) {
      architecture = rules_mkosi_find_foreign_architecture(argv[++index]);
      if (architecture == NULL) {
        fprintf(stderr, "binfmt_runner: unsupported architecture %s\n",
                argv[index]);
        return USAGE_FAILURE;
      }
    } else if (index + 1 < argc && strcmp(argv[index], "--emulator") == 0) {
      emulator = argv[++index];
    } else {
      return usage(argv[0]);
    }
  }
  if (architecture == NULL || emulator == NULL ||
      check_only == (index < argc)) {
    return usage(argv[0]);
  }
  if (realpath(emulator, interpreter) == NULL) {
    fprintf(stderr, "binfmt_runner: emulator %s: %s\n", emulator,
            strerror(errno));
    return SETUP_FAILURE;
  }
  if (uname(&kernel) < 0) {
    strcpy(kernel.release, "unknown");
  }
  instance = rules_mkosi_register_foreign_interpreter(architecture, interpreter,
                                                      &step);
  if (instance < 0) {
    rules_mkosi_report_binfmt_failure(check_only ? stdout : stderr, step,
                                      -instance, kernel.release);
    if (check_only) {
      printf("RESULT binfmt_misc FAIL\n");
      return 1;
    }
    return SETUP_FAILURE;
  }
  fflush(stdout);
  /* The open instance keeps the registration alive until this process exits. */
  return check_only ? check(architecture, uid, gid, kernel.release)
                    : run_command(argv + index, uid, gid, kernel.release);
}
