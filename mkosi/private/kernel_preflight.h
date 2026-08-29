#ifndef RULES_MKOSI_KERNEL_PREFLIGHT_H
#define RULES_MKOSI_KERNEL_PREFLIGHT_H

#include <stddef.h>
#include <stdio.h>

typedef struct {
  int user_namespace;
  int id_mapping;
  int root_transition;
  int namespace_capabilities;
  int mount_namespace;
  int bind_mount;
  int pivot_root;
} rules_mkosi_namespace_checks;

typedef struct {
  int (*check_initial_privilege)(char *detail, size_t detail_size,
                                 void *context);
  int (*run_namespace_setup)(rules_mkosi_namespace_checks *checks,
                             void *context);
  void *context;
} rules_mkosi_kernel_preflight_ops;

/*
 * proc_root is normally "/proc". Tests may point it at a fixture containing
 * procfs sysctl files and inject namespace operations through ops. Passing
 * NULL for ops runs the real kernel checks.
 */
int rules_mkosi_kernel_preflight_with_ops(
    const char *proc_root, FILE *output,
    const rules_mkosi_kernel_preflight_ops *ops);

int rules_mkosi_kernel_preflight(const char *proc_root, FILE *output);

#endif
