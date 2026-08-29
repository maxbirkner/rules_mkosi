#ifndef RULES_MKOSI_KERNEL_PREFLIGHT_H
#define RULES_MKOSI_KERNEL_PREFLIGHT_H

#include <stdio.h>

/*
 * Runs the host contract checks used by an unprivileged mkosi action.
 *
 * proc_root is normally "/proc". Tests may point it at a fixture containing
 * the procfs sysctl files; namespace and mount checks always exercise the
 * running kernel.
 */
int rules_mkosi_kernel_preflight(const char *proc_root, FILE *output);

#endif
