#include "kernel_preflight.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

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
  (void)context;
  checks->user_namespace = 1;
  checks->id_mapping = 1;
  checks->root_transition = 1;
  checks->namespace_capabilities = 1;
  checks->mount_namespace = 1;
  checks->bind_mount = 1;
  checks->pivot_root = 1;
  return 1;
}

static void test_failure_diagnostic(void) {
  char root[128];
  char path[256];
  FILE *output;
  char diagnostics[4096];
  size_t bytes;
  rules_mkosi_kernel_preflight_ops ops = {
      .check_initial_privilege = fake_initial_privilege,
      .run_namespace_setup = fake_namespace_setup,
      .context = NULL,
  };

  snprintf(root, sizeof(root), "kernel-preflight-fixture-%ld", (long)getpid());
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
  write_file(path, "0\n");
  snprintf(path, sizeof(path), "%s/sys/kernel/unprivileged_userns_clone", root);
  write_file(path, "1\n");

  snprintf(path, sizeof(path), "%s/output", root);
  {
    int file = open(path, O_CREAT | O_RDWR | O_TRUNC, 0600);
    must(file >= 0, "open diagnostics file");
    output = fdopen(file, "w+");
    must(output != NULL, "open diagnostics stream");
  }
  must(rules_mkosi_kernel_preflight_with_ops(root, output, &ops) != 0,
       "fixture should fail closed");
  must(fflush(output) == 0, "flush diagnostics");
  must(fseek(output, 0, SEEK_SET) == 0, "rewind diagnostics");
  bytes = fread(diagnostics, 1, sizeof(diagnostics) - 1, output);
  diagnostics[bytes] = '\0';
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
       "report capability check");
  must(strstr(diagnostics, "PASS mount_namespace") != NULL,
       "report mount namespace check");
  must(strstr(diagnostics, "PASS bind_mount") != NULL,
       "report bind mount check");
  must(strstr(diagnostics, "PASS pivot_root") != NULL,
       "report pivot root check");
  must(strstr(diagnostics, "RESULT kernel_contract: FAIL") != NULL,
       "report final failure");
  must(fclose(output) == 0, "close diagnostics");
  must(unlink(path) == 0, "remove diagnostics");

  snprintf(path, sizeof(path), "%s/self/ns/mnt", root);
  unlink(path);
  snprintf(path, sizeof(path), "%s/self/ns/user", root);
  unlink(path);
  snprintf(path, sizeof(path), "%s/sys/kernel/unprivileged_userns_clone", root);
  unlink(path);
  snprintf(path, sizeof(path), "%s/sys/user/max_user_namespaces", root);
  unlink(path);
  snprintf(path, sizeof(path), "%s/self/ns", root);
  rmdir(path);
  snprintf(path, sizeof(path), "%s/self", root);
  rmdir(path);
  snprintf(path, sizeof(path), "%s/sys/kernel", root);
  rmdir(path);
  snprintf(path, sizeof(path), "%s/sys/user", root);
  rmdir(path);
  snprintf(path, sizeof(path), "%s/sys", root);
  rmdir(path);
  rmdir(root);
}

int main(void) {
  test_failure_diagnostic();
  return 0;
}
