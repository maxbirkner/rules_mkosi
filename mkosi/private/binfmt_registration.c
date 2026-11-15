/* Some toolchains already define _GNU_SOURCE on the command line. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include "mkosi/private/binfmt_registration.h"

#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#include "mkosi/private/write_all.h"

/* The new mount API's system calls have the same numbers on every architecture.
 */
enum {
  RULES_MKOSI_SYS_FSOPEN = 430,
  RULES_MKOSI_SYS_FSCONFIG = 431,
  RULES_MKOSI_SYS_FSMOUNT = 432,
  RULES_MKOSI_FSOPEN_CLOEXEC = 0x1,
  RULES_MKOSI_FSCONFIG_CMD_CREATE = 6,
  RULES_MKOSI_FSMOUNT_CLOEXEC = 0x1,
};
#define RULES_MKOSI_MOUNT_ATTR_NOSUID 0x2U
#define RULES_MKOSI_MOUNT_ATTR_NODEV 0x4U
#define RULES_MKOSI_MOUNT_ATTR_NOEXEC 0x8U

static const rules_mkosi_foreign_architecture foreign_architectures[] = {
    {
        .debian_architecture = "arm64",
        .entry_name = "rules_mkosi_arm64",
        .magic = "\\x7fELF\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00"
                 "\\x00\\x00\\x02\\x00\\xb7\\x00",
        .mask = "\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff"
                "\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff",
        .elf_machine = EM_AARCH64,
    },
};

/*
 * write(1, message, 25); exit(0); followed by the message. ADR x1 addresses
 * the message 28 bytes after itself.
 */
static const uint32_t aarch64_probe_code[] = {
    0xd2800020U, /* mov x0, #1 */
    0x100000e1U, /* adr x1, message */
    0xd2800322U, /* mov x2, #25 */
    0xd2800808U, /* mov x8, #64 (write) */
    0xd4000001U, /* svc #0 */
    0xd2800000U, /* mov x0, #0 */
    0xd2800ba8U, /* mov x8, #93 (exit) */
    0xd4000001U, /* svc #0 */
};

#define PROBE_LOAD_ADDRESS 0x400000U

const rules_mkosi_foreign_architecture *rules_mkosi_find_foreign_architecture(
    const char *debian_architecture) {
  size_t index;

  for (index = 0;
       index < sizeof(foreign_architectures) / sizeof(foreign_architectures[0]);
       ++index) {
    if (strcmp(foreign_architectures[index].debian_architecture,
               debian_architecture) == 0) {
      return &foreign_architectures[index];
    }
  }
  return NULL;
}

int rules_mkosi_format_binfmt_registration(
    char *buffer, size_t size,
    const rules_mkosi_foreign_architecture *architecture,
    const char *interpreter) {
  int length;

  if (interpreter[0] != '/' || strchr(interpreter, ':') != NULL ||
      strchr(interpreter, '\n') != NULL) {
    return -EINVAL;
  }
  length =
      snprintf(buffer, size, ":%s:M::%s:%s:%s:FP", architecture->entry_name,
               architecture->magic, architecture->mask, interpreter);
  if (length < 0) {
    return -EINVAL;
  }
  if ((size_t)length >= size) {
    return -ENAMETOOLONG;
  }
  return length;
}

static void store_le32(unsigned char *destination, uint32_t value) {
  size_t index;

  for (index = 0; index < 4; ++index) {
    destination[index] = (unsigned char)(value >> (8 * index));
  }
}

