"""Actions that run Python scripts with the managed interpreter of the mkosi toolchain."""

MKOSI_TOOLCHAIN_TYPE = "//mkosi/toolchain:toolchain_type"

# The interpreter must find no host programs and ignore the user's site-packages directory.
_ISOLATED_ENVIRONMENT = {
    "PATH": "",
    "PYTHONNOUSERSITE": "1",
}

def mkosi_toolchain_info(ctx):
    """Returns the MkosiToolchainInfo of the resolved mkosi toolchain."""
    return ctx.toolchains[MKOSI_TOOLCHAIN_TYPE].mkosi

def run_python(ctx, arguments, inputs, outputs, mnemonic, env = {}, transitive_inputs = None, tools = [], **kwargs):
    """Registers an action that runs a Python script with the managed mkosi toolchain interpreter.

    Args:
      ctx: Rule context of a rule that requires the mkosi toolchain.
      arguments: Interpreter arguments, starting with the script path.
      inputs: Files read by the action, including the script.
      outputs: Files written by the action.
      mnemonic: Action mnemonic.
      env: Variables added to the isolated environment.
      transitive_inputs: Input depsets; defaults to the managed Python runtime.
      tools: Additional FilesToRunProviders invoked by the script.
      **kwargs: Further ctx.actions.run arguments, such as progress_message.
    """
    mkosi = mkosi_toolchain_info(ctx)
    environment = dict(_ISOLATED_ENVIRONMENT)
    environment.update(env)
    ctx.actions.run(
        executable = mkosi.python,
        arguments = arguments,
        inputs = depset(
            inputs,
            transitive = [mkosi.python_runtime_files] if transitive_inputs == None else transitive_inputs,
        ),
        tools = [mkosi.python_files_to_run] + tools,
        outputs = outputs,
        env = environment,
        mnemonic = mnemonic,
        **kwargs
    )
