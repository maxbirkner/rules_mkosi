"""Toolchain rule and provider for mkosi image assembly."""

MkosiToolchainInfo = provider(
    doc = "Information used to execute an mkosi image build.",
    fields = {
        "format_version": "String identifying the toolchain output contract.",
        "name": "Logical name of the selected toolchain.",
    },
)

def _mkosi_toolchain_impl(ctx):
    return [
        platform_common.ToolchainInfo(
            mkosi = MkosiToolchainInfo(
                format_version = ctx.attr.format_version,
                name = ctx.attr.toolchain_name,
            ),
        ),
    ]

mkosi_toolchain = rule(
    implementation = _mkosi_toolchain_impl,
    attrs = {
        "format_version": attr.string(
            default = "hello-v1",
            doc = "Output contract implemented by this toolchain.",
        ),
        "toolchain_name": attr.string(
            mandatory = True,
            doc = "Logical name exposed for diagnostics.",
        ),
    },
    doc = "Defines an mkosi toolchain.",
)
