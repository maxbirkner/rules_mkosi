#include "launcher_config.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <string.h>
#include <unistd.h>

static char *join_path(const char *root, const char *relative) {
  size_t length = strlen(root) + 1 + strlen(relative) + 1;
  char *result = malloc(length);
  if (result == NULL) {
    return NULL;
  }
  snprintf(result, length, "%s/%s", root, relative);
  return result;
}

static char *python_home(const char *python) {
  char *home = strdup(python);
  if (home == NULL) {
    return NULL;
  }
  char *last_slash = strrchr(home, '/');
  if (last_slash == NULL) {
    free(home);
    return NULL;
  }
  *last_slash = '\0';
  last_slash = strrchr(home, '/');
  if (last_slash == NULL) {
    free(home);
    return NULL;
  }
  *last_slash = '\0';
  return home;
}

static void clear_host_injection_environment(void) {
  const char *variables[] = {
      "PYTHONPATH",       "PYTHONHOME",        "PYTHONSTARTUP",
      "PYTHONINSPECT",    "PYTHONUSERBASE",    "PYTHONWARNINGS",
      "PYTHONBREAKPOINT", "PYTHONHASHSEED",    "PYTHONIOENCODING",
      "PYTHONMALLOC",     "PYTHONCOERCECLOCALE", "PYTHONUTF8",
      "PYTHONFAULTHANDLER", "PYTHONDEVMODE",   "PYTHONTRACEMALLOC",
      "PYTHONPROFILEIMPORTTIME", "PYTHONINTMAXSTRDIGITS",
      "LD_PRELOAD",       "LD_LIBRARY_PATH",   "LD_AUDIT",
      "LD_DEBUG",         "LD_DEBUG_OUTPUT",   "LD_PROFILE",
      "LD_PROFILE_OUTPUT", "LD_USE_LOAD_BIAS",  "LD_ORIGIN_PATH",
      "LD_ASSUME_KERNEL", "LD_HWCAP_MASK",     "LD_HWCAP",
      "LD_PREFER_MAP_32BIT_EXEC", "LD_DYNAMIC_WEAK", "LD_BIND_NOW",
      "LD_WARN",          "LD_SHOW_AUXV",      "LD_TRACE_LOADED_OBJECTS",
      "LD_VERBOSE",       "LD_TRACE_PRELINKING", "GLIBC_TUNABLES",
      "GCONV_PATH",       "LOCPATH",           "NLSPATH",
      "NSS_MODULE_PATH",  "CHARSETALIASDIR",   "GETCONF_DIR",
  };
  for (size_t index = 0; index < sizeof(variables) / sizeof(variables[0]); ++index) {
    unsetenv(variables[index]);
  }
}

static void reset_inherited_signals(void) {
  sigset_t empty;
  sigemptyset(&empty);
  sigprocmask(SIG_SETMASK, &empty, NULL);
  struct sigaction default_action;
  memset(&default_action, 0, sizeof(default_action));
  default_action.sa_handler = SIG_DFL;
  sigemptyset(&default_action.sa_mask);
  const int signals[] = {SIGHUP,  SIGINT,  SIGQUIT, SIGILL,  SIGABRT,
                         SIGFPE,  SIGSEGV, SIGTERM, SIGCHLD, SIGPIPE,
                         SIGALRM, SIGUSR1, SIGUSR2};
  for (size_t index = 0; index < sizeof(signals) / sizeof(signals[0]); ++index) {
    sigaction(signals[index], &default_action, NULL);
  }
}

static char *manifest_lookup(const char *manifest, const char *logical) {
  FILE *file = fopen(manifest, "r");
  if (file == NULL) {
    return NULL;
  }
  char line[4096];
  while (fgets(line, sizeof(line), file) != NULL) {
    char *separator = strchr(line, ' ');
    if (separator == NULL) {
      continue;
    }
    *separator = '\0';
    if (strcmp(line, logical) != 0) {
      continue;
    }
    char *physical = separator + 1;
    physical[strcspn(physical, "\n")] = '\0';
    char *result = strdup(physical);
    fclose(file);
    return result;
  }
  fclose(file);
  return NULL;
}

static char *manifest_lookup(const char *manifest, const char *logical);

