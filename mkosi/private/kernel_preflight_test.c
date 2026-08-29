#include "kernel_preflight.h"

#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static void make_directory(const char *path) {
  assert(mkdir(path, 0700) == 0);
}

static void write_file(const char *path, const char *contents) {
  int file = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0600);
  assert(file >= 0);
  assert(write(file, contents, strlen(contents)) == (ssize_t)strlen(contents));
  assert(close(file) == 0);
}

static void test_failure_diagnostic(void) {
  char root[128];
  char path[256];
  FILE *output;
  char diagnostics[4096];
  size_t bytes;

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
  output = fdopen(open(path, O_CREAT | O_RDWR | O_TRUNC, 0600), "w+");
  assert(output != NULL);
  assert(rules_mkosi_kernel_preflight(root, output) != 0);
  fflush(output);
  rewind(output);
  bytes = fread(diagnostics, 1, sizeof(diagnostics) - 1, output);
  diagnostics[bytes] = '\0';
  assert(strstr(diagnostics, "PASS linux_kernel") != NULL);
  assert(strstr(diagnostics, "PASS procfs_namespaces") != NULL);
  assert(strstr(diagnostics, "FAIL user.max_user_namespaces") != NULL);
  assert(strstr(diagnostics, "set /proc/sys/user/max_user_namespaces above zero") !=
         NULL);
  assert(strstr(diagnostics, "PASS kernel.unprivileged_userns_clone") != NULL);
  assert(strstr(diagnostics, "PASS user_namespace") != NULL);
  assert(strstr(diagnostics, "user_namespace_mount") != NULL);
  assert(strstr(diagnostics, "RESULT kernel_contract: FAIL") != NULL);
  fclose(output);
  unlink(path);

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
