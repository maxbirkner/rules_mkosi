"""GPT partition type GUIDs and slot labels shared by the rules_mkosi image tools.

Type GUIDs are lowercase strings, as projected into partition metadata.
"""

ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
ROOT_X86_64_VERITY = "2c7357ed-ebd2-46d9-aec1-23d437ec2bf5"
ROOT_X86_64_VERITY_SIG = "41092b05-9fc8-4523-994f-2def0408b176"
BIOS_BOOT = "21686148-6449-6e6f-744e-656564454649"
# systemd-sysupdate labels inactive A/B slots "_empty"; they carry no verity data.
EMPTY_SLOT_LABEL = "_empty"
