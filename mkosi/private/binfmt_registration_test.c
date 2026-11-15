/* Some toolchains already define _GNU_SOURCE on the command line. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include "mkosi/private/binfmt_registration.h"

#include <elf.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void must(int condition, const char *message) {
  if (!condition) {
    fprintf(stderr, "test failure: %s\n", message);
    exit(1);
  }
}

static const rules_mkosi_foreign_architecture *arm64(void) {
  const rules_mkosi_foreign_architecture *architecture =
      rules_mkosi_find_foreign_architecture("arm64");

  must(architecture != NULL, "arm64 is a supported foreign architecture");
  return architecture;
}

static void test_supported_architectures(void) {
  must(arm64()->elf_machine == EM_AARCH64, "arm64 runs aarch64 executables");
  must(rules_mkosi_find_foreign_architecture("amd64") == NULL,
       "amd64 is not a foreign architecture");
  must(rules_mkosi_find_foreign_architecture("armhf") == NULL,
       "armhf is not supported");
}

static void test_registration_uses_qemu_magic_and_fix_binary_flag(void) {
  char buffer[512];
  int length = rules_mkosi_format_binfmt_registration(
      buffer, sizeof(buffer), arm64(), "/execroot/qemu-aarch64");

  must(length == (int)strlen(buffer), "the length of the registration");
  must(
      strcmp(buffer,
             ":rules_mkosi_arm64:M::"
             "\\x7fELF\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"
             "\\x00\\x02\\x00\\xb7\\x00:"
             "\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff"
             "\\xff\\xff\\xff\\xfe\\xff\\xff\\xff:"
             "/execroot/qemu-aarch64:FP") == 0,
      "registration string");
}

static void test_registration_rejects_unusable_paths(void) {
  char buffer[512];

  must(rules_mkosi_format_binfmt_registration(buffer, sizeof(buffer), arm64(),
                                              "qemu-aarch64") == -EINVAL,
       "a relative interpreter is rejected");
  must(rules_mkosi_format_binfmt_registration(buffer, sizeof(buffer), arm64(),
                                              "/a:b/qemu") == -EINVAL,
       "an interpreter with the field delimiter is rejected");
  must(rules_mkosi_format_binfmt_registration(buffer, 16, arm64(), "/qemu") ==
           -ENAMETOOLONG,
       "a short buffer is rejected");
}

static void test_probe_is_a_static_aarch64_executable(void) {
  unsigned char probe[512];
  long size = rules_mkosi_write_binfmt_probe(probe, sizeof(probe), arm64());
  Elf64_Ehdr header;
  Elf64_Phdr segment;
  const char *message = RULES_MKOSI_BINFMT_PROBE_OUTPUT;

  must(size > 0, "probe is written");
  memcpy(&header, probe, sizeof(header));
  memcpy(&segment, probe + header.e_phoff, sizeof(segment));
  must(memcmp(header.e_ident, ELFMAG, SELFMAG) == 0, "ELF magic");
  must(header.e_ident[EI_CLASS] == ELFCLASS64, "64-bit executable");
  must(header.e_type == ET_EXEC && header.e_machine == EM_AARCH64,
       "aarch64 executable");
  must(header.e_phnum == 1 && segment.p_type == PT_LOAD, "one load segment");
  must(segment.p_filesz == (Elf64_Xword)size, "the segment maps the file");
  must(header.e_entry > segment.p_vaddr &&
           header.e_entry < segment.p_vaddr + segment.p_filesz,
       "the entry point is inside the segment");
  must(memcmp(probe + size - strlen(message), message, strlen(message)) == 0,
       "the probe ends with its message");
  must(rules_mkosi_write_binfmt_probe(probe, 64, arm64()) == -ENOSPC,
       "a short buffer is rejected");
}

static void report(rules_mkosi_binfmt_step step, int error, const char *release,
                   char *buffer, size_t size) {
  FILE *output = fmemopen(buffer, size, "w");

  must(output != NULL, "open the report buffer");
  rules_mkosi_report_binfmt_failure(output, step, error, release);
  must(fclose(output) == 0, "close the report buffer");
}

static void test_failures_name_a_remediation(void) {
  char buffer[1024];

  report(RULES_MKOSI_BINFMT_STEP_CREATE_INSTANCE, EPERM, "6.6.0", buffer,
         sizeof(buffer));
  must(strstr(buffer, "FAIL binfmt_misc: create binfmt_misc instance") != NULL,
       "the failed step is named");
  must(strstr(buffer, "Remediation: Linux 6.7 or newer is required") != NULL,
       "an old kernel needs an upgrade");
  report(RULES_MKOSI_BINFMT_STEP_CREATE_INSTANCE, EPERM, "6.8.0-1070-azure",
         buffer, sizeof(buffer));
  must(strstr(buffer, "Linux 6.7 or newer is required") == NULL,
       "a new kernel is not asked to upgrade");
  must(strstr(buffer, "Remediation: allow unprivileged user and mount") != NULL,
       "a new kernel is asked for namespace permissions");
  report(RULES_MKOSI_BINFMT_STEP_OPEN_FILE_SYSTEM, ENODEV, "6.8.0", buffer,
         sizeof(buffer));
  must(strstr(buffer, "modprobe binfmt_misc") != NULL,
       "a missing file system needs the module");
}

int main(void) {
  test_supported_architectures();
  test_registration_uses_qemu_magic_and_fix_binary_flag();
  test_registration_rejects_unusable_paths();
  test_probe_is_a_static_aarch64_executable();
  test_failures_name_a_remediation();
  return 0;
}