static char *repository_mapping(const char *apparent) {
  FILE *file = NULL;
  const char *root = getenv("RUNFILES_DIR");
  if (root != NULL && root[0] != '\0') {
    char *mapping = join_path(root, "_repo_mapping");
    if (mapping != NULL) {
      file = fopen(mapping, "r");
      free(mapping);
    }
  }
  if (file == NULL) {
    const char *manifest = getenv("RUNFILES_MANIFEST_FILE");
    char *mapping = manifest == NULL ? NULL : manifest_lookup(manifest, "_repo_mapping");
    if (mapping != NULL) {
      file = fopen(mapping, "r");
      free(mapping);
    }
  }
  if (file == NULL) {
    return NULL;
  }
  char line[4096];
  while (fgets(line, sizeof(line), file) != NULL) {
    char *first = strchr(line, ',');
    if (first == NULL) {
      continue;
    }
    char *second = strchr(first + 1, ',');
    if (second == NULL) {
      continue;
    }
    *second = '\0';
    if (strcmp(first + 1, apparent) != 0) {
      continue;
    }
    char *canonical = strdup(second + 1);
    if (canonical != NULL) {
      canonical[strcspn(canonical, "\n")] = '\0';
    }
    fclose(file);
    return canonical;
  }
  fclose(file);
  return NULL;
}

static char *runfile(const char *logical, const char *alternate) {
  const char *manifest = getenv("RUNFILES_MANIFEST_FILE");
  if (manifest != NULL && manifest[0] != '\0') {
    char *result = manifest_lookup(manifest, logical);
    if (result != NULL) {
      return result;
    }
    if (alternate != NULL) {
      result = manifest_lookup(manifest, alternate);
      if (result != NULL) {
        return result;
      }
    }
  }
  const char *root = getenv("RUNFILES_DIR");
  if (root == NULL || root[0] == '\0') {
    return NULL;
  }
  char *result = join_path(root, logical);
  if (result != NULL && access(result, R_OK) == 0) {
    return result;
  }
  free(result);
  result = NULL;
  if (alternate != NULL) {
    result = join_path(root, alternate);
    if (result != NULL && access(result, R_OK) == 0) {
      return result;
    }
  }
  free(result);
  return NULL;
}

