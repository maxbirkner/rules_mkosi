# Device tree fixtures of mkosi_image(devicetrees = ...)

`board.dts` is the smallest device tree that `devicetrees` accepts, a root node with a compatible string.
`devicetrees_test.bzl` compiles it with the `devicetree` rule for each fixture, with the compatible string from the `COMPATIBLE` define.
