#ifndef RULES_MKOSI_MOUNT_API_H
#define RULES_MKOSI_MOUNT_API_H

/*
 * Linux mount API (open_tree, move_mount, mount_setattr) constants and x86_64
 * syscall numbers, for C libraries and kernel headers that predate them.
 * Include after the system headers so their definitions take precedence.
 */

#include <fcntl.h>
#include <sys/mount.h>
#include <sys/syscall.h>

#ifndef SYS_mount_setattr
#define SYS_mount_setattr 442
#endif
#ifndef SYS_open_tree
#define SYS_open_tree 428
#endif
#ifndef SYS_move_mount
#define SYS_move_mount 429
#endif
#ifndef AT_RECURSIVE
#define AT_RECURSIVE 0x8000
#endif
#ifndef MOUNT_ATTR_RDONLY
#define MOUNT_ATTR_RDONLY 0x00000001ULL
#endif
#ifndef OPEN_TREE_CLONE
#define OPEN_TREE_CLONE 1
#endif
#ifndef OPEN_TREE_CLOEXEC
#define OPEN_TREE_CLOEXEC 0x80000
#endif
#ifndef MOVE_MOUNT_F_EMPTY_PATH
#define MOVE_MOUNT_F_EMPTY_PATH 0x00000004
#endif
#ifndef AT_EMPTY_PATH
#define AT_EMPTY_PATH 0x1000
#endif

/* mount_setattr argument, named to avoid clashing with newer libc headers. */
struct rules_mkosi_mount_attr {
  unsigned long long attr_set;
  unsigned long long attr_clr;
  unsigned long long propagation;
  unsigned long long userns_fd;
};

#endif
