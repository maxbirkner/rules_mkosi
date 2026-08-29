"""Version information replaced by git archive for releases."""

_VERSION_PRIVATE = "$Format:%(describe:tags=true)$"

VERSION = "0.0.0" if _VERSION_PRIVATE.startswith("$Format") else _VERSION_PRIVATE.replace("v", "", 1)
IS_PRERELEASE = VERSION == "0.0.0" or VERSION.find("g") >= 0
