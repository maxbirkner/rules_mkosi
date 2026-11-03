#define _GNU_SOURCE

#include "mkosi/private/write_all.h"

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

enum { PAYLOAD_SIZE = 1 << 20, READ_CHUNK = 512 };

static volatile sig_atomic_t interruptions;

static void must(int condition, const char *message) {
  if (!condition) {
    fprintf(stderr, "test failure: %s\n", message);
    exit(1);
  }
}

static unsigned char payload_byte(size_t index) {
  return (unsigned char)(index * 31 + index / 251);
}

static void count_interruption(int signal_number) {
  (void)signal_number;
  ++interruptions;
}

/* Without SA_RESTART, a blocked write returns early or fails with EINTR. */
static void interrupt_writes_every(long microseconds) {
  struct sigaction action;
  struct itimerval timer = {
      .it_interval = {.tv_sec = 0, .tv_usec = microseconds},
      .it_value = {.tv_sec = 0, .tv_usec = microseconds},
  };

  memset(&action, 0, sizeof(action));
  action.sa_handler = count_interruption;
  sigemptyset(&action.sa_mask);
  must(sigaction(SIGALRM, &action, NULL) == 0, "install SIGALRM handler");
  must(setitimer(ITIMER_REAL, &timer, NULL) == 0, "start interval timer");
}

static void stop_interrupting_writes(void) {
  struct itimerval timer = {{0, 0}, {0, 0}};

  must(setitimer(ITIMER_REAL, &timer, NULL) == 0, "stop interval timer");
}

/* Reads slowly so the writer keeps blocking on a full pipe. */
static void read_and_verify_payload(int file) {
  unsigned char chunk[READ_CHUNK];
  size_t received = 0;
  ssize_t bytes;

  while ((bytes = read(file, chunk, sizeof(chunk))) != 0) {
    if (bytes < 0 && errno == EINTR) {
      continue;
    }
    must(bytes > 0, "read payload");
    for (ssize_t index = 0; index < bytes; ++index) {
      must(chunk[index] == payload_byte(received + (size_t)index),
           "payload bytes arrive in order");
    }
    received += (size_t)bytes;
    usleep(50);
  }
  must(received == PAYLOAD_SIZE, "the whole payload arrives");
}

static void test_write_all_survives_partial_and_interrupted_writes(void) {
  unsigned char *payload = malloc(PAYLOAD_SIZE);
  int pipe_files[2];
  int status = 0;

  must(payload != NULL, "allocate payload");
  for (size_t index = 0; index < PAYLOAD_SIZE; ++index) {
    payload[index] = payload_byte(index);
  }
  must(pipe(pipe_files) == 0, "create pipe");
  pid_t reader = fork();
  must(reader >= 0, "fork reader");
  if (reader == 0) {
    close(pipe_files[1]);
    read_and_verify_payload(pipe_files[0]);
    _exit(0);
  }
  close(pipe_files[0]);
  interrupt_writes_every(1000);
  int result = rules_mkosi_write_all(pipe_files[1], payload, PAYLOAD_SIZE);
  stop_interrupting_writes();
  close(pipe_files[1]);
  must(waitpid(reader, &status, 0) == reader, "wait for reader");
  must(result == 0, "write_all completes despite interruptions");
  must(WIFEXITED(status) && WEXITSTATUS(status) == 0,
       "reader receives the complete payload");
  must(interruptions > 0, "the writer was interrupted");
  free(payload);
}

static void test_write_file_writes_existing_file(void) {
  char path[128];
  char contents[16] = {0};

  snprintf(path, sizeof(path), "write-all-test-%ld", (long)getpid());
  int file = open(path, O_CREAT | O_WRONLY | O_TRUNC | O_CLOEXEC, 0600);
  must(file >= 0 && close(file) == 0, "create target file");
  must(rules_mkosi_write_file(path, "0 1000 1\n", 9) == 0, "write file");
  file = open(path, O_RDONLY | O_CLOEXEC);
  must(file >= 0, "open written file");
  must(read(file, contents, sizeof(contents)) == 9, "read written file");
  must(close(file) == 0 && unlink(path) == 0, "remove written file");
  must(strcmp(contents, "0 1000 1\n") == 0, "file has the written contents");
  must(rules_mkosi_write_file(path, "x", 1) == -ENOENT,
       "a missing file is not created");
}

int main(void) {
  test_write_all_survives_partial_and_interrupted_writes();
  test_write_file_writes_existing_file();
  return 0;
}
