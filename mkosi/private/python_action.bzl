"""Actions that run Python scripts with a hermetic interpreter, by default that of the mkosi toolchain."""

MKOSI_TOOLCHAIN_TYPE = "//mkosi/toolchain:toolchain_type"

# The interpreter must find no host programs and ignore the user's site-packages directory.
_ISOLATED_ENVIRONMENT = {
    "PATH": "",
    "PYTHONNOUSERSITE": "1",
}

def mkosi_toolchain_info(ctx):
    """Returns the MkosiToolchainInfo of the resolved mkosi toolchain."""
    return ctx.toolchains[MKOSI_TOOLCHAIN_TYPE].mkosi

def python_interpreter(executable, files_to_run, runtime_files = depset(), options = [], env = {}):
    """Describes an interpreter for run_python.

    Args:
      executable: Interpreter executable File.
      files_to_run: FilesToRunProvider of the interpreter.
      runtime_files: Depset of runtime files read by the interpreter.
      options: Interpreter options placed before the script path.
      env: Variables the interpreter needs, added to the isolated environment.
    """
    return struct(
        executable = executable,
        files_to_run = files_to_run,
        runtime_files = runtime_files,
        options = options,
        env = env,
    )

def static_python_interpreter(executable, files_to_run):
    """Describes a static interpreter that runs in isolated mode with its standard library next to it.

    Args:
      executable: Interpreter executable File.
      files_to_run: FilesToRunProvider of the interpreter.
    """
    return python_interpreter(
        executable,
        files_to_run,
        options = ["-I"],
        env = {"PYTHONHOME": executable.dirname},
    )

def _mkosi_interpreter(ctx):
    mkosi = mkosi_toolchain_info(ctx)
    return python_interpreter(mkosi.python, mkosi.python_files_to_run, mkosi.python_runtime_files)

def run_python(
        ctx,
        arguments,
        inputs,
        outputs,
        mnemonic,
        env = {},
        transitive_inputs = None,
        tools = [],
        interpreter = None,
        **kwargs):
    """Registers an action that runs a Python script in an isolated environment.

    Args:
      ctx: Rule context; it must require the mkosi toolchain unless interpreter is set.
      arguments: Interpreter arguments, starting with the script path.
      inputs: Files read by the action, including the script.
      outputs: Files written by the action.
      mnemonic: Action mnemonic.
      env: Variables added to the isolated environment.
      transitive_inputs: Input depsets; defaults to the interpreter runtime files.
      tools: Additional FilesToRunProviders invoked by the script.
      interpreter: python_interpreter to run; defaults to the managed mkosi toolchain interpreter.
      **kwargs: Further ctx.actions.run arguments, such as progress_message.
    """
    python = _mkosi_interpreter(ctx) if interpreter == None else interpreter
    ctx.actions.run(
        executable = python.executable,
        arguments = python.options + arguments,
        inputs = depset(
            inputs,
            transitive = [python.runtime_files] if transitive_inputs == None else transitive_inputs,
        ),
        tools = [python.files_to_run] + tools,
        outputs = outputs,
        env = _ISOLATED_ENVIRONMENT | python.env | env,
        mnemonic = mnemonic,
        **kwargs
    )
