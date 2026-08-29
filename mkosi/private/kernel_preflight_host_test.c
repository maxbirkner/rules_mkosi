#include "kernel_preflight.h"

#include <stdio.h>

int main(void) {
  return rules_mkosi_kernel_preflight("/proc", stdout);
}
