/*
 * Unit tests for the namespace runner's internal helpers. The runner is a
 * single static binary, so its source is included with main renamed.
 */
#define main namespace_runner_main
#include "mkosi/debian/namespace_runner.c"
#undef main

static void must(bool condition, const char *message) {
  if (!condition) {
    fprintf(stderr, "test failure: %s\n", message);
    exit(1);
  }
}

typedef struct {
  int status;
  char output[512];
} child_result;

/* Runs TEST in a child with stderr captured, because failures exit. */
static child_result run_in_child(void (*test)(const void *), const void *data) {
  child_result result = {.status = -1};
  int output[2];
  must(pipe(output) == 0, "create output pipe");
  pid_t child = fork();
  must(child >= 0, "fork test child");
  if (child == 0) {
    close(output[0]);
    must(dup2(output[1], STDERR_FILENO) >= 0, "redirect stderr");
    test(data);
    _exit(0);
  }
  close(output[1]);
  size_t length = 0;
  ssize_t bytes;
  while ((bytes = read(output[0], result.output + length,
                       sizeof(result.output) - 1 - length)) > 0) {
    length += (size_t)bytes;
  }
  close(output[0]);
  must(waitpid(child, &result.status, 0) == child, "wait for test child");
  return result;
}

static bool exited_with(const child_result *result, int code) {
  return WIFEXITED(result->status) && WEXITSTATUS(result->status) == code;
}

typedef struct {
  const char *device;
  const char *inode;
} identity_text;

static void parse_identity_text(const void *data) {
  const identity_text *text = data;
  (void)parse_mount_identity(text->device, text->inode);
}

static void test_valid_identities_are_parsed(void) {
  struct mount_identity identity = parse_mount_identity("2049", "131074");
  must(identity.validated && identity.device == 2049 &&
           identity.inode == 131074,
       "a decimal identity is parsed and validated");
  identity = parse_mount_identity("18446744073709551615", "007");
  must(identity.validated && identity.device == 18446744073709551615ULL &&
           identity.inode == 7,
       "the largest identity is accepted");
}

/* An unusable identity must stop the runner instead of skipping the check. */
static void test_unusable_identities_fail_closed(void) {
  static const identity_text cases[] = {
      {"", "1"},     {"1", ""},     {"0", "1"},
      {"1", "0"},    {"00", "1"},   {"18446744073709551616", "1"},
      {"1", "99999999999999999999"}, {"-1", "1"}, {"+1", "1"},
      {" 1", "1"},   {"1 ", "1"},   {"1x", "1"},
      {"0x10", "1"}, {"1", "-0"},
  };
  for (size_t index = 0; index < ARRAY_SIZE(cases); ++index) {
    child_result result = run_in_child(parse_identity_text, &cases[index]);
    if (!exited_with(&result, 1) ||
        strstr(result.output, "namespace mount identity is invalid") == NULL) {
      fprintf(stderr, "accepted identity \"%s\" \"%s\": %s\n",
              cases[index].device, cases[index].inode, result.output);
      exit(1);
    }
  }
}

static const char *test_directory(void) {
  const char *directory = getenv("TEST_TMPDIR");
  return directory != NULL ? directory : ".";
}

static void make_private_mount_namespace(void) {
  map_current_identity(getuid(), getgid());
  must(unshare(CLONE_NEWNS) == 0, "unshare mount namespace");
  must(mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) == 0,
       "make mounts private");
}

static void expect_pin_rejected(const char *path, bool directory,
                                struct mount_identity expected,
                                const char *message) {
  errno = ENOENT;
  int pinned = pin_mount_path(path, directory, expected);
  if (pinned >= 0) {
    close(pinned);
  }
  must(pinned < 0 && errno == EAGAIN, message);
}

/*
 * A pinned tree that is not the validated object fails with EAGAIN, never
 * with an errno left over from an earlier call.
 */
static void pin_checks_validated_identity(const void *data) {
  (void)data;
  make_private_mount_namespace();
  char path[PATH_BUFFER_SIZE];
  format_or_fail(path, sizeof(path), "test path is too long",
                 "%s/namespace-runner-pin-%ld", test_directory(),
                 (long)getpid());
  must(create_empty_file(path), "create pin source");
  struct stat status;
  must(stat(path, &status) == 0, "inspect pin source");
  struct mount_identity identity = identity_of(&status);
  struct mount_identity other_inode = identity;
  other_inode.inode += 1;
  struct mount_identity zero = {.validated = true, .device = 0, .inode = 0};
  expect_pin_rejected(path, false, other_inode,
                      "another inode is rejected with EAGAIN");
  expect_pin_rejected(path, false, zero,
                      "a zero validated identity is checked, not skipped");
  expect_pin_rejected(path, true, identity,
                      "a file pinned as a directory is rejected with EAGAIN");
  int pinned = pin_mount_path(path, false, identity);
  must(pinned >= 0, "the validated identity is pinned");
  close(pinned);
  must(unlink(path) == 0, "remove pin source");
}

static void test_pin_checks_validated_identity(void) {
  child_result result = run_in_child(pin_checks_validated_identity, NULL);
  if (!exited_with(&result, 0)) {
    fprintf(stderr, "%s", result.output);
    exit(1);
  }
}

int main(void) {
  test_valid_identities_are_parsed();
  test_unusable_identities_fail_closed();
  test_pin_checks_validated_identity();
  return 0;
}