int main(int argc, char **argv) {
  const char *runfiles_dir = getenv("RUNFILES_DIR");
  char derived_runfiles[4096];
  if ((runfiles_dir == NULL || runfiles_dir[0] == '\0') && argv[0] != NULL) {
    snprintf(derived_runfiles, sizeof(derived_runfiles), "%s.runfiles", argv[0]);
    setenv("RUNFILES_DIR", derived_runfiles, 1);
  }

  char *python = NULL;
  char *python_repository = repository_mapping("mkosi_debian_python");
  if (python_repository != NULL) {
    char logical_python[4096];
    char alternate_python[4096];
    snprintf(logical_python, sizeof(logical_python), "%s/bin/python3.11",
             python_repository);
    snprintf(alternate_python, sizeof(alternate_python),
             "_main/external/%s/bin/python3.11", python_repository);
    python = runfile(logical_python, alternate_python);
    free(python_repository);
  }
  if (python == NULL) {
    python = runfile(
        DEBIAN_TOOLS_PYTHON_RLOCATION,
        "_main/external/mkosi_debian_python/bin/python3.11");
  }
  char *script = runfile(DEBIAN_TOOLS_SCRIPT_RLOCATION,
                         DEBIAN_TOOLS_SCRIPT_ALTERNATE_RLOCATION);
  char *extractor = runfile(DEBIAN_TOOLS_EXTRACTOR_RLOCATION,
                            DEBIAN_TOOLS_EXTRACTOR_ALTERNATE_RLOCATION);
  char *rules_repository = repository_mapping("rules_mkosi");
  if (rules_repository != NULL) {
    char logical_script[4096];
    char logical_extractor[4096];
    char alternate_script[4096];
    char alternate_extractor[4096];
    if (strcmp(rules_repository, "_main") == 0) {
      snprintf(logical_script, sizeof(logical_script),
               "_main/mkosi/debian/debian_launcher.py");
      snprintf(logical_extractor, sizeof(logical_extractor),
               "_main/mkosi/debian/extract_tree.py");
    } else {
      snprintf(logical_script, sizeof(logical_script),
               "_main/external/%s/mkosi/debian/debian_launcher.py",
               rules_repository);
      snprintf(logical_extractor, sizeof(logical_extractor),
               "_main/external/%s/mkosi/debian/extract_tree.py",
               rules_repository);
    }
    snprintf(alternate_script, sizeof(alternate_script), "%s/mkosi/debian/debian_launcher.py",
             rules_repository);
    snprintf(alternate_extractor, sizeof(alternate_extractor), "%s/mkosi/debian/extract_tree.py",
             rules_repository);
    free(script);
    free(extractor);
    script = runfile(logical_script, alternate_script);
    extractor = runfile(logical_extractor, alternate_extractor);
    free(rules_repository);
  }
  char *archive = NULL;
  char *package_repository = repository_mapping("mkosi_debian_tools");
  if (package_repository != NULL) {
    char logical_archive[4096];
    snprintf(logical_archive, sizeof(logical_archive), "%s/flat.tar",
             package_repository);
    char alternate_archive[4096];
    snprintf(alternate_archive, sizeof(alternate_archive), "_main/external/%s/flat.tar",
             package_repository);
    archive = runfile(logical_archive, alternate_archive);
    free(package_repository);
  }
  if (archive == NULL) {
    archive = runfile(DEBIAN_TOOLS_ARCHIVE_RLOCATION, NULL);
  }
  if (archive == NULL) {
    archive = runfile("mkosi_debian_tools/flat.tar", NULL);
  }
  char *namespace_runner = NULL;
  char *tools_repository = repository_mapping("mkosi_debian_tools");
  if (tools_repository != NULL) {
    char logical_runner[4096];
    char alternate_runner[4096];
    snprintf(logical_runner, sizeof(logical_runner), "%s/namespace_runner",
             tools_repository);
    snprintf(alternate_runner, sizeof(alternate_runner),
             "_main/external/%s/namespace_runner", tools_repository);
    namespace_runner = runfile(logical_runner, alternate_runner);
    free(tools_repository);
  }
  if (namespace_runner == NULL) {
    namespace_runner = runfile(
        DEBIAN_TOOLS_NAMESPACE_RLOCATION,
        "_main/external/mkosi_debian_tools/namespace_runner");
  }
  if (python == NULL || script == NULL || extractor == NULL || archive == NULL ||
      namespace_runner == NULL) {
    fprintf(stderr, "Debian tools launcher runfiles are incomplete\n");
    free(python);
    free(script);
    free(extractor);
    free(archive);
    free(namespace_runner);
    return 1;
  }
  if (access(python, X_OK) != 0 || access(script, R_OK) != 0 ||
      access(extractor, R_OK) != 0 || access(archive, R_OK) != 0 ||
      access(namespace_runner, X_OK) != 0) {
    fprintf(stderr, "Debian tools launcher runfiles are not executable/readable\n");
    free(python);
    free(script);
    free(extractor);
    free(archive);
    free(namespace_runner);
    return 1;
  }

  clear_host_injection_environment();
  reset_inherited_signals();
  setenv("DEBIAN_TOOLS_ARCHIVE", archive, 1);
  setenv("DEBIAN_TOOLS_EXTRACTOR", extractor, 1);
  setenv("DEBIAN_TOOLS_NAMESPACE_RUNNER", namespace_runner, 1);
  setenv("DEBIAN_TOOLS_ARCHIVE_SHA256", DEBIAN_TOOLS_ARCHIVE_SHA256, 1);
  setenv("PATH", "", 1);
  setenv("PYTHONNOUSERSITE", "1", 1);
  char *home = python_home(python);
  if (home == NULL) {
    fprintf(stderr, "unable to determine managed Python home\n");
    return 1;
  }
  setenv("PYTHONHOME", home, 1);

  char **python_argv = calloc((size_t)argc + 3, sizeof(char *));
  if (python_argv == NULL) {
    fprintf(stderr, "unable to allocate Debian tools launcher arguments: %s\n",
            strerror(errno));
    return 1;
  }
  python_argv[0] = python;
  python_argv[1] = "-I";
  python_argv[2] = script;
  for (int index = 1; index < argc; ++index) {
    python_argv[index + 2] = argv[index];
  }
  python_argv[argc + 2] = NULL;
  execv(python, python_argv);
  fprintf(stderr, "unable to execute managed Python: %s: %s\n", python,
          strerror(errno));
  free(python_argv);
  free(home);
  free(python);
  free(script);
  free(extractor);
  free(archive);
  return 127;
}
