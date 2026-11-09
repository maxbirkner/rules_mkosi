"""Validation of os-release image identity strings used for A/B updates."""

_ID_CHARACTERS = "abcdefghijklmnopqrstuvwxyz0123456789._-"
_VERSION_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789."

# GPT partition names hold at most 36 UTF-16 code units; systemd-repart silently replaces a longer Label=.
GPT_PARTITION_NAME_MAX = 36

# Hex characters, 64 bits, of the input digest that form a version derived with image_version_from_inputs;
# input_version.py uses the same length.
INPUT_VERSION_LENGTH = 16

def validate_image_id(image_id):
    """Fails unless image_id is a non-empty os-release IMAGE_ID.

    Args:
      image_id: Candidate IMAGE_ID string.
    """
    if not image_id or image_id.strip(_ID_CHARACTERS):
        fail("image_id must be non-empty and use only lowercase letters, digits, '.', '_' and '-': %r" % image_id)

def validate_image_version(image_version):
    """Fails unless image_version can be matched unambiguously by systemd-sysupdate patterns.

    systemd-sysupdate accepts only letters, digits and ".,_-+" in a version. '_' separates the image
    id from the version and '+'/'-' introduce systemd-boot boot-counting suffixes, so a version is
    restricted to letters, digits and '.'. image_version.py applies the same rule to image_version_file
    contents at execution time.

    Args:
      image_version: Candidate IMAGE_VERSION string.
    """
    if not image_version or image_version.strip(_VERSION_CHARACTERS):
        fail("image_version must be non-empty and use only letters, digits and '.': %r" % image_version)

def validate_slot_labels(image_id, image_version):
    """Fails unless the A/B root and verity partition labels fit in a GPT partition name.

    The populated slots are labelled '<image_id>_<image_version>' and '<image_id>_<image_version>_verity'. The
    verity label is the longer one. image_id and image_version are ASCII, so their length equals their UTF-16 length.
    image_version.py applies the same rule to image_version_file contents at execution time.

    Args:
      image_id: Validated IMAGE_ID string.
      image_version: Validated IMAGE_VERSION string.
    """
    label = "%s_%s_verity" % (image_id, image_version)
    if len(label) > GPT_PARTITION_NAME_MAX:
        fail(("A/B verity partition label '%s' is %d characters, but GPT partition names are limited to %d; " +
              "shorten image_id or image_version so that image_id + '_' + image_version + '_verity' fits") %
             (label, len(label), GPT_PARTITION_NAME_MAX))

def validate_input_version_slot_labels(image_id):
    """Fails unless the A/B partition labels of a version derived with image_version_from_inputs fit.

    Args:
      image_id: Validated IMAGE_ID string.
    """
    longest = GPT_PARTITION_NAME_MAX - len("__verity") - INPUT_VERSION_LENGTH
    if len(image_id) > longest:
        fail(("image_version_from_inputs derives %d-character versions, so with verity = \"hash\" image_id may have " +
              "at most %d characters to fit '<image_id>_<version>_verity' in a %d-character GPT partition name: %r") %
             (INPUT_VERSION_LENGTH, longest, GPT_PARTITION_NAME_MAX, image_id))
