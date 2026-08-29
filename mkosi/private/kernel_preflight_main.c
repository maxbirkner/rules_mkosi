#include "kernel_preflight.h"

#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
  const char *proc_root = "/proc";

  if (argc == 2 && strcmp(argv[1], "--capability-check") == 0) {
    return rules_mkosi_verify_namespace_capabilities();
  }
  if (argc > 2 || (argc == 2 && strncmp(argv[1], "--proc-root=", 12) != 0)) {
    fprintf(stderr,
            "usage: %s [--proc-root=PATH|--capability-check]\n", argv[0]);
    return 2;
  }
  if (argc == 2) {
    proc_root = argv[1] + 12;
    if (*proc_root == '\0') {
      fprintf(stderr, "usage: %s [--proc-root=PATH]\n", argv[0]);
      return 2;
    }
  }
  return rules_mkosi_kernel_preflight(proc_root, stdout);
}
