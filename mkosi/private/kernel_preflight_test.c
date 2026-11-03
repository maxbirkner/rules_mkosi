#include "kernel_preflight.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))

enum {
  FAIL_CAPABILITY_SETS = 1u << 0,
  FAIL_CAPABILITY_EXEC = 1u << 1,
  FAIL_TMPFS_WORKSPACE = 1u << 2,
  FAIL_BIND_MOUNT = 1u << 3,
  FAIL_PIVOT_ROOT_WORKSPACE = 1u << 4,
  FAIL_PIVOT_ROOT = 1u << 5,
  FAIL_OLD_ROOT_DETACH = 1u << 6,
  FAIL_FD_MOUNT_API = 1u << 7,
};

typedef struct {
  unsigned int failure_mask;
  rules_mkosi_fd_mount_operation fd_mount_operation;
  int fd_mount_errno;
} fixture_context;

typedef struct {
  const char *needle;
  const char *message;
} expected_diagnostic;

/* Created in order and removed in reverse order. */
static const char *const fixture_directories[] = {
    "sys", "sys/user", "sys/kernel", "self", "self/ns",
};

static const char *const fixture_files[] = {
    "self/ns/mnt",
    "self/ns/user",
    "sys/kernel/unprivileged_userns_clone",
    "sys/user/max_user_namespaces",
    "output",
};

static void must(int condition, const char *message) {
  if (!condition) {
    fprintf(stderr, "test failure: %s\n", message);
    exit(1);
  }
}

static void expect_diagnostic(const char *diagnostics,
                              const expected_diagnostic *expected) {
  must(strstr(diagnostics, expected->needle) != NULL, expected->message);
}

static void fixture_path(char *path, size_t path_size, const char *root,
                         const char *relative) {
  snprintf(path, path_size, "%s/%s", root, relative);
}

static void make_directory(const char *path) {
  must(mkdir(path, 0700) == 0, "create fixture directory");
}

static void write_file(const char *path, const char *contents) {
  int file = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0600);
  must(file >= 0, "open fixture file");
  must(write(file, contents, strlen(contents)) == (ssize_t)strlen(contents),
       "write fixture file");
  must(close(file) == 0, "close fixture file");
}

static void write_fixture_file(const char *root, const char *relative,
                               const char *contents) {
  char path[256];

  fixture_path(path, sizeof(path), root, relative);
  write_file(path, contents);
}

static int fake_initial_privilege(char *detail, size_t detail_size,
                                  void *context) {
  (void)context;
  snprintf(detail, detail_size, "fixture identity is unprivileged");
  return 1;
}

static int passes(const fixture_context *fixture, unsigned int failure) {
  return (fixture->failure_mask & failure) == 0;
}

static int fake_namespace_setup(rules_mkosi_namespace_checks *checks,
                                void *context) {
  const fixture_context *fixture = context;

  checks->user_namespace = 1;
  checks->id_mapping = 1;
  checks->root_transition = 1;
  checks->namespace_capabilities = passes(fixture, FAIL_CAPABILITY_SETS);
  checks->capability_exec = passes(fixture, FAIL_CAPABILITY_EXEC);
  checks->mount_namespace = 1;
  checks->tmpfs_workspace = passes(fixture, FAIL_TMPFS_WORKSPACE);
  checks->pivot_root_workspace = passes(fixture, FAIL_PIVOT_ROOT_WORKSPACE);
  checks->bind_mount = passes(fixture, FAIL_BIND_MOUNT);
  checks->fd_mount_api = passes(fixture, FAIL_FD_MOUNT_API);
  checks->fd_mount_operation = fixture->fd_mount_operation;
  checks->fd_mount_errno = fixture->fd_mount_errno;
  checks->pivot_root = passes(fixture, FAIL_PIVOT_ROOT);
  checks->old_root_detach = passes(fixture, FAIL_OLD_ROOT_DETACH);
  return 1;
}

static FILE *create_fixture(const char *root, int max_namespaces) {
  char path[256];
  size_t index;
  int file;
  FILE *output;

  make_directory(root);
  for (index = 0; index < ARRAY_SIZE(fixture_directories); ++index) {
    fixture_path(path, sizeof(path), root, fixture_directories[index]);
    make_directory(path);
  }
  write_fixture_file(root, "self/ns/user", "");
  write_fixture_file(root, "self/ns/mnt", "");
  write_fixture_file(root, "sys/user/max_user_namespaces",
                     max_namespaces == 0 ? "0\n" : "1\n");
  write_fixture_file(root, "sys/kernel/unprivileged_userns_clone", "1\n");
  fixture_path(path, sizeof(path), root, "output");
  file = open(path, O_CREAT | O_RDWR | O_TRUNC, 0600);
  must(file >= 0, "open diagnostics file");
  output = fdopen(file, "w+");
  must(output != NULL, "open diagnostics stream");
  return output;
}

