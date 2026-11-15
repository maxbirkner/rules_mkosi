#ifndef RULES_MKOSI_BINFMT_REGISTRATION_H
#define RULES_MKOSI_BINFMT_REGISTRATION_H

#include <stddef.h>
#include <stdio.h>
#include <sys/types.h>

/*
 * Registers a user-mode emulator for a foreign architecture in a binfmt_misc
 * instance that is private to a new user namespace (Linux 6.7 or newer), so
 * that the processes of an image build execute foreign programs, such as dpkg
 * maintainer scripts, without root and without any host registration.
 */

/* A foreign Debian architecture that an emulator can run. */
typedef struct {
  /* Debian architecture name, such as "arm64". */
  const char *debian_architecture;
  /* Name of the binfmt_misc entry. */
  const char *entry_name;
  /* ELF magic and mask of QEMU's qemu-binfmt-conf.sh, as \x escapes. */
  const char *magic;
  const char *mask;
  /* e_machine of the architecture's ELF executables. */
  unsigned short elf_machine;
} rules_mkosi_foreign_architecture;

/* The step of the namespace and registration setup that failed. */
typedef enum {
  RULES_MKOSI_BINFMT_STEP_NONE = 0,
  RULES_MKOSI_BINFMT_STEP_USER_NAMESPACE = 1,
  RULES_MKOSI_BINFMT_STEP_ID_MAPPING = 2,
  RULES_MKOSI_BINFMT_STEP_OPEN_FILE_SYSTEM = 3,
  RULES_MKOSI_BINFMT_STEP_CREATE_INSTANCE = 4,
  RULES_MKOSI_BINFMT_STEP_REGISTER = 5,
  RULES_MKOSI_BINFMT_STEP_RESTORE_IDENTITY = 6,
} rules_mkosi_binfmt_step;

/*
 * Returns the foreign architecture named by DEBIAN_ARCHITECTURE, or NULL if
 * none is supported.
 */
const rules_mkosi_foreign_architecture *rules_mkosi_find_foreign_architecture(
    const char *debian_architecture);

/*
 * Formats the binfmt_misc registration of INTERPRETER, an absolute path, for
 * ARCHITECTURE into BUFFER. The flags are F, which opens the interpreter at
 * registration so that it also runs in chroots that do not contain it, and P,
 * which preserves argv[0]. Returns the length, or -EINVAL for a relative or
 * delimiter-containing path and -ENAMETOOLONG if BUFFER is too small.
 */
int rules_mkosi_format_binfmt_registration(
    char *buffer, size_t size,
    const rules_mkosi_foreign_architecture *architecture,
    const char *interpreter);

/*
 * Writes into BUFFER a static executable of ARCHITECTURE that prints
 * RULES_MKOSI_BINFMT_PROBE_OUTPUT and exits with status 0, and returns its
 * size, or -ENOTSUP for an architecture without a probe and -ENOSPC if BUFFER
 * is too small.
 */
#define RULES_MKOSI_BINFMT_PROBE_OUTPUT "rules_mkosi binfmt probe\n"
long rules_mkosi_write_binfmt_probe(
    unsigned char *buffer, size_t size,
    const rules_mkosi_foreign_architecture *architecture);

/*
 * Enters a new user and mount namespace in which the caller is root, mounts a
 * detached binfmt_misc instance and registers INTERPRETER for ARCHITECTURE.
 * Returns the file descriptor of the instance, which keeps the registration
 * alive while it is open, or a negative errno value with *STEP set to the
 * failed step.
 */
int rules_mkosi_register_foreign_interpreter(
    const rules_mkosi_foreign_architecture *architecture,
    const char *interpreter, rules_mkosi_binfmt_step *step);

/*
 * Enters a nested user namespace that maps UID and GID to the root of the
 * registering namespace, so that a program executed afterwards runs with the
 * caller's original identity and without capabilities. Returns 0 or a negative
 * errno value.
 */
int rules_mkosi_restore_identity(uid_t uid, gid_t gid);

/*
 * Prints a FAIL line for STEP and ERROR (a positive errno value) with a
 * remediation for KERNEL_RELEASE, the running kernel's release string.
 */
void rules_mkosi_report_binfmt_failure(FILE *output,
                                       rules_mkosi_binfmt_step step, int error,
                                       const char *kernel_release);

#endif
