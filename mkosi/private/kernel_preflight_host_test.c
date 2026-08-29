#include "kernel_preflight.h"

#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--capability-check") == 0) {
    return rules_mkosi_verify_namespace_capabilities();
  }
  return rules_mkosi_kernel_preflight("/proc", stdout);
}
