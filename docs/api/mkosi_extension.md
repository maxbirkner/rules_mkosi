<!-- Generated with Stardoc: http://skydoc.bazel.build -->

Bazelmod extension for rules_mkosi toolchains.

<a id="mkosi"></a>

## mkosi

<pre>
mkosi = use_extension("@rules_mkosi//mkosi:extensions.bzl", "mkosi")
mkosi.toolchain(<a href="#mkosi.toolchain-name">name</a>, <a href="#mkosi.toolchain-version">version</a>)
</pre>

Creates `@mkosi_toolchains`: the pinned mkosi with its Python runtime, and QEMU, OVMF, and SeaBIOS.

rules_mkosi registers these toolchains itself.


**TAG CLASSES**

<a id="mkosi.toolchain"></a>

### toolchain

Selects the mkosi version of the `@mkosi_toolchains` repository.

The selected version is the root module's, or the default without one; a dependency module that requests another
version fails module resolution.

**Attributes**

| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="mkosi.toolchain-name"></a>name |  Logical toolchain name. Only the root module may override it.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | optional |  `"mkosi"`  |
| <a id="mkosi.toolchain-version"></a>version |  mkosi version, one of: 27.1.   | String | optional |  `"27.1"`  |


