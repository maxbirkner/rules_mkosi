#ifndef RULES_MKOSI_WRITE_ALL_H
#define RULES_MKOSI_WRITE_ALL_H

#include <stddef.h>

/*
 * Writes all SIZE bytes of BUFFER to FILE, continuing after partial writes and
 * retrying writes interrupted by a signal. Returns 0 on success or a negative
 * errno value; a write that makes no progress fails with -EIO.
 */
int rules_mkosi_write_all(int file, const void *buffer, size_t size);

/*
 * Opens the existing PATH write-only and writes all SIZE bytes of CONTENTS
 * with rules_mkosi_write_all. Used for procfs files such as uid_map, gid_map,
 * and setgroups. Returns 0 on success or a negative errno value.
 */
int rules_mkosi_write_file(const char *path, const char *contents, size_t size);

#endif
