#include "kernel_preflight.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

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
} fixture_context;

static void must(int condition, const char *message) {
  if (!condition) {
    fprintf(stderr, "test failure: %s\n", message);
    exit(1);
  }
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

static int fake_initial_privilege(char *detail, size_t detail_size,
                                  void *context) {
  (void)context;
  snprintf(detail, detail_size, "fixture identity is unprivileged");
  return 1;
}

static int fake_namespace_setup(rules_mkosi_namespace_checks *checks,
                                void *context) {
  const fixture_context *fixture = context;

  checks->user_namespace = 1;
  checks->id_mapping = 1;
  checks->root_transition = 1;
  checks->namespace_capabilities =
      (fixture->failure_mask & FAIL_CAPABILITY_SETS) == 0;
  checks->capability_exec =
      (fixture->failure_mask & FAIL_CAPABILITY_EXEC) == 0;
  checks->mount_namespace = 1;
  checks->tmpfs_workspace =
      (fixture->failure_mask & FAIL_TMPFS_WORKSPACE) == 0;
  checks->pivot_root_workspace =
      (fixture->failure_mask & FAIL_PIVOT_ROOT_WORKSPACE) == 0;
  checks->bind_mount = (fixture->failure_mask & FAIL_BIND_MOUNT) == 0;
  checks->fd_mount_api = (fixture->failure_mask & FAIL_FD_MOUNT_API) == 0;
  checks->pivot_root = (fixture->failure_mask & FAIL_PIVOT_ROOT) == 0;
  checks->old_root_detach =
      (fixture->failure_mask & FAIL_OLD_ROOT_DETACH) == 0;
  return 1;
}

static FILE *create_fixture(const char *root, int max_namespaces) {
  char path[256];
  int file;
  FILE *output;

  make_directory(root);
  snprintf(path, sizeof(path), "%s/sys", root);
  make_directory(path);
  snprintf(path, sizeof(path), "%s/sys/user", root);
  make_directory(path);
  snprintf(path, sizeof(path), "%s/sys/kernel", root);
  make_directory(path);
  snprintf(path, sizeof(path), "%s/self", root);
  make_directory(path);
  snprintf(path, sizeof(path), "%s/self/ns", root);
  make_directory(path);
  snprintf(path, sizeof(path), "%s/self/ns/user", root);
  write_file(path, "");
  snprintf(path, sizeof(path), "%s/self/ns/mnt", root);
  write_file(path, "");
  snprintf(path, sizeof(path), "%s/sys/user/max_user_namespaces", root);
  write_file(path, max_namespaces == 0 ? "0\n" : "1\n");
  snprintf(path, sizeof(path), "%s/sys/kernel/unprivileged_userns_clone",
           root);
  write_file(path, "1\n");
  snprintf(path, sizeof(path), "%s/output", root);
  file = open(path, O_CREAT | O_RDWR | O_TRUNC, 0600);
  must(file >= 0, "open diagnostics file");
  output = fdopen(file, "w+");
  must(output != NULL, "open diagnostics stream");
  return output;
}

static void remove_fixture(const char *root) {
  char path[256];
  const char *files[] = {
      "self/ns/mnt",
      "self/ns/user",
      "sys/kernel/unprivileged_userns_clone",
      "sys/user/max_user_namespaces",
      "output",
  };
  size_t index;

  for (index = 0; index < sizeof(files) / sizeof(files[0]); ++index) {
    snprintf(path, sizeof(path), "%s/%s", root, files[index]);
    must(unlink(path) == 0, "remove fixture file");
  }
  snprintf(path, sizeof(path), "%s/self/ns", root);
  must(rmdir(path) == 0, "remove namespace fixture directory");
  snprintf(path, sizeof(path), "%s/self", root);
  must(rmdir(path) == 0, "remove self fixture directory");
  snprintf(path, sizeof(path), "%s/sys/kernel", root);
  must(rmdir(path) == 0, "remove kernel fixture directory");
  snprintf(path, sizeof(path), "%s/sys/user", root);
  must(rmdir(path) == 0, "remove user fixture directory");
  snprintf(path, sizeof(path), "%s/sys", root);
  must(rmdir(path) == 0, "remove sys fixture directory");
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

static void test_failure_diagnostic(void) {
  char root[128];
  char diagnostics[8192];
  FILE *output;
  fixture_context context = {.failure_mask = 0};
  rules_mkosi_kernel_preflight_ops ops = {
      .check_initial_privilege = fake_initial_privilege,
      .run_namespace_setup = fake_namespace_setup,
      .context = &context,
  };

  snprintf(root, sizeof(root), "kernel-preflight-fixture-%ld-0",
           (long)getpid());
  output = create_fixture(root, 0);
  must(rules_mkosi_kernel_preflight_with_ops(root, output, &ops) != 0,
       "fixture should fail closed");
  read_diagnostics(output, diagnostics, sizeof(diagnostics));
  must(strstr(diagnostics, "PASS linux_kernel") != NULL,
       "report Linux check");
  must(strstr(diagnostics, "PASS procfs_namespaces") != NULL,
       "report procfs check");
  must(strstr(diagnostics, "PASS initial_privilege") != NULL,
       "report privilege check");
  must(strstr(diagnostics, "FAIL user.max_user_namespaces") != NULL,
       "report max namespace failure");
  must(strstr(diagnostics,
              "set /proc/sys/user/max_user_namespaces above zero") != NULL,
       "report max namespace remediation");
  must(strstr(diagnostics, "PASS kernel.unprivileged_userns_clone") != NULL,
       "report user namespace sysctl");
  must(strstr(diagnostics, "PASS user_namespace") != NULL,
       "report user namespace check");
  must(strstr(diagnostics, "PASS id_mapping") != NULL,
       "report ID mapping check");
  must(strstr(diagnostics, "PASS root_transition") != NULL,
       "report root transition check");
  must(strstr(diagnostics, "PASS namespace_capabilities") != NULL,
       "report capability set check");
  must(strstr(diagnostics, "PASS capability_exec") != NULL,
       "report capability exec check");
  must(strstr(diagnostics, "PASS mount_namespace") != NULL,
       "report mount namespace check");
  must(strstr(diagnostics, "PASS tmpfs_workspace") != NULL,
       "report tmpfs workspace check");
  must(strstr(diagnostics, "PASS pivot_root_workspace") != NULL,
       "report workspace pivot check");
  must(strstr(diagnostics, "PASS bind_mount") != NULL,
       "report bind mount check");
  must(strstr(diagnostics, "PASS fd_mount_api") != NULL,
       "report descriptor mount API check");
  must(strstr(diagnostics, "PASS pivot_root") != NULL,
       "report final pivot check");
  must(strstr(diagnostics, "PASS old_root_detach") != NULL,
       "report old root detach check");
  must(strstr(diagnostics, "RESULT kernel_contract: FAIL") != NULL,
       "report final failure");
  must(fclose(output) == 0, "close diagnostics");
  remove_fixture(root);
}

static void test_focused_failure(unsigned int failure_mask,
                                 const char *expected_name,
                                 unsigned int index) {
  char root[128];
  char diagnostics[8192];
  FILE *output;
  fixture_context context = {.failure_mask = failure_mask};
  rules_mkosi_kernel_preflight_ops ops = {
      .check_initial_privilege = fake_initial_privilege,
      .run_namespace_setup = fake_namespace_setup,
      .context = &context,
  };

  snprintf(root, sizeof(root), "kernel-preflight-fixture-%ld-%u",
           (long)getpid(), index);
  output = create_fixture(root, 1);
  must(rules_mkosi_kernel_preflight_with_ops(root, output, &ops) != 0,
       "focused fixture should fail closed");
  read_diagnostics(output, diagnostics, sizeof(diagnostics));
  {
    char expected[128];
    snprintf(expected, sizeof(expected), "FAIL %s", expected_name);
    must(strstr(diagnostics, expected) != NULL,
         "focused fixture should report the injected failure");
  }
  must(strstr(diagnostics, "RESULT kernel_contract: FAIL") != NULL,
       "focused fixture should report final failure");
  must(fclose(output) == 0, "close focused diagnostics");
  remove_fixture(root);
}

static void test_focused_failures(void) {
  test_focused_failure(FAIL_CAPABILITY_SETS, "namespace_capabilities", 1);
  test_focused_failure(FAIL_CAPABILITY_EXEC, "capability_exec", 2);
  test_focused_failure(FAIL_TMPFS_WORKSPACE, "tmpfs_workspace", 3);
  test_focused_failure(FAIL_BIND_MOUNT, "bind_mount", 4);
  test_focused_failure(FAIL_FD_MOUNT_API, "fd_mount_api", 5);
  test_focused_failure(FAIL_PIVOT_ROOT_WORKSPACE, "pivot_root_workspace", 6);
  test_focused_failure(FAIL_PIVOT_ROOT, "pivot_root", 7);
  test_focused_failure(FAIL_OLD_ROOT_DETACH, "old_root_detach", 8);
}

static void test_unsupported_fd_mount_api_diagnostic(void) {
  char root[128];
  char diagnostics[8192];
  FILE *output;
  fixture_context context = {.failure_mask = FAIL_FD_MOUNT_API};
  rules_mkosi_kernel_preflight_ops ops = {
      .check_initial_privilege = fake_initial_privilege,
      .run_namespace_setup = fake_namespace_setup,
      .context = &context,
  };

  snprintf(root, sizeof(root), "kernel-preflight-fixture-%ld-unsupported",
           (long)getpid());
  output = create_fixture(root, 1);
  must(rules_mkosi_kernel_preflight_with_ops(root, output, &ops) != 0,
       "unsupported descriptor mount API should fail closed");
  read_diagnostics(output, diagnostics, sizeof(diagnostics));
  must(strstr(diagnostics, "FAIL fd_mount_api") != NULL,
       "report unsupported descriptor mount API");
  must(strstr(diagnostics, "open_tree(AT_EMPTY_PATH)") != NULL,
       "name the unsupported syscall contract");
  must(strstr(diagnostics, "upgrade the kernel") != NULL,
       "provide kernel remediation");
  must(fclose(output) == 0, "close unsupported API diagnostics");
  remove_fixture(root);
}

int main(void) {
  test_failure_diagnostic();
  test_focused_failures();
  test_unsupported_fd_mount_api_diagnostic();
  return 0;
}
