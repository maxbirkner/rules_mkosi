# Device tree source fixture

`board.dts` includes a dt-bindings header from `include/` and `soc.dtsi`, and takes its model from the `BOARD_MODEL` define.
The overlay `display.dtso` changes the board's `status_led` through its label and adds a node below `/soc` by path, with a revision from the `DISPLAY_REVISION` define.
`//mkosi/tests:devicetree_board` compiles them with the `devicetree` rule, and `devicetree_artifact_test` checks the result.
