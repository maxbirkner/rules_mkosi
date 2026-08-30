#include "launcher_config.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
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

static char *manifest_python_lookup(const char *manifest) {
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
    size_t logical_length = strlen(line);
    size_t suffix_length = strlen("/bin/python3");
    if (strstr(line, "rules_python") == NULL ||
        strstr(line, "python_3_11_") == NULL ||
        logical_length < suffix_length ||
        strcmp(line + logical_length - suffix_length, "/bin/python3") != 0) {
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

static char *repository_mapping(const char *apparent) {
  const char *root = getenv("RUNFILES_DIR");
  if (root == NULL || root[0] == '\0') {
    return NULL;
  }
  char *mapping = join_path(root, "_repo_mapping");
  if (mapping == NULL) {
    return NULL;
  }
  FILE *file = fopen(mapping, "r");
  free(mapping);
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
  const char *manifest = getenv("RUNFILES_MANIFEST_FILE");
  if (manifest != NULL && manifest[0] != '\0') {
    python = manifest_python_lookup(manifest);
  }
  if (python == NULL) {
    python = runfile(
        DEBIAN_TOOLS_PYTHON_RLOCATION,
        "_main/external/rules_python~~python~python_3_11_x86_64-unknown-linux-gnu/bin/python3");
  }
  if (python == NULL) {
    python = runfile(
        "rules_python~~python~python_3_11_x86_64-unknown-linux-gnu/bin/python3",
        NULL);
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
  char *package_repository = repository_mapping("mkosi_debian_packages");
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
    archive = runfile(
        "rules_distroless~~apt~mkosi_debian_packages/flat.tar", NULL);
  }
  if (python == NULL || script == NULL || extractor == NULL || archive == NULL) {
    fprintf(stderr, "Debian tools launcher runfiles are incomplete\n");
    free(python);
    free(script);
    free(extractor);
    free(archive);
    return 1;
  }
  if (access(python, X_OK) != 0 || access(script, R_OK) != 0 ||
      access(extractor, R_OK) != 0 || access(archive, R_OK) != 0) {
    fprintf(stderr, "Debian tools launcher runfiles are not executable/readable\n");
    free(python);
    free(script);
    free(extractor);
    free(archive);
    return 1;
  }

  setenv("DEBIAN_TOOLS_ARCHIVE", archive, 1);
  setenv("DEBIAN_TOOLS_EXTRACTOR", extractor, 1);
  setenv("DEBIAN_TOOLS_ARCHIVE_SHA256", DEBIAN_TOOLS_ARCHIVE_SHA256, 1);
  setenv("PATH", "", 1);
  setenv("PYTHONNOUSERSITE", "1", 1);
  char *home = python_home(python);
  if (home == NULL) {
    fprintf(stderr, "unable to determine managed Python home\n");
    return 1;
  }
  setenv("PYTHONHOME", home, 1);

  char **python_argv = calloc((size_t)argc + 2, sizeof(char *));
  if (python_argv == NULL) {
    fprintf(stderr, "unable to allocate Debian tools launcher arguments: %s\n",
            strerror(errno));
    return 1;
  }
  python_argv[0] = python;
  python_argv[1] = script;
  for (int index = 1; index < argc; ++index) {
    python_argv[index + 1] = argv[index];
  }
  python_argv[argc + 1] = NULL;
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
