"""Validation of os-release image identity strings used for A/B updates."""

_ID_CHARACTERS = "abcdefghijklmnopqrstuvwxyz0123456789._-"
_VERSION_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789."

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