long rules_mkosi_write_binfmt_probe(
    unsigned char *buffer, size_t size,
    const rules_mkosi_foreign_architecture *architecture) {
  static const char message[] = RULES_MKOSI_BINFMT_PROBE_OUTPUT;
  const size_t code_offset = sizeof(Elf64_Ehdr) + sizeof(Elf64_Phdr);
  const size_t code_size = sizeof(aarch64_probe_code);
  const size_t total = code_offset + code_size + sizeof(message) - 1;
  Elf64_Ehdr header;
  Elf64_Phdr segment;
  size_t index;

  if (architecture->elf_machine != EM_AARCH64) {
    return -ENOTSUP;
  }
  if (size < total) {
    return -ENOSPC;
  }
  memset(&header, 0, sizeof(header));
  memcpy(header.e_ident, ELFMAG, SELFMAG);
  header.e_ident[EI_CLASS] = ELFCLASS64;
  header.e_ident[EI_DATA] = ELFDATA2LSB;
  header.e_ident[EI_VERSION] = EV_CURRENT;
  header.e_type = ET_EXEC;
  header.e_machine = architecture->elf_machine;
  header.e_version = EV_CURRENT;
  header.e_entry = PROBE_LOAD_ADDRESS + code_offset;
  header.e_phoff = sizeof(Elf64_Ehdr);
  header.e_ehsize = sizeof(Elf64_Ehdr);
  header.e_phentsize = sizeof(Elf64_Phdr);
  header.e_phnum = 1;
  memset(&segment, 0, sizeof(segment));
  segment.p_type = PT_LOAD;
  segment.p_flags = PF_R | PF_X;
  segment.p_vaddr = PROBE_LOAD_ADDRESS;
  segment.p_paddr = PROBE_LOAD_ADDRESS;
  segment.p_filesz = total;
  segment.p_memsz = total;
  segment.p_align = 0x1000;
  /* The probe runs on a little-endian architecture, like its build hosts. */
  memcpy(buffer, &header, sizeof(header));
  memcpy(buffer + sizeof(header), &segment, sizeof(segment));
  for (index = 0; index < code_size / sizeof(aarch64_probe_code[0]); ++index) {
    store_le32(buffer + code_offset + 4 * index, aarch64_probe_code[index]);
  }
  memcpy(buffer + code_offset + code_size, message, sizeof(message) - 1);
  return (long)total;
}

static int write_id_maps(const char *inside_uid, uid_t outside_uid,
                         const char *inside_gid, gid_t outside_gid) {
  char mapping[64];
  int length;
  int result;

  result = rules_mkosi_write_file("/proc/self/setgroups", "deny", 4);
  if (result < 0) {
    return result;
  }
  length = snprintf(mapping, sizeof(mapping), "%s %lu 1", inside_uid,
                    (unsigned long)outside_uid);
  if (length < 0 || (size_t)length >= sizeof(mapping)) {
    return -EINVAL;
  }
  result =
      rules_mkosi_write_file("/proc/self/uid_map", mapping, (size_t)length);
  if (result < 0) {
    return result;
  }
  length = snprintf(mapping, sizeof(mapping), "%s %lu 1", inside_gid,
                    (unsigned long)outside_gid);
  if (length < 0 || (size_t)length >= sizeof(mapping)) {
    return -EINVAL;
  }
  return rules_mkosi_write_file("/proc/self/gid_map", mapping, (size_t)length);
}

static int fail_at(rules_mkosi_binfmt_step *step,
                   rules_mkosi_binfmt_step failed, int error) {
  *step = failed;
  return error > 0 ? -error : -EIO;
}

/* Registers INTERPRETER in the binfmt_misc instance mounted at INSTANCE. */
static int register_interpreter(
    int instance, const rules_mkosi_foreign_architecture *architecture,
    const char *interpreter) {
  char registration[PATH_MAX + 256];
  int length;
  int file;
  int result;

  length = rules_mkosi_format_binfmt_registration(
      registration, sizeof(registration), architecture, interpreter);
  if (length < 0) {
    return length;
  }
  file = openat(instance, "register", O_WRONLY | O_CLOEXEC);
  if (file < 0) {
    return -errno;
  }
  result = rules_mkosi_write_all(file, registration, (size_t)length);
  close(file);
  return result;
}

