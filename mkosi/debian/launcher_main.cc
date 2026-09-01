#include <errno.h>
#include <signal.h>
#include <unistd.h>

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include "rules_cc/cc/runfiles/runfiles.h"

namespace {

using rules_cc::cc::runfiles::Runfiles;

constexpr char kPythonRunfile[] = "mkosi_debian_python/python";
constexpr char kCliRunfile[] = "mkosi_debian_tools/launcher_cli";

void ClearHostInjectionEnvironment() {
  const char* variables[] = {
      "PYTHONPATH",
      "PYTHONHOME",
      "PYTHONSTARTUP",
      "PYTHONINSPECT",
      "PYTHONUSERBASE",
      "PYTHONWARNINGS",
      "PYTHONBREAKPOINT",
      "PYTHONHASHSEED",
      "PYTHONIOENCODING",
      "PYTHONMALLOC",
      "PYTHONCOERCECLOCALE",
      "PYTHONUTF8",
      "PYTHONFAULTHANDLER",
      "PYTHONDEVMODE",
      "PYTHONTRACEMALLOC",
      "PYTHONPROFILEIMPORTTIME",
      "PYTHONINTMAXSTRDIGITS",
      "LD_PRELOAD",
      "LD_LIBRARY_PATH",
      "LD_AUDIT",
      "LD_DEBUG",
      "LD_DEBUG_OUTPUT",
      "LD_PROFILE",
      "LD_PROFILE_OUTPUT",
      "LD_USE_LOAD_BIAS",
      "LD_ORIGIN_PATH",
      "LD_ASSUME_KERNEL",
      "LD_HWCAP_MASK",
      "LD_HWCAP",
      "LD_PREFER_MAP_32BIT_EXEC",
      "LD_DYNAMIC_WEAK",
      "LD_BIND_NOW",
      "LD_WARN",
      "LD_SHOW_AUXV",
      "LD_TRACE_LOADED_OBJECTS",
      "LD_VERBOSE",
      "LD_TRACE_PRELINKING",
      "GLIBC_TUNABLES",
      "GCONV_PATH",
      "LOCPATH",
      "NLSPATH",
      "NSS_MODULE_PATH",
      "CHARSETALIASDIR",
      "GETCONF_DIR",
  };
  for (const char* variable : variables) {
    unsetenv(variable);
  }
}

void ResetInheritedSignals() {
  sigset_t empty;
  sigemptyset(&empty);
  sigprocmask(SIG_SETMASK, &empty, nullptr);

  struct sigaction default_action {};
  default_action.sa_handler = SIG_DFL;
  sigemptyset(&default_action.sa_mask);
  const int signals[] = {SIGHUP,  SIGINT,  SIGQUIT, SIGILL,  SIGABRT,
                         SIGFPE,  SIGSEGV, SIGTERM, SIGCHLD, SIGPIPE,
                         SIGALRM, SIGUSR1, SIGUSR2};
  for (int signal : signals) {
    sigaction(signal, &default_action, nullptr);
  }
}

std::string ParentDirectory(const std::string& path) {
  const std::string::size_type separator = path.rfind('/');
  return separator == std::string::npos ? std::string() : path.substr(0, separator);
}

}  // namespace

int main(int argc, char** argv) {
  std::string error;
  std::unique_ptr<Runfiles> runfiles(
      Runfiles::Create(argv[0], BAZEL_CURRENT_REPOSITORY, &error));
  if (runfiles == nullptr) {
    std::cerr << "unable to initialize Debian launcher runfiles: " << error
              << '\n';
    return 1;
  }

  const std::string python = runfiles->Rlocation(kPythonRunfile);
  const std::string cli = runfiles->Rlocation(kCliRunfile);
  if (python.empty() || cli.empty() || access(python.c_str(), X_OK) != 0 ||
      access(cli.c_str(), R_OK) != 0) {
    std::cerr << "Debian tools launcher runfiles are incomplete\n";
    return 1;
  }

  for (const auto& variable : runfiles->EnvVars()) {
    setenv(variable.first.c_str(), variable.second.c_str(), 1);
  }
  ClearHostInjectionEnvironment();
  ResetInheritedSignals();
  setenv("PATH", "", 1);
  setenv("PYTHONNOUSERSITE", "1", 1);
  const std::string python_home = ParentDirectory(python);
  if (python_home.empty()) {
    std::cerr << "unable to determine managed Python home\n";
    return 1;
  }
  setenv("PYTHONHOME", python_home.c_str(), 1);

  std::vector<char*> python_argv;
  python_argv.reserve(static_cast<std::size_t>(argc) + 3);
  python_argv.push_back(const_cast<char*>(python.c_str()));
  python_argv.push_back(const_cast<char*>("-I"));
  python_argv.push_back(const_cast<char*>(cli.c_str()));
  for (int index = 1; index < argc; ++index) {
    python_argv.push_back(argv[index]);
  }
  python_argv.push_back(nullptr);

  execv(python.c_str(), python_argv.data());
  std::cerr << "unable to execute managed Python: " << python << ": "
            << std::strerror(errno) << '\n';
  return 127;
}
