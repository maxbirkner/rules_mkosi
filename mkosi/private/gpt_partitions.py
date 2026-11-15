"""GPT partition type GUIDs and slot labels shared by the rules_mkosi image tools.

Type GUIDs are lowercase strings, as projected into partition metadata.
"""

from dataclasses import dataclass

ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
ROOT_X86_64_VERITY = "2c7357ed-ebd2-46d9-aec1-23d437ec2bf5"
ROOT_X86_64_VERITY_SIG = "41092b05-9fc8-4523-994f-2def0408b176"
ROOT_ARM64 = "b921b045-1df0-41c3-af44-4c6f280d3fae"
ROOT_ARM64_VERITY = "df3300ce-d69f-4c92-978c-9bfb0f38d820"
ROOT_ARM64_VERITY_SIG = "6db69de6-29f4-4758-a7a5-962190f00ce3"
BIOS_BOOT = "21686148-6449-6e6f-744e-656564454649"
# systemd-sysupdate labels inactive A/B slots "_empty"; they carry no verity data.
EMPTY_SLOT_LABEL = "_empty"
ESP = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


@dataclass(frozen=True)
class RootTypes:
    """The root partition types of one architecture, from the UAPI Discoverable Partitions Specification."""

    # The systemd-repart and systemd-sysupdate name of the root type, which mkosi also uses as the root's label.
    name: str
    root: str
    verity: str
    verity_sig: str


# The root partition types of each Debian architecture that an image may have.
_ROOT_TYPES = {
    "amd64": RootTypes("root-x86-64", ROOT_X86_64, ROOT_X86_64_VERITY, ROOT_X86_64_VERITY_SIG),
    "arm64": RootTypes("root-arm64", ROOT_ARM64, ROOT_ARM64_VERITY, ROOT_ARM64_VERITY_SIG),
}
ARCHITECTURES = tuple(sorted(_ROOT_TYPES))


def root_types(architecture: str) -> RootTypes:
    """Returns the root partition types of a Debian architecture, such as arm64; raises ValueError for others."""
    try:
        return _ROOT_TYPES[architecture]
    except KeyError:
        raise ValueError("unsupported image architecture {!r}".format(architecture)) from None