int rules_mkosi_register_foreign_interpreter(
    const rules_mkosi_foreign_architecture *architecture,
    const char *interpreter, rules_mkosi_binfmt_step *step) {
  uid_t uid = getuid();
  gid_t gid = getgid();
  long configuration;
  long instance;
  int result;

  *step = RULES_MKOSI_BINFMT_STEP_NONE;
  if (unshare(CLONE_NEWUSER | CLONE_NEWNS) < 0) {
    return fail_at(step, RULES_MKOSI_BINFMT_STEP_USER_NAMESPACE, errno);
  }
  /* binfmt_misc lets only the root of its user namespace register entries. */
  result = write_id_maps("0", uid, "0", gid);
  if (result < 0) {
    return fail_at(step, RULES_MKOSI_BINFMT_STEP_ID_MAPPING, -result);
  }
  configuration = syscall(RULES_MKOSI_SYS_FSOPEN, "binfmt_misc",
                          RULES_MKOSI_FSOPEN_CLOEXEC);
  if (configuration < 0) {
    return fail_at(step, RULES_MKOSI_BINFMT_STEP_OPEN_FILE_SYSTEM, errno);
  }
  /* The instance is never attached to a path, so no build step can see it. */
  if (syscall(RULES_MKOSI_SYS_FSCONFIG, (int)configuration,
              RULES_MKOSI_FSCONFIG_CMD_CREATE, NULL, NULL, 0) < 0) {
    result = errno;
    close((int)configuration);
    return fail_at(step, RULES_MKOSI_BINFMT_STEP_CREATE_INSTANCE, result);
  }
  instance = syscall(
      RULES_MKOSI_SYS_FSMOUNT, (int)configuration, RULES_MKOSI_FSMOUNT_CLOEXEC,
      RULES_MKOSI_MOUNT_ATTR_NOSUID | RULES_MKOSI_MOUNT_ATTR_NODEV |
          RULES_MKOSI_MOUNT_ATTR_NOEXEC);
  result = errno;
  close((int)configuration);
  if (instance < 0) {
    return fail_at(step, RULES_MKOSI_BINFMT_STEP_CREATE_INSTANCE, result);
  }
  result = register_interpreter((int)instance, architecture, interpreter);
  if (result < 0) {
    close((int)instance);
    return fail_at(step, RULES_MKOSI_BINFMT_STEP_REGISTER, -result);
  }
  return (int)instance;
}

int rules_mkosi_restore_identity(uid_t uid, gid_t gid) {
  char inside_uid[32];
  char inside_gid[32];

  if (unshare(CLONE_NEWUSER) < 0) {
    return -errno;
  }
  snprintf(inside_uid, sizeof(inside_uid), "%lu", (unsigned long)uid);
  snprintf(inside_gid, sizeof(inside_gid), "%lu", (unsigned long)gid);
  return write_id_maps(inside_uid, 0, inside_gid, 0);
}

/* Returns whether RELEASE, such as "6.8.0-1070-azure", is older than 6.7. */
static int kernel_predates_binfmt_namespaces(const char *release) {
  unsigned int major = 0;
  unsigned int minor = 0;

  if (sscanf(release, "%u.%u", &major, &minor) != 2) {
    return 0;
  }
  return major < 6 || (major == 6 && minor < 7);
}

static const char *binfmt_remediation(rules_mkosi_binfmt_step step, int error,
                                      const char *kernel_release) {
  switch (step) {
    case RULES_MKOSI_BINFMT_STEP_OPEN_FILE_SYSTEM:
      if (error == ENODEV) {
        return "the kernel has no binfmt_misc file system; load the "
               "binfmt_misc module (modprobe binfmt_misc) or build on an "
               "execution platform of the image's architecture";
      }
      break;
    case RULES_MKOSI_BINFMT_STEP_CREATE_INSTANCE:
      if (kernel_predates_binfmt_namespaces(kernel_release)) {
        return "Linux 6.7 or newer is required to mount binfmt_misc in a user "
               "namespace; upgrade the kernel or build on an execution "
               "platform of the image's architecture";
      }
      break;
    case RULES_MKOSI_BINFMT_STEP_REGISTER:
      return "binfmt_misc rejected the emulator; check that the Bazel-provided "
             "emulator exists and is executable";
    default:
      break;
  }
  return "allow unprivileged user and mount namespaces as the host-kernel "
         "contract requires, and binfmt_misc mounts in them (Linux 6.7 or "
         "newer)";
}

void rules_mkosi_report_binfmt_failure(FILE *output,
                                       rules_mkosi_binfmt_step step, int error,
                                       const char *kernel_release) {
  static const char *const step_names[] = {
      "setup",
      "user namespace",
      "UID/GID mapping",
      "open binfmt_misc",
      "create binfmt_misc instance",
      "register emulator",
      "restore identity",
  };
  const char *name = (size_t)step < sizeof(step_names) / sizeof(step_names[0])
                         ? step_names[step]
                         : "setup";

  fprintf(output, "FAIL binfmt_misc: %s failed on Linux %s: %s\n", name,
          kernel_release, strerror(error));
  fprintf(output, "Remediation: %s\n",
          binfmt_remediation(step, error, kernel_release));
}
