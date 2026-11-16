# Consumer board device tree

`board.dts` takes its compatible string from `include/consumer-board.h` and its model from a define, and the overlay `display.dtso` prepends a more specific compatible string.
The `devicetree` rule compiles them into the device tree that `arm64_demo` embeds in its UKI.
