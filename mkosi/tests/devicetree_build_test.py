"""Proves that the devicetree rule preprocesses, compiles and applies overlays like the Linux kernel's build."""

import struct
import sys

from mkosi.private import devicetree
from mkosi.tests.devicetree_fixture import read_nodes
from mkosi.tests.runfile_paths import resolve_runfile


def main() -> None:
    blob = resolve_runfile(sys.argv[1]).read_bytes()
    tree = devicetree.parse_device_tree(blob)
    # The blob ends with the device tree, so a UKI section holds nothing else.
    assert tree.size == len(blob), (tree.size, len(blob))
    assert tree.compatible == ("rules-mkosi,test-board", "rules-mkosi,test-soc"), tree.compatible
    nodes = read_nodes(blob)
    # BOARD_MODEL comes from defines, and soc.dtsi from a quoted include next to board.dts.
    assert nodes["/"]["model"] == b"rules-mkosi test board\0", nodes["/"]
    assert nodes["/soc"]["compatible"] == b"simple-bus\0", nodes["/soc"]
    led = nodes["/leds/led-status"]
    # LED_STATUS comes from <dt-bindings/rules-mkosi-leds.h> in an include directory.
    assert led["function-enumerator"] == struct.pack(">I", 7), led
    # The overlay changed the LED through its label and added a node by path, with DISPLAY_REVISION from defines.
    assert led["label"] == b"display-status\0", led
    display = nodes["/soc/display@1000"]
    assert display["compatible"] == b"rules-mkosi,test-display\0", display
    assert display["revision"] == struct.pack(">I", 3), display
    # The base was compiled with symbols, so that the overlay could refer to status_led.
    assert nodes["/__symbols__"]["status_led"] == b"/leds/led-status\0", nodes["/__symbols__"]


if __name__ == "__main__":
    main()