static void remove_fixture(const char *root) {
  char path[256];
  size_t index;

  for (index = 0; index < ARRAY_SIZE(fixture_files); ++index) {
    fixture_path(path, sizeof(path), root, fixture_files[index]);
    must(unlink(path) == 0, "remove fixture file");
  }
  for (index = ARRAY_SIZE(fixture_directories); index > 0; --index) {
    fixture_path(path, sizeof(path), root, fixture_directories[index - 1]);
    must(rmdir(path) == 0, "remove fixture directory");
  }
  must(rmdir(root) == 0, "remove fixture root");
}

static size_t read_diagnostics(FILE *output, char *diagnostics,
                               size_t diagnostics_size) {
  size_t bytes;

  must(fflush(output) == 0, "flush diagnostics");
  must(fseek(output, 0, SEEK_SET) == 0, "rewind diagnostics");
  bytes = fread(diagnostics, 1, diagnostics_size - 1, output);
  diagnostics[bytes] = '\0';
  return bytes;
}

/*
 * Runs the preflight against a procfs fixture with injected namespace results,
 * requires it to fail closed, and returns its diagnostics.
 */
static void run_failing_preflight(const char *root, int max_namespaces,
                                  fixture_context *context,
                                  const char *fail_closed_message,
                                  char *diagnostics, size_t diagnostics_size) {
  rules_mkosi_kernel_preflight_ops ops = {
      .check_initial_privilege = fake_initial_privilege,
      .run_namespace_setup = fake_namespace_setup,
      .context = context,
  };
  FILE *output = create_fixture(root, max_namespaces);

  must(rules_mkosi_kernel_preflight_with_ops(root, output, &ops) != 0,
       fail_closed_message);
  read_diagnostics(output, diagnostics, diagnostics_size);
  must(fclose(output) == 0, "close diagnostics");
  remove_fixture(root);
}

static void test_failure_diagnostic(void) {
  static const expected_diagnostic expected[] = {
      {"PASS linux_kernel", "report Linux check"},
      {"PASS procfs_namespaces", "report procfs check"},
      {"PASS initial_privilege", "report privilege check"},
      {"FAIL user.max_user_namespaces", "report max namespace failure"},
      {"set /proc/sys/user/max_user_namespaces above zero",
       "report max namespace remediation"},
      {"PASS kernel.unprivileged_userns_clone", "report user namespace sysctl"},
      {"PASS user_namespace", "report user namespace check"},
      {"PASS id_mapping", "report ID mapping check"},
      {"PASS root_transition", "report root transition check"},
      {"PASS namespace_capabilities", "report capability set check"},
      {"PASS capability_exec", "report capability exec check"},
      {"PASS mount_namespace", "report mount namespace check"},
      {"PASS tmpfs_workspace", "report tmpfs workspace check"},
      {"PASS pivot_root_workspace", "report workspace pivot check"},
      {"PASS bind_mount", "report bind mount check"},
      {"PASS fd_mount_api", "report descriptor mount API check"},
      {"PASS pivot_root", "report final pivot check"},
      {"PASS old_root_detach", "report old root detach check"},
      {"RESULT kernel_contract: FAIL", "report final failure"},
  };
  char root[128];
  char diagnostics[8192];
  fixture_context context = {.failure_mask = 0};
  size_t index;

  snprintf(root, sizeof(root), "kernel-preflight-fixture-%ld-0",
           (long)getpid());
  run_failing_preflight(root, 0, &context, "fixture should fail closed",
                        diagnostics, sizeof(diagnostics));
  for (index = 0; index < ARRAY_SIZE(expected); ++index) {
    expect_diagnostic(diagnostics, &expected[index]);
  }
}

