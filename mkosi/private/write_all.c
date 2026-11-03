#define _GNU_SOURCE

#include "mkosi/private/write_all.h"

#include <errno.h>
#include <fcntl.h>
#include <unistd.h>

int rules_mkosi_write_all(int file, const void *buffer, size_t size) {
  const char *cursor = buffer;

  while (size > 0) {
    ssize_t bytes = write(file, cursor, size);
    if (bytes < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -errno;
    }
    if (bytes == 0) {
      return -EIO;
    }
    cursor += bytes;
    size -= (size_t)bytes;
  }
  return 0;
}

int rules_mkosi_write_file(const char *path, const char *contents,
                           size_t size) {
  int file = open(path, O_WRONLY | O_CLOEXEC);
  int result;

  if (file < 0) {
    return -errno;
  }
  result = rules_mkosi_write_all(file, contents, size);
  close(file);
  return result;
}