static void test_focused_failure(unsigned int failure_mask,
                                 const char *expected_name,
                                 unsigned int index) {
  char root[128];
  char diagnostics[8192];
  char expected[128];
  fixture_context context = {.failure_mask = failure_mask};

  snprintf(root, sizeof(root), "kernel-preflight-fixture-%ld-%u",
           (long)getpid(), index);
  run_failing_preflight(root, 1, &context,
                        "focused fixture should fail closed", diagnostics,
                        sizeof(diagnostics));
  snprintf(expected, sizeof(expected), "FAIL %s", expected_name);
  must(strstr(diagnostics, expected) != NULL,
       "focused fixture should report the injected failure");
  must(strstr(diagnostics, "RESULT kernel_contract: FAIL") != NULL,
       "focused fixture should report final failure");
}

static void test_focused_failures(void) {
  static const struct {
    unsigned int failure_mask;
    const char *name;
  } cases[] = {
      {FAIL_CAPABILITY_SETS, "namespace_capabilities"},
      {FAIL_CAPABILITY_EXEC, "capability_exec"},
      {FAIL_TMPFS_WORKSPACE, "tmpfs_workspace"},
      {FAIL_BIND_MOUNT, "bind_mount"},
      {FAIL_FD_MOUNT_API, "fd_mount_api"},
      {FAIL_PIVOT_ROOT_WORKSPACE, "pivot_root_workspace"},
      {FAIL_PIVOT_ROOT, "pivot_root"},
      {FAIL_OLD_ROOT_DETACH, "old_root_detach"},
  };
  unsigned int index;

  for (index = 0; index < ARRAY_SIZE(cases); ++index) {
    test_focused_failure(cases[index].failure_mask, cases[index].name,
                         index + 1);
  }
}

static void test_unsupported_fd_mount_api_diagnostic(void) {
  static const expected_diagnostic expected[] = {
      {"FAIL fd_mount_api", "report unsupported descriptor mount API"},
      {"kernel compatibility", "name the production syscall contract"},
      {"open_tree(directory) failed with errno 22",
       "preserve the failed operation and errno"},
      {"upgrade the kernel", "provide kernel remediation"},
  };
  char root[128];
  char diagnostics[8192];
  fixture_context context = {
      .failure_mask = FAIL_FD_MOUNT_API,
      .fd_mount_operation = RULES_MKOSI_FD_MOUNT_OP_OPEN_TREE_DIRECTORY,
      .fd_mount_errno = EINVAL,
  };
  size_t index;

  snprintf(root, sizeof(root), "kernel-preflight-fixture-%ld-unsupported",
           (long)getpid());
  run_failing_preflight(root, 1, &context,
                        "unsupported descriptor mount API should fail closed",
                        diagnostics, sizeof(diagnostics));
  for (index = 0; index < ARRAY_SIZE(expected); ++index) {
    expect_diagnostic(diagnostics, &expected[index]);
  }
}

static void test_fd_mount_diagnostic_classes(void) {
  static const struct {
    rules_mkosi_fd_mount_operation operation;
    int error;
    const char *expected;
  } cases[] = {
      {RULES_MKOSI_FD_MOUNT_OP_MOUNT_SETATTR, EPERM,
       "seccomp/LSM/policy restriction: mount_setattr(detached_fd) failed "
       "with errno 1"},
      {RULES_MKOSI_FD_MOUNT_OP_SETUP, EEXIST,
       "fixture/setup error: fixture/setup failed with errno 17"},
      {RULES_MKOSI_FD_MOUNT_OP_MOVE_MOUNT_FILE, EIO,
       "unexpected fd-mount probe error: move_mount(file) failed with errno "
       "5"},
  };

  for (unsigned int index = 0; index < ARRAY_SIZE(cases); ++index) {
    char root[128];
    char diagnostics[8192];
    fixture_context context = {
        .failure_mask = FAIL_FD_MOUNT_API,
        .fd_mount_operation = cases[index].operation,
        .fd_mount_errno = cases[index].error,
    };

    snprintf(root, sizeof(root), "kernel-preflight-fixture-%ld-class-%u",
             (long)getpid(), index);
    run_failing_preflight(root, 1, &context,
                          "diagnostic class fixture should fail closed",
                          diagnostics, sizeof(diagnostics));
    must(strstr(diagnostics, cases[index].expected) != NULL,
         "diagnostic class should preserve encoded operation and errno");
  }
}

int main(void) {
  test_failure_diagnostic();
  test_focused_failures();
  test_unsupported_fd_mount_api_diagnostic();
  test_fd_mount_diagnostic_classes();
  return 0;
}
